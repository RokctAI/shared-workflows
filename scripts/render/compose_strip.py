#!/usr/bin/env python3
# Copyright (c) 2026 ROKCT INTELLIGENCE (PTY) LTD
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Compose a review strip: real-render PNGs + element-rect JSON -> ONE page.

Input is whatever `templates/render-harness/render_screen_test.dart` wrote
(see scripts/render/README.md for the whole pipeline): per variant a PNG of
the real Flutter screen and a sidecar JSON of measured element rectangles.
This script turns a set of those, plus a small strip config, into a single
self-contained HTML file.

Output shape is fixed by review convention and is NOT negotiable per thread:

  * ONE vertical scroll. Frames stack down the page (grouped into sections,
    side by side only where the viewport is wide enough). There is no
    pan/zoom canvas - a canvas that has to be dragged around has been
    explicitly rejected as a review format, because the reviewer cannot tell
    whether they have seen everything.
  * CSS phone bezels. The PNG is the screen; the bezel is drawn in CSS so
    the render itself is never letterboxed or scaled non-uniformly.
  * Orange (#FF6600) number chips, placed from the rect JSON - never by
    hand. A chip's position is derived from the element's measured rect, so
    it cannot drift out of sync with the render.
  * A per-frame legend keyed by the same numbers, a status pill per frame
    (SHIPPED / PROPOSED / BEFORE / HELD), free-text notes, and a chips
    on/off toggle: chips ON is review mode, chips OFF is presentation mode
    (client/investor-facing - the same page, no second export).

Numbering is global and stable, not per-frame and not positional. Every
element carries a KEY (the harness writes `key`; older harnesses that only
wrote `label` fall back to the label). A number is bound to a key once, in
`numbering.map`, and stays bound for the life of the page - so "point 14"
means the same thing in a revision three weeks later. Numbers freed by a
deleted element are NOT reused: they move to `numbering.retired` and render
as tombstones at the foot of the page. Keys the map does not know get the
next free number and are reported (with --emit-numbering, written back into
a merged map file to commit).

Everything is inlined - PNGs as base64 data URIs, CSS and JS in the page -
so the result is one file that can be attached, published, or opened from
disk with no network. By default it uses system font stacks for that
reason; `"fonts": "google"` in the config opts into the webfont link.

Run:
    python scripts/render/compose_strip.py --config strip.json --out strip.html
    python scripts/render/compose_strip.py --config strip.json --out strip.html \\
        --emit-numbering numbering.json
"""

import argparse
import base64
import html
import json
import os
import sys

# The four review states a frame may be in. Kept deliberately small: a
# reviewer should be able to hold the whole vocabulary in their head.
#   SHIPPED  - this is what main renders today
#   PROPOSED - this is what the change under review renders
#   BEFORE   - kept for contrast beside a PROPOSED frame
#   HELD     - drawn, deliberately not being built (parked, needs a decision)
STATUS_TAGS = {
    'SHIPPED': 'in main today',
    'PROPOSED': 'what this change renders',
    'BEFORE': 'prior state, shown for contrast',
    'HELD': 'parked - not being built yet',
}

CHIP_COLOR = '#FF6600'

# Chip anchor: the top-RIGHT corner of the element's rect, nudged so the chip
# straddles the corner rather than sitting inside the widget and covering it.
CHIP_SHIFT = 'translate(-70%,-30%)'


# ---------------------------------------------------------------------------
# Loading + validation
# ---------------------------------------------------------------------------

class ConfigError(Exception):
    """A strip config or harness output that cannot be composed."""


def _resolve(base_dir, path):
    return path if os.path.isabs(path) else os.path.join(base_dir, path)


def load_config(config_path):
    """Read the strip config; returns (config dict, base directory)."""
    with open(config_path, encoding='utf-8') as handle:
        config = json.load(handle)
    if not isinstance(config, dict):
        raise ConfigError('strip config must be a JSON object')
    if not config.get('frames'):
        raise ConfigError('strip config has no "frames"')
    base_dir = config.get('base_dir')
    config_dir = os.path.dirname(os.path.abspath(config_path))
    return config, _resolve(config_dir, base_dir) if base_dir else config_dir


def load_frame(frame, base_dir):
    """Load one frame's PNG bytes and rect JSON, validating both."""
    for key in ('png', 'rects'):
        if key not in frame:
            raise ConfigError(f'frame {frame.get("caption", "?")!r} has no "{key}"')

    status = frame.get('status')
    if status is not None and status not in STATUS_TAGS:
        raise ConfigError(
            f'frame {frame.get("caption", "?")!r} has unknown status {status!r}; '
            f'use one of {", ".join(sorted(STATUS_TAGS))}')

    png_path = _resolve(base_dir, frame['png'])
    rects_path = _resolve(base_dir, frame['rects'])
    for path in (png_path, rects_path):
        if not os.path.isfile(path):
            raise ConfigError(f'missing harness output: {path}')

    with open(png_path, 'rb') as handle:
        png_bytes = handle.read()
    with open(rects_path, encoding='utf-8') as handle:
        rects = json.load(handle)

    for key in ('logicalWidth', 'logicalHeight', 'elements'):
        if key not in rects:
            raise ConfigError(f'{rects_path}: rect JSON has no "{key}" - '
                              'is this a render-harness sidecar?')
    if not rects['logicalWidth'] or not rects['logicalHeight']:
        raise ConfigError(f'{rects_path}: zero logical size')
    return png_bytes, rects


def element_key(element):
    """The stable identity of an element: its `key`, else its label.

    The harness template writes an explicit `key` per finder spec. The
    original proof-of-concept harness only wrote `label`, so labels remain a
    valid (if more brittle - rewording the label rebinds the number) key.
    """
    return element.get('key') or element.get('label') or ''


# ---------------------------------------------------------------------------
# Numbering
# ---------------------------------------------------------------------------

def resolve_numbering(frames, config):
    """Bind every element key on the page to a stable global number.

    Returns (mapping key -> number, list of newly assigned keys). Numbers
    already in `numbering.map` are honoured; retired numbers are never
    handed out again; new keys take the next free number in first-seen order
    (frame order, then top-to-bottom within the frame).
    """
    numbering = config.get('numbering') or {}
    mapping = {str(k): int(v) for k, v in (numbering.get('map') or {}).items()}
    retired = {int(n) for n in (numbering.get('retired') or {})}

    taken = set(mapping.values()) | retired
    assigned = []
    next_free = 1

    for _frame, rects in frames:
        for element in rects['elements']:
            key = element_key(element)
            if not key:
                raise ConfigError('element with neither "key" nor "label"')
            if key in mapping:
                continue
            while next_free in taken:
                next_free += 1
            mapping[key] = next_free
            taken.add(next_free)
            assigned.append(key)
    return mapping, assigned


def merged_numbering(config, mapping):
    """The numbering block to write back so the next revision stays stable."""
    numbering = config.get('numbering') or {}
    return {
        'map': {k: mapping[k] for k in sorted(mapping, key=lambda k: mapping[k])},
        'retired': dict(numbering.get('retired') or {}),
    }


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

def esc(text):
    return html.escape(str(text), quote=True)


def legend_text(element, config, frame):
    """Display text for one legend row.

    Precedence: the frame's own override, then the page-wide `labels` alias
    map, then the raw label the harness measured. Aliases exist because a
    harness label is written for the person reading the test, and a legend
    row is written for the person reading the review.
    """
    key = element_key(element)
    overrides = frame.get('legend') or {}
    if key in overrides:
        return overrides[key]
    labels = config.get('labels') or {}
    if key in labels:
        return labels[key]
    if element.get('label') in labels:
        return labels[element['label']]
    return element.get('label') or key


def frame_html(frame, rects, png_bytes, config, mapping):
    """One phone frame: bezel, render, chips, legend, status pill, note."""
    width = float(rects['logicalWidth'])
    height = float(rects['logicalHeight'])
    b64 = base64.b64encode(png_bytes).decode('ascii')

    chips = []
    legend = []
    for element in rects['elements']:
        number = mapping[element_key(element)]
        # Chip rides the element's top-right corner, as a percentage of the
        # render so it survives any display scale.
        left = (float(element['x']) + float(element['w'])) / width * 100.0
        top = float(element['y']) / height * 100.0
        chips.append(f'<i class="chip" style="left:{left:.2f}%;top:{top:.2f}%">'
                     f'{number}</i>')
        legend.append(f'<span class="lg"><b>{number}</b>'
                      f'{esc(legend_text(element, config, frame))}</span>')

    ratio = height / width * 100.0
    status = frame.get('status')
    pill = ''
    if status:
        pill = (f'<span class="pill s-{status.lower()}" '
                f'title="{esc(STATUS_TAGS[status])}">{esc(status)}</span>')
    caption = esc(frame.get('caption', ''))
    note = frame.get('note')
    note_html = f'<div class="frame-note">{esc(note)}</div>' if note else ''

    return f'''
      <figure class="frame">
        <figcaption class="frame-head">{pill}<span class="frame-title">{caption}</span></figcaption>
        <div class="phone"><div class="screen">
          <div class="shot" style="padding-top:{ratio:.2f}%">
            <img src="data:image/png;base64,{b64}" alt="Real render - {caption}"
                 loading="lazy" width="{width:.0f}" height="{height:.0f}">
            <div class="chips">{''.join(chips)}</div>
          </div>
        </div></div>
        <div class="legend">{''.join(legend)}</div>
        {note_html}
      </figure>'''


def notes_html(config):
    """Free-text notes: what is real, what is stubbed, what was found."""
    blocks = []
    for note in config.get('notes') or []:
        kicker = note.get('kicker', 'note')
        body = note.get('body') or []
        if isinstance(body, str):
            body = [body]
        paragraphs = ''.join(f'<p>{esc(line)}</p>' for line in body)
        items = ''.join(f'<li>{esc(item)}</li>' for item in note.get('items') or [])
        list_html = f'<ul>{items}</ul>' if items else ''
        blocks.append(f'<aside class="note"><span class="nk">{esc(kicker)}</span>'
                      f'{paragraphs}{list_html}</aside>')
    return ''.join(blocks)


def tombstones_html(config):
    """Retired numbers, kept visible so nobody re-uses or re-asks about them."""
    retired = (config.get('numbering') or {}).get('retired') or {}
    if not retired:
        return ''
    rows = ''.join(
        f'<span class="lg"><b class="dead">{esc(number)}</b>{esc(what)}</span>'
        for number, what in sorted(retired.items(), key=lambda kv: int(kv[0])))
    return (f'<section class="tombstones"><h2>Retired numbers</h2>'
            f'<p class="sub">Removed from the design. The numbers are burnt - '
            f'never re-issued - so old review comments keep their meaning.</p>'
            f'<div class="legend">{rows}</div></section>')


def sections_html(config, frames, mapping):
    """Group frames into headed sections; one vertical scroll, no canvas."""
    order = []
    grouped = {}
    for (frame, rects), png_bytes in frames:
        name = frame.get('section', '')
        if name not in grouped:
            grouped[name] = []
            order.append(name)
        grouped[name].append(frame_html(frame, rects, png_bytes, config, mapping))

    out = []
    for name in order:
        head = ''
        if name:
            head = f'<div class="sec-head"><h2>{esc(name)}</h2></div>'
        out.append(f'<section class="sec">{head}'
                   f'<div class="frames">{"".join(grouped[name])}</div></section>')
    return ''.join(out)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

SYSTEM_STACK = ('-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,'
                '"Helvetica Neue",Arial,sans-serif')
MONO_STACK = ('ui-monospace,SFMono-Regular,Menlo,Consolas,'
              '"Liberation Mono",monospace')

GOOGLE_FONTS_LINK = (
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
    'family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500'
    '&display=swap">')


def build_page(config, frames, mapping):
    title = config.get('title', 'Real-render review strip')
    kicker = config.get('kicker', '')
    lede = config.get('lede', '')

    use_google = config.get('fonts') == 'google'
    font_link = GOOGLE_FONTS_LINK if use_google else ''
    body_font = f'"Inter",{SYSTEM_STACK}' if use_google else SYSTEM_STACK
    mono_font = f'"IBM Plex Mono",{MONO_STACK}' if use_google else MONO_STACK

    chips_on = config.get('chips_default', True)
    present_class = '' if chips_on else ' present'
    checked = ' checked' if chips_on else ''

    head = ''
    if kicker:
        head += f'<div class="kicker">{esc(kicker)}</div>'
    head += f'<h1>{esc(title)}</h1>'
    if lede:
        head += f'<p class="lede">{esc(lede)}</p>'

    return f'''<title>{esc(title)}</title>
{font_link}
<style>
  :root{{
    --paper:#F6F6F3; --ink:#22262B; --muted:#6B7178; --line:#E2E3DE;
    --card:#FFFFFF; --accent:#D95700; --accent-soft:#FBEADF;
    --bezel:#1A1C1F; --bezel-edge:#33363B;
  }}
  @media (prefers-color-scheme: dark){{
    :root:not([data-theme="light"]){{
      --paper:#141619; --ink:#E8EAEC; --muted:#9BA1A8; --line:#2B2E33;
      --card:#1C1F23; --accent:#FF8A3D; --accent-soft:#33231A;
      --bezel:#0E1012; --bezel-edge:#2A2D32;
    }}
  }}
  :root[data-theme="dark"]{{
    --paper:#141619; --ink:#E8EAEC; --muted:#9BA1A8; --line:#2B2E33;
    --card:#1C1F23; --accent:#FF8A3D; --accent-soft:#33231A;
    --bezel:#0E1012; --bezel-edge:#2A2D32;
  }}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--paper);color:var(--ink);
    font-family:{body_font};font-size:15px;line-height:1.55;
    -webkit-font-smoothing:antialiased}}
  .wrap{{max-width:1180px;margin:0 auto;padding:44px 22px 76px}}
  h1,h2{{margin:0;text-wrap:balance;letter-spacing:-.015em}}
  h1{{font-size:32px;font-weight:700}}
  .kicker{{font-family:{mono_font};font-size:11.5px;letter-spacing:.14em;
    text-transform:uppercase;color:var(--accent);margin-bottom:9px}}
  .lede{{color:var(--muted);max-width:66ch;margin:12px 0 0}}

  /* sticky control bar - the only chrome; chips off = presentation mode */
  .bar{{position:sticky;top:0;z-index:20;margin:26px 0 0;padding:10px 0;
    background:var(--paper);border-bottom:1px solid var(--line);
    display:flex;flex-wrap:wrap;align-items:center;gap:10px 16px}}
  .bar .hint{{font-size:12px;color:var(--muted)}}
  .mode{{margin-left:auto;display:inline-flex;align-items:center;gap:7px;
    font-size:12.5px;color:var(--muted);cursor:pointer;user-select:none}}
  .mode input{{accent-color:{CHIP_COLOR}}}
  .mode input:focus-visible{{outline:2px solid var(--accent);outline-offset:2px}}

  .sec{{margin-top:40px}}
  .sec-head{{border-bottom:1px solid var(--line);padding-bottom:10px;
    margin-bottom:22px}}
  .sec-head h2{{font-size:20px;font-weight:700}}
  .frames{{display:grid;gap:34px;
    grid-template-columns:repeat(auto-fit,minmax(340px,1fr));align-items:start;
    justify-items:center}}

  figure.frame{{margin:0;display:grid;gap:11px;justify-items:start;
    width:100%;max-width:412px}}
  .frame-head{{display:flex;flex-wrap:wrap;align-items:center;gap:8px}}
  .frame-title{{font-size:14px;font-weight:600}}
  .pill{{font-family:{mono_font};font-size:10px;letter-spacing:.12em;
    padding:3px 9px;border-radius:999px;font-weight:600;white-space:nowrap}}
  .s-shipped{{color:#FFF;background:{CHIP_COLOR}}}
  .s-proposed{{color:var(--accent);background:var(--accent-soft);
    box-shadow:inset 0 0 0 1px var(--accent)}}
  .s-before{{color:var(--muted);background:var(--card);
    box-shadow:inset 0 0 0 1px var(--line)}}
  .s-held{{color:var(--muted);background:transparent;
    box-shadow:inset 0 0 0 1px var(--muted);font-style:italic}}

  .phone{{width:100%;border-radius:44px;padding:10px;background:var(--bezel);
    box-shadow:0 18px 44px rgba(0,0,0,.28),inset 0 0 0 2px var(--bezel-edge)}}
  .screen{{border-radius:35px;overflow:hidden}}
  .shot{{position:relative;height:0;overflow:hidden}}
  .shot img{{position:absolute;inset:0;width:100%;height:100%;display:block}}
  .chips{{position:absolute;inset:0;pointer-events:none}}
  .chip{{position:absolute;z-index:6;min-width:17px;height:17px;padding:0 4px;
    border-radius:999px;background:{CHIP_COLOR};color:#FFF;font-style:normal;
    font-family:{mono_font};font-size:10px;font-weight:500;line-height:1;
    display:flex;align-items:center;justify-content:center;
    box-shadow:0 1px 3px rgba(0,0,0,.45);transform:{CHIP_SHIFT}}}

  .legend{{width:100%;font-size:11.5px;line-height:1.95;color:var(--muted);
    display:flex;flex-wrap:wrap;gap:2px 12px}}
  .legend .lg{{display:inline-flex;align-items:baseline;gap:4px}}
  .legend b{{font-family:{mono_font};font-weight:500;font-size:9.5px;color:#FFF;
    background:{CHIP_COLOR};border-radius:999px;min-width:15px;height:15px;
    padding:0 4px;display:inline-flex;align-items:center;justify-content:center;
    transform:translateY(2px)}}
  .legend b.dead{{background:transparent;color:var(--muted);
    box-shadow:inset 0 0 0 1px var(--muted);text-decoration:line-through}}
  .frame-note{{width:100%;font-family:{mono_font};font-size:10.5px;
    color:var(--muted)}}

  /* presentation mode: the same page with the review scaffolding hidden */
  .present .chips,.present .legend,.present .frame-note,
  .present .tombstones{{display:none}}

  .tombstones{{margin-top:44px;border-top:1px solid var(--line);padding-top:18px}}
  .tombstones h2{{font-size:15px;font-weight:600}}
  .tombstones .sub{{margin:4px 0 10px;font-size:12.5px;color:var(--muted);
    max-width:66ch}}

  aside.note{{margin:26px 0 0;border:1px solid var(--line);
    border-left:3px solid var(--accent);border-radius:12px;background:var(--card);
    padding:14px 18px;font-size:13.5px;color:var(--muted)}}
  aside.note .nk{{font-family:{mono_font};font-size:10px;letter-spacing:.12em;
    text-transform:uppercase;color:var(--accent);display:block;margin-bottom:6px}}
  aside.note p{{margin:0}}
  aside.note p+p{{margin-top:8px}}
  aside.note ul{{margin:8px 0 0;padding-left:18px;display:grid;gap:5px}}
  @media (max-width:820px){{h1{{font-size:26px}} .wrap{{padding:30px 13px 54px}}}}
</style>

<div class="wrap{present_class}" id="page">
  <header>{head}</header>

  <div class="bar">
    <span class="hint">Numbered points are measured from the widget tree, not
      placed by hand. Numbers are global and never re-used.</span>
    <label class="mode"><input type="checkbox" id="chipsToggle"{checked}>chips</label>
  </div>

  {sections_html(config, frames, mapping)}
  {tombstones_html(config)}
  {notes_html(config)}
</div>

<script>
  (function(){{
    var toggle = document.getElementById('chipsToggle');
    var page = document.getElementById('page');
    toggle.addEventListener('change', function(){{
      page.classList.toggle('present', !toggle.checked);
    }});
  }})();
</script>
'''


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def compose(config_path, out_path, emit_numbering=None, base_dir=None):
    """Compose the strip; returns (html text, numbering map, new keys)."""
    config, resolved_base = load_config(config_path)
    if base_dir:
        resolved_base = base_dir

    loaded = []
    for frame in config['frames']:
        png_bytes, rects = load_frame(frame, resolved_base)
        loaded.append(((frame, rects), png_bytes))

    mapping, assigned = resolve_numbering([pair for pair, _ in loaded], config)
    page = build_page(config, loaded, mapping)

    with open(out_path, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(page)

    if emit_numbering:
        with open(emit_numbering, 'w', encoding='utf-8', newline='\n') as handle:
            json.dump(merged_numbering(config, mapping), handle, indent=2)
            handle.write('\n')
    return page, mapping, assigned


def main():
    parser = argparse.ArgumentParser(
        description='Compose a real-render review strip (PNG + rect JSON -> '
                    'one self-contained HTML page).')
    parser.add_argument('--config', required=True,
                        help='strip config JSON (see scripts/render/README.md)')
    parser.add_argument('--out', required=True, help='output HTML path')
    parser.add_argument('--base-dir',
                        help='resolve frame paths against this directory '
                             '(default: the config\'s directory, or its '
                             '"base_dir")')
    parser.add_argument('--emit-numbering',
                        help='write the merged stable numbering map here, to '
                             'commit back into the config')
    args = parser.parse_args()

    try:
        page, mapping, assigned = compose(args.config, args.out,
                                          args.emit_numbering, args.base_dir)
    except (ConfigError, json.JSONDecodeError, OSError) as err:
        print(f'[ERROR] {err}', file=sys.stderr)
        return 1

    print(f'[INFO] wrote {args.out} ({len(page) // 1024} KB, '
          f'{len(mapping)} numbered elements)')
    if assigned:
        print(f'[INFO] {len(assigned)} new number(s) assigned: '
              + ', '.join(f'{mapping[k]} -> {k}' for k in assigned))
        if not args.emit_numbering:
            print('[WARNING] new numbers were auto-assigned but not written '
                  'back; re-run with --emit-numbering and commit the map, or '
                  'the next revision may renumber.')
    return 0


if __name__ == '__main__':
    sys.exit(main())

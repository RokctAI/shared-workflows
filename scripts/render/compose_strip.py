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
import re
import struct
import sys
import textwrap
import zlib

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

SVG_NS = 'http://www.w3.org/2000/svg'
XLINK_NS = 'http://www.w3.org/1999/xlink'

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
# Cross-frame repeats: chip each number ONCE
#
# A screen rendered in light AND dark puts every numbered element on both
# frames, so numbers 1-11 appear twice and the page reads as if it had 22
# points. The fix is not to alternate numbers between the frames - that would
# scatter one screen's elements across two pictures and you could no longer
# see element 1 in dark at all. Instead every number is chipped ONCE, on the
# first frame it appears in (its PRIMARY frame), and a later frame chips only
# the elements that actually CHANGED between the two renders.
#
# That second half is the part with real value. A light/dark pair differs
# everywhere in raw pixel terms - a naive per-pixel diff flags all of it - so
# the discriminator is the element's INTERNAL CONTRAST, not its colour:
#
#   * A tonal inversion (v -> 255-v, which is what a correct dark theme does
#     to a widget) leaves the standard deviation of luminance inside the
#     element's rect unchanged. Score ~0. Not flagged.
#   * An element that stops being legible - white ink left on a card that did
#     not flip, the exact paas_driver courier-profile bug where the name,
#     phone, "Balance"/"R0.00" and the delivered-order count all vanish -
#     collapses to a near-flat region. Its contrast falls to nothing. Score
#     ~1. Flagged.
#
# So a dark frame chips precisely the elements a reviewer needs to look at.
# Geometry is checked too: an element that moved or resized past a couple of
# logical pixels has changed whatever its contrast did.
#
# Everything is recoverable: the "repeats" checkbox in the mode bar shows the
# full set on every frame, which is the behaviour this replaced.
# ---------------------------------------------------------------------------

# Relative contrast change at which a repeat is called a real difference.
# 0.35 is deliberately tolerant: a dark theme that re-tints an accent shifts
# contrast a little, and only a collapse (or an appearance) should be flagged.
CHIP_CHANGE_THRESHOLD = 0.35
# Logical pixels an element may move or resize before that alone counts.
CHIP_MOVE_TOLERANCE = 2.0
# Cap on pixels sampled per element; the metric is a spread, not a checksum,
# so a few thousand samples say the same thing as a few million, far faster.
CHIP_SAMPLE_CAP = 4096

ROLE_PRIMARY = 'primary'   # first frame this number appears on - always chipped
ROLE_CHANGED = 'changed'   # a repeat that differs from its primary - chipped
ROLE_REPEAT = 'repeat'     # a repeat that matches its primary - hidden by default


def decode_png_luma(data):
    """Decode a PNG to (width, height, luminance bytes), or None.

    Stdlib only, on purpose: the composer has no third-party dependency and
    the tests synthesise their own PNGs. Handles what
    RepaintBoundary.toImage writes and what the tests build - 8-bit,
    non-interlaced, greyscale / RGB / grey+alpha / RGBA. Anything else
    returns None and the caller degrades to "cannot tell".
    """
    if len(data) < 8 or data[:8] != b'\x89PNG\r\n\x1a\n':
        return None
    pos, idat, ihdr = 8, [], None
    while pos + 8 <= len(data):
        length = struct.unpack('>I', data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        if kind == b'IHDR':
            ihdr = struct.unpack('>IIBBBBB', data[pos + 8:pos + 8 + length])
        elif kind == b'IDAT':
            idat.append(data[pos + 8:pos + 8 + length])
        elif kind == b'IEND':
            break
        pos += 12 + length
    if not ihdr or not idat:
        return None
    width, height, depth, color, compression, filtering, interlace = ihdr
    if depth != 8 or interlace != 0 or compression != 0 or filtering != 0:
        return None
    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(color)
    if not channels or not width or not height:
        return None
    try:
        raw = zlib.decompress(b''.join(idat))
    except zlib.error:
        return None
    stride = width * channels
    if len(raw) < (stride + 1) * height:
        return None

    luma = bytearray(width * height)
    prev = bytearray(stride)
    offset = 0
    for row_index in range(height):
        filter_type = raw[offset]
        offset += 1
        line = bytearray(raw[offset:offset + stride])
        offset += stride
        # The five PNG filters, undone in place (RFC 2083 section 6).
        if filter_type == 1:
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 255
        elif filter_type == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif filter_type == 3:
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 255
        elif filter_type == 4:
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                up = prev[i]
                up_left = prev[i - channels] if i >= channels else 0
                estimate = left + up - up_left
                da, db, dc = (abs(estimate - left), abs(estimate - up),
                              abs(estimate - up_left))
                if da <= db and da <= dc:
                    predictor = left
                elif db <= dc:
                    predictor = up
                else:
                    predictor = up_left
                line[i] = (line[i] + predictor) & 255
        elif filter_type != 0:
            return None

        base = row_index * width
        if channels == 1:
            luma[base:base + width] = line
        elif channels == 2:
            luma[base:base + width] = line[0::2]
        else:
            red, green, blue = line[0::channels], line[1::channels], line[2::channels]
            luma[base:base + width] = bytes(
                (299 * red[i] + 587 * green[i] + 114 * blue[i]) // 1000
                for i in range(width))
        prev = line
    return width, height, bytes(luma)


def _rect(element, key):
    """One rect field as a float. Tolerant: an older harness sidecar that
    never wrote `h` must degrade to "cannot measure", not crash the page."""
    try:
        return float(element[key])
    except (KeyError, TypeError, ValueError):
        return 0.0


def region_contrast(image, element, logical_width, logical_height):
    """Standard deviation of luminance inside one element's rect, or None.

    Invariant to a tonal inversion by construction, which is what makes it
    tell a dark THEME apart from a dark-mode BUG.
    """
    if image is None:
        return None
    width, height, luma = image
    scale_x = width / float(logical_width)
    scale_y = height / float(logical_height)
    x0 = max(0, int(_rect(element, 'x') * scale_x))
    y0 = max(0, int(_rect(element, 'y') * scale_y))
    x1 = min(width, int((_rect(element, 'x') + _rect(element, 'w')) * scale_x))
    y1 = min(height, int((_rect(element, 'y') + _rect(element, 'h')) * scale_y))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None

    span_x, span_y = x1 - x0, y1 - y0
    step = max(1, int(((span_x * span_y) / CHIP_SAMPLE_CAP) ** 0.5))
    total = squares = count = 0
    for y in range(y0, y1, step):
        row = y * width
        for x in range(x0, x1, step):
            value = luma[row + x]
            total += value
            squares += value * value
            count += 1
    if count < 4:
        return None
    mean = total / count
    variance = squares / count - mean * mean
    return variance ** 0.5 if variance > 0 else 0.0


def _moved(a, b):
    return any(abs(_rect(a, k) - _rect(b, k)) > CHIP_MOVE_TOLERANCE
               for k in ('x', 'y', 'w', 'h'))


def resolve_roles(loaded):
    """Classify every element on every frame as primary / changed / repeat.

    Returns a list parallel to ``loaded``: one ``{key: role}`` dict per
    frame. Numbering is untouched - this decides only what gets a chip
    DRAWN, never what number it carries, so a committed numbering map and
    --emit-numbering round-trip exactly as they did before.
    """
    images = {}

    def image_for(index, png_bytes):
        if index not in images:
            images[index] = decode_png_luma(png_bytes)
        return images[index]

    # Held UNMEASURED until a repeat actually turns up: a single-frame page
    # has nothing to compare, and decoding its PNG for a number nobody will
    # question is a second of CI time spent on nothing.
    primaries = {}   # key -> (frame index, rects, png bytes, element)
    measured = {}    # key -> contrast of the primary, computed on demand
    roles = []

    def primary_contrast(key):
        if key not in measured:
            index, rects, png_bytes, element = primaries[key]
            measured[key] = region_contrast(
                image_for(index, png_bytes), element,
                rects['logicalWidth'], rects['logicalHeight'])
        return measured[key]

    for index, ((frame, rects), png_bytes) in enumerate(loaded):
        frame_roles = {}
        for element in rects['elements']:
            key = element_key(element)
            if key not in primaries:
                primaries[key] = (index, rects, png_bytes, element)
                frame_roles[key] = ROLE_PRIMARY
                continue
            first_element = primaries[key][3]
            if _moved(first_element, element):
                frame_roles[key] = ROLE_CHANGED
                continue
            first_contrast = primary_contrast(key)
            contrast = region_contrast(
                image_for(index, png_bytes), element,
                rects['logicalWidth'], rects['logicalHeight'])
            if first_contrast is None or contrast is None:
                # Undecidable (unsupported PNG, degenerate rect). Stay with
                # the default - hidden - and let the toggle recover it.
                frame_roles[key] = ROLE_REPEAT
                continue
            spread = max(first_contrast, contrast, 1.0)
            delta = abs(first_contrast - contrast) / spread
            frame_roles[key] = (ROLE_CHANGED if delta >= CHIP_CHANGE_THRESHOLD
                                else ROLE_REPEAT)
        roles.append(frame_roles)
    return roles


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


def frame_points(frame, rects, config, mapping, roles=None):
    """The annotation model for one frame: one point per measured element.

    THE single definition of what a frame's annotation is. The HTML page's
    chips and legend and the SVG export's are both built from this list, so a
    chip cannot mean one thing on the review page and another in the deck,
    and a number cannot drift between the two.

    Each point carries the anchor in BOTH coordinate systems the two
    renderers need: percentages of the render (the page places chips with
    CSS, so it survives any display scale) and logical pixels (the SVG is
    laid out in the render's own logical pixels), plus its `role` from
    resolve_roles - primary / changed / repeat - which is what decides
    whether the chip is drawn by default.
    """
    width = float(rects['logicalWidth'])
    height = float(rects['logicalHeight'])
    points = []
    for element in rects['elements']:
        # Chip rides the element's top-RIGHT corner - see CHIP_SHIFT.
        anchor_x = float(element['x']) + float(element['w'])
        anchor_y = float(element['y'])
        points.append({
            'number': mapping[element_key(element)],
            'x': anchor_x,
            'y': anchor_y,
            'left_pct': anchor_x / width * 100.0,
            'top_pct': anchor_y / height * 100.0,
            'text': legend_text(element, config, frame),
            'role': (roles or {}).get(element_key(element), ROLE_PRIMARY),
        })
    return points


def frame_html(frame, rects, png_bytes, config, mapping, roles=None):
    """One phone frame: bezel, render, chips, legend, status pill, note.

    A point whose role is ROLE_REPEAT (already chipped on an earlier frame,
    and unchanged there) is marked `rep` rather than dropped: it is hidden by
    CSS, and the "repeats" checkbox shows the whole set again.
    """
    width = float(rects['logicalWidth'])
    height = float(rects['logicalHeight'])
    b64 = base64.b64encode(png_bytes).decode('ascii')

    chips = []
    legend = []
    repeats = 0
    changed = 0
    for point in frame_points(frame, rects, config, mapping, roles):
        cls = ''
        if point['role'] == ROLE_REPEAT:
            cls = ' rep'
            repeats += 1
        elif point['role'] == ROLE_CHANGED:
            cls = ' chg'
            changed += 1
        chips.append(f'<i class="chip{cls}" '
                     f'style="left:{point["left_pct"]:.2f}%;'
                     f'top:{point["top_pct"]:.2f}%">{point["number"]}</i>')
        legend.append(f'<span class="lg{cls}"><b>{point["number"]}</b>'
                      f'{esc(point["text"])}</span>')

    # Only a frame that actually repeats an earlier one gets the explainer,
    # so a single-frame page is unchanged from before.
    diff_html = ''
    if repeats or changed:
        if changed:
            diff_html = (
                f'<div class="frame-diff">Chipped here: the {changed} '
                f'element(s) that CHANGED from the first frame this screen '
                f'appears on. {repeats} unchanged point(s) are hidden - turn '
                f'"repeats" on to see every number again.</div>')
        else:
            diff_html = (
                f'<div class="frame-diff">Nothing measurably changed from '
                f'the first frame this screen appears on, so all {repeats} '
                f'numbers are hidden here - turn "repeats" on to see '
                f'them.</div>')

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
        {diff_html}
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


def sections_html(config, frames, mapping, roles_by_frame=None):
    """Group frames into headed sections; one vertical scroll, no canvas."""
    order = []
    grouped = {}
    for index, (((frame, rects), png_bytes)) in enumerate(frames):
        name = frame.get('section', '')
        if name not in grouped:
            grouped[name] = []
            order.append(name)
        roles = roles_by_frame[index] if roles_by_frame else None
        grouped[name].append(
            frame_html(frame, rects, png_bytes, config, mapping, roles))

    out = []
    for name in order:
        head = ''
        if name:
            head = f'<div class="sec-head"><h2>{esc(name)}</h2></div>'
        out.append(f'<section class="sec">{head}'
                   f'<div class="frames">{"".join(grouped[name])}</div></section>')
    return ''.join(out)


# ---------------------------------------------------------------------------
# SVG export
#
# The page is one long scroll, which is the right shape for a review and the
# wrong shape for placement: dropping a screen into a user guide or a pitch
# deck needs ONE file per frame that scales without going soft.
#
# So: one SVG per frame, in two variants, both self-contained.
#
#   * The screenshot is an embedded raster (`<image>` with a base64 data URI).
#     Flutter rasterises - there is no vector of the screen to recover, and
#     pretending otherwise would be a lie. It is embedded, not referenced, so
#     the file travels alone.
#   * EVERYTHING ELSE is real vector: chips are <circle> + <text>, the legend
#     and the caption are <text>. They stay sharp at any size on a slide, and
#     they stay selectable/editable in a design app.
#
# The two variants are the page's own two modes, not a second idea of what
# annotation means: `.present` on the HTML page hides .chips, .legend and
# .frame-note, so the clean SVG omits exactly those three and keeps the
# caption header, and both variants are built from the same frame_points().
# ---------------------------------------------------------------------------

SVG_PAD = 24.0            # margin around the whole card
SVG_HEAD_H = 34.0         # caption row height
SVG_GAP = 18.0            # gap between blocks
SVG_CHIP_R = 13.0         # chip radius, logical px
SVG_LEGEND_SIZE = 13.0    # legend/caption type size
SVG_LEGEND_LINE = 19.0    # legend line height
SVG_BEZEL = 10.0          # rounded corner of the screen
# Sans-serif metrics are close enough to 0.55em average advance for laying
# out a legend; the text is real text, so a browser or design app re-flows
# nothing - this only decides where WE break the lines.
SVG_CHAR_W = 0.55


def _slug(text):
    """Filesystem-safe, predictable, lowercase: driver_profile_dark."""
    slug = re.sub(r'[^A-Za-z0-9]+', '-', str(text)).strip('-').lower()
    return slug or 'frame'


def frame_slug(frame, rects):
    """The name a frame's SVGs are filed under.

    Prefers the harness's own `variant` (the sidecar's screen+variant name,
    e.g. driver_profile_dark), falling back to the PNG's stem. Predictable on
    purpose: a document references
    <output-dir>/svg/<slug>.annotated.svg by name, without guessing.
    """
    name = rects.get('variant') or os.path.splitext(
        os.path.basename(frame.get('png', '')))[0]
    return _slug(name)


def _svg_text(x, y, text, size, fill, weight='400', anchor='start',
              family='sans'):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size:.1f}" '
            f'font-family="{family}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}">{esc(text)}</text>')


def _wrap(text, avail_px, size):
    """Break legend text to the available width, in whole words."""
    per_line = max(8, int(avail_px / (size * SVG_CHAR_W)))
    return textwrap.wrap(str(text), width=per_line) or ['']


def frame_svg(frame, rects, png_bytes, config, mapping, present=False,
              roles=None):
    """One frame as a standalone SVG. `present` is the page's presentation
    mode: chips, legend and the frame note are dropped, exactly as the
    page's `.present` class hides them.

    Repeats are dropped here rather than hidden - an SVG has no checkbox, and
    the annotated export should say the same thing the page says by default.
    """
    width = float(rects['logicalWidth'])
    height = float(rects['logicalHeight'])
    points = [point for point
              in frame_points(frame, rects, config, mapping, roles)
              if point['role'] != ROLE_REPEAT]

    canvas_w = width + SVG_PAD * 2
    y = SVG_PAD

    parts = []
    caption = frame.get('caption', '') or frame_slug(frame, rects)
    status = frame.get('status')

    head = []
    text_x = SVG_PAD
    if status:
        pill_w = len(status) * SVG_LEGEND_SIZE * SVG_CHAR_W + 18.0
        head.append(f'<rect x="{SVG_PAD:.1f}" y="{y:.1f}" width="{pill_w:.1f}" '
                    f'height="22" rx="11" fill="#111"/>')
        head.append(_svg_text(SVG_PAD + pill_w / 2, y + 15.5, status,
                              11.0, '#fff', weight='700', anchor='middle'))
        text_x = SVG_PAD + pill_w + 10.0
    head.append(_svg_text(text_x, y + 15.5, caption, SVG_LEGEND_SIZE,
                          '#111', weight='600'))
    parts.append('<g class="head">' + ''.join(head) + '</g>')
    y += SVG_HEAD_H

    b64 = base64.b64encode(png_bytes).decode('ascii')
    href = f'data:image/png;base64,{b64}'
    clip = f'clip-{frame_slug(frame, rects)}'
    parts.append(
        f'<defs><clipPath id="{clip}">'
        f'<rect x="{SVG_PAD:.1f}" y="{y:.1f}" width="{width:.1f}" '
        f'height="{height:.1f}" rx="{SVG_BEZEL:.1f}"/></clipPath></defs>')
    parts.append(
        f'<g class="screen" clip-path="url(#{clip})">'
        f'<image x="{SVG_PAD:.1f}" y="{y:.1f}" width="{width:.1f}" '
        f'height="{height:.1f}" preserveAspectRatio="none" '
        f'href="{href}" xlink:href="{href}"/></g>')
    parts.append(
        f'<rect x="{SVG_PAD:.1f}" y="{y:.1f}" width="{width:.1f}" '
        f'height="{height:.1f}" rx="{SVG_BEZEL:.1f}" fill="none" '
        f'stroke="#dcdcdc" stroke-width="1"/>')

    if not present:
        chips = []
        for point in points:
            # Same anchor the page uses: the element's top-right corner,
            # nudged by CHIP_SHIFT (translate(-70%,-30%) of the chip box) so
            # the chip straddles the corner instead of covering the widget.
            cx = SVG_PAD + point['x'] - 0.4 * SVG_CHIP_R
            cy = y + point['y'] + 0.4 * SVG_CHIP_R
            chips.append(
                f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{SVG_CHIP_R:.1f}" '
                f'fill="{CHIP_COLOR}" stroke="#fff" stroke-width="2"/>')
            chips.append(_svg_text(cx, cy + 4.5, point['number'], 12.0,
                                   '#fff', weight='700', anchor='middle'))
        parts.append('<g class="chips">' + ''.join(chips) + '</g>')

    y += height

    if not present and points:
        y += SVG_GAP
        rows = []
        avail = width - (SVG_CHIP_R * 2 + 10.0)
        for point in points:
            cx = SVG_PAD + SVG_CHIP_R
            cy = y + SVG_CHIP_R - 3.0
            rows.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" '
                        f'r="{SVG_CHIP_R - 2:.1f}" fill="{CHIP_COLOR}"/>')
            rows.append(_svg_text(cx, cy + 4.0, point['number'], 11.0, '#fff',
                                  weight='700', anchor='middle'))
            for index, line in enumerate(_wrap(point['text'], avail,
                                               SVG_LEGEND_SIZE)):
                rows.append(_svg_text(
                    SVG_PAD + SVG_CHIP_R * 2 + 10.0,
                    cy + 4.0 + index * SVG_LEGEND_LINE, line,
                    SVG_LEGEND_SIZE, '#333'))
                if index:
                    y += SVG_LEGEND_LINE
            y += SVG_LEGEND_LINE + 5.0
        parts.append('<g class="legend">' + ''.join(rows) + '</g>')

    note = frame.get('note')
    if note and not present:
        y += SVG_GAP
        for line in _wrap(note, width, 12.0):
            parts.append(_svg_text(SVG_PAD, y, line, 12.0, '#666'))
            y += 17.0

    canvas_h = y + SVG_PAD
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="{SVG_NS}" xmlns:xlink="{XLINK_NS}" '
        f'viewBox="0 0 {canvas_w:.1f} {canvas_h:.1f}" '
        f'width="{canvas_w:.0f}" height="{canvas_h:.0f}">\n'
        f'<title>{esc(caption)}</title>\n'
        f'<desc>Real render of {esc(caption)} - the screen is an embedded '
        f'PNG, every chip, number and label is vector text.</desc>\n'
        f'<rect width="100%" height="100%" fill="#ffffff"/>\n'
        + '\n'.join(parts) + '\n</svg>\n')


def write_frame_svgs(loaded, config, mapping, out_dir, roles_by_frame=None):
    """Write <slug>.annotated.svg + <slug>.clean.svg per frame.

    One file per frame, not one combined file: these are placed individually
    into a document. Returns the list of paths written, in frame order.
    """
    os.makedirs(out_dir, exist_ok=True)
    written = []
    seen = {}
    for index, ((frame, rects), png_bytes) in enumerate(loaded):
        roles = roles_by_frame[index] if roles_by_frame else None
        slug = frame_slug(frame, rects)
        # Two frames can share a PNG (a before/after pair on one render);
        # keep the names unique and still predictable.
        seen[slug] = seen.get(slug, 0) + 1
        if seen[slug] > 1:
            slug = f'{slug}-{seen[slug]}'
        for suffix, present in (('annotated', False), ('clean', True)):
            path = os.path.join(out_dir, f'{slug}.{suffix}.svg')
            with open(path, 'w', encoding='utf-8', newline='\n') as handle:
                handle.write(frame_svg(frame, rects, png_bytes, config,
                                       mapping, present=present,
                                       roles=roles))
            written.append(path)
    return written


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


def build_page(config, frames, mapping, roles_by_frame=None):
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

    # Repeats OFF by default: every number appears exactly once on the page.
    # `repeats_default: true` in the config restores the old behaviour (every
    # element chipped on every frame it appears on) without touching the
    # markup - the checkbox drives the same class either way.
    repeats_on = config.get('repeats_default', False)
    repeats_class = ' repeats' if repeats_on else ''
    repeats_checked = ' checked' if repeats_on else ''

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

  /* A number is chipped once, on the first frame it appears on. A later
     frame keeps only the points that CHANGED there; the rest are `rep` and
     hidden until the repeats checkbox is ticked. */
  .chip.rep,.legend .lg.rep{{display:none}}
  .repeats .chip.rep{{display:flex}}
  .repeats .legend .lg.rep{{display:inline-flex}}
  /* A chip that survived onto a later frame is a real difference - ring it
     so the eye goes there first. */
  .chip.chg{{box-shadow:0 0 0 2px #FFF,0 1px 4px rgba(0,0,0,.5)}}
  .frame-diff{{width:100%;font-family:{mono_font};font-size:10.5px;
    color:var(--muted);margin-top:2px}}

  /* presentation mode: the same page with the review scaffolding hidden */
  .present .chips,.present .legend,.present .frame-note,
  .present .frame-diff,.present .tombstones{{display:none}}

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

<div class="wrap{present_class}{repeats_class}" id="page">
  <header>{head}</header>

  <div class="bar">
    <span class="hint">Numbered points are measured from the widget tree, not
      placed by hand. Numbers are global and never re-used.</span>
    <label class="mode"><input type="checkbox" id="chipsToggle"{checked}>chips</label>
    <label class="mode rep-mode"><input type="checkbox" id="repeatsToggle"{repeats_checked}>repeats</label>
  </div>

  {sections_html(config, frames, mapping, roles_by_frame)}
  {tombstones_html(config)}
  {notes_html(config)}
</div>

<script>
  (function(){{
    var toggle = document.getElementById('chipsToggle');
    var repeats = document.getElementById('repeatsToggle');
    var page = document.getElementById('page');
    toggle.addEventListener('change', function(){{
      page.classList.toggle('present', !toggle.checked);
    }});
    repeats.addEventListener('change', function(){{
      page.classList.toggle('repeats', repeats.checked);
    }});
  }})();
</script>
'''


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def compose(config_path, out_path, emit_numbering=None, base_dir=None,
            emit_svg=None):
    """Compose the strip; returns (html, numbering map, new keys, svg paths)."""
    config, resolved_base = load_config(config_path)
    if base_dir:
        resolved_base = base_dir

    loaded = []
    for frame in config['frames']:
        png_bytes, rects = load_frame(frame, resolved_base)
        loaded.append(((frame, rects), png_bytes))

    mapping, assigned = resolve_numbering([pair for pair, _ in loaded], config)
    # Numbering first, always: roles decide what is DRAWN, never what a
    # number is, so --emit-numbering round-trips exactly as before.
    roles_by_frame = resolve_roles(loaded)
    page = build_page(config, loaded, mapping, roles_by_frame)

    with open(out_path, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(page)

    if emit_numbering:
        with open(emit_numbering, 'w', encoding='utf-8', newline='\n') as handle:
            json.dump(merged_numbering(config, mapping), handle, indent=2)
            handle.write('\n')

    svgs = (write_frame_svgs(loaded, config, mapping, emit_svg, roles_by_frame)
            if emit_svg else [])
    return page, mapping, assigned, svgs


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
    parser.add_argument('--emit-svg',
                        help='also write one SVG per frame into this '
                             'directory, in an annotated and a clean '
                             'variant, for placing into a user guide or a '
                             'deck (the page itself stays the review format)')
    args = parser.parse_args()

    try:
        page, mapping, assigned, svgs = compose(args.config, args.out,
                                                args.emit_numbering,
                                                args.base_dir, args.emit_svg)
    except (ConfigError, json.JSONDecodeError, OSError) as err:
        print(f'[ERROR] {err}', file=sys.stderr)
        return 1

    print(f'[INFO] wrote {args.out} ({len(page) // 1024} KB, '
          f'{len(mapping)} numbered elements)')
    if svgs:
        print(f'[INFO] wrote {len(svgs)} SVG(s) to {args.emit_svg}: '
              + ', '.join(os.path.basename(path) for path in svgs))
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

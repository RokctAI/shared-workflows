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
import sys
import textwrap

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

# The device bezel and the type stack are drawn by BOTH the HTML page and the
# per-frame SVG export. They live here, once, so the two renderings cannot
# drift apart the way the status pill and the chip radius did.
BEZEL_FILL = '#1A1C1F'       # --bezel, light
BEZEL_FILL_DARK = '#0E1012'  # --bezel, dark
BEZEL_EDGE = '#33363B'       # --bezel-edge, light
BEZEL_EDGE_DARK = '#2A2D32'  # --bezel-edge, dark
BEZEL_PAD = 10.0             # .phone padding - the bezel around the screen
BEZEL_EDGE_W = 2.0           # .phone inset ring
BEZEL_RADIUS = 44.0          # .phone border-radius
SCREEN_RADIUS = 35.0         # .screen border-radius

# `sans` is NOT a CSS generic (the generic is `sans-serif`); left as the SVG
# default it resolves like an unknown family and falls back to a serif face
# in browsers and design apps alike. This is the page's own stack, quoted for
# an XML attribute - single quotes so it can sit inside font-family="...".
SYSTEM_STACK = ('-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,'
                '"Helvetica Neue",Arial,sans-serif')
SVG_FONT_STACK = SYSTEM_STACK.replace('"', "'")

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
# Cross-frame numbering: each number is carried by ONE frame, in turn
#
# A screen rendered in light AND dark puts every numbered element on both
# frames, so numbers 13-27 appear twice and the page reads as if it had 30
# points. The frames sit side by side, so a number only has to be said once -
# but it must be said on a frame that is worth looking at, and the rule this
# replaced ("the first frame owns every number; a later frame keeps only what
# measurably changed") left the dark frame bare.
#
# The rule is ALTERNATION, in numbering order: the first number is chipped on
# the first frame, the second on the second frame, the third on the first
# again, and so on. Both frames end up carrying roughly half the numbers, so
# neither picture is empty and the reviewer's eye crosses between them -
# which is the point, because the two renders are what is being compared.
#
# An element that exists on only ONE frame is always chipped there and does
# NOT consume an alternation slot, so a frame-specific element cannot push
# the split lopsided.
#
# Numbers stay GLOBAL: a number means the same element wherever it appears.
# This decides only which frame draws it. Everything is recoverable - the
# "repeats" checkbox in the mode bar puts every number back on every frame it
# exists on.
#
# NOTE: the per-frame SVG export deliberately does NOT alternate. It draws
# every numbered element present on the frame, because an exported SVG is
# used ALONE - in a guide, on a slide - with no second frame beside it to
# carry the other half. Page alternates, SVG is complete; see frame_svg.
# ---------------------------------------------------------------------------

ROLE_PRIMARY = 'primary'   # this frame carries the number - chipped
ROLE_REPEAT = 'repeat'     # another frame carries it - hidden on the PAGE
#                            (the SVG export draws it anyway; see frame_svg)


def resolve_roles(loaded, mapping):
    """Decide which frame carries each number.

    Returns a list parallel to ``loaded``: one ``{key: role}`` dict per
    frame. Numbering is untouched - this decides only what gets a chip DRAWN,
    never what number it carries, so a committed numbering map and
    --emit-numbering round-trip exactly as they did before.
    """
    # Which frames each key appears on, and the numbering order to walk.
    frames_for = {}
    for index, ((_frame, rects), _png) in enumerate(loaded):
        for element in rects['elements']:
            frames_for.setdefault(element_key(element), []).append(index)

    roles = [{} for _ in loaded]
    turn = 0
    for key in sorted(frames_for, key=lambda k: mapping[k]):
        appears_on = frames_for[key]
        if len(appears_on) == 1:
            # Only one frame can show it; it costs nobody a turn.
            roles[appears_on[0]][key] = ROLE_PRIMARY
            continue
        owner = appears_on[turn % len(appears_on)]
        turn += 1
        for index in appears_on:
            roles[index][key] = (ROLE_PRIMARY if index == owner
                                 else ROLE_REPEAT)
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
    resolve_roles - primary / repeat - which is what decides whether the
    PAGE draws the chip by default. The SVG export ignores the role and
    draws every point; see frame_svg.
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

    A point whose role is ROLE_REPEAT (its number is carried by another
    frame this turn) is marked `rep` rather than dropped: it is hidden by
    CSS, and the "repeats" checkbox shows the whole set again.
    """
    width = float(rects['logicalWidth'])
    height = float(rects['logicalHeight'])
    b64 = base64.b64encode(png_bytes).decode('ascii')

    chips = []
    legend = []
    repeats = 0
    carried = 0
    for point in frame_points(frame, rects, config, mapping, roles):
        cls = ''
        if point['role'] == ROLE_REPEAT:
            cls = ' rep'
            repeats += 1
        else:
            carried += 1
        chips.append(f'<i class="chip{cls}" '
                     f'style="left:{point["left_pct"]:.2f}%;'
                     f'top:{point["top_pct"]:.2f}%">{point["number"]}</i>')
        legend.append(f'<span class="lg{cls}"><b>{point["number"]}</b>'
                      f'{esc(point["text"])}</span>')

    # Only a frame that shares elements with another gets the explainer, so
    # a single-frame page is unchanged from before.
    diff_html = ''
    if repeats:
        diff_html = (
            f'<div class="frame-diff">This frame carries {carried} of the '
            f'numbers; the other {repeats} are chipped on the frame beside '
            f'it, so each number is said once. Turn "repeats" on to see '
            f'every number on every frame.</div>')

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
# The page's chip is a 17px box (min-width/height) - radius 8.5 - and its
# number is set at 10px. The SVG used 13.0, which drew a chip 2.3x the page's
# area: on the light driver frame chips 16 and 17 sit 11.8px apart, so 17
# buried ~80% of 16 and neither number could be read.
SVG_CHIP_R = 8.5          # chip radius, logical px - matches the page's 17px chip
SVG_CHIP_TEXT = 10.0      # chip number size, matching the page's .chip
SVG_LEGEND_CHIP_TEXT = 9.5  # matching the page's .legend b
SVG_LEGEND_SIZE = 13.0    # legend/caption type size
SVG_LEGEND_LINE = 19.0    # legend line height
# Sans-serif metrics are close enough to 0.55em average advance for laying
# out a legend; the text is real text, so a browser or design app re-flows
# nothing - this only decides where WE break the lines.
#
# Re-measured after the font-family fix, on the driver legend, at 13px:
# the widest line ("Host footer - app name, version, online dot and usage",
# 52 chars) measures 310.0px in the resolved stack - 0.459em average advance
# - against a 383px column. 0.55 therefore still OVER-estimates by ~20% and
# breaks lines early, which is the safe direction; it stays as it is. (Under
# the old `sans` it measured 352.3px in a 354px column: 1.7px of margin.)
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
              family=SVG_FONT_STACK):
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

    EVERY numbered point on the frame is drawn, repeats included. That is
    deliberately NOT what the page does: the page ALTERNATES, giving each
    number to one frame in turn, because its frames are read side by side and
    saying a number twice down the column is noise. An exported SVG is used
    ALONE - in a guide, on a slide - with no second frame beside it, so a
    frame that dropped its repeats would ship with unlabelled widgets and a
    legend that does not describe the picture.

    Page alternates, SVG is complete. Do not "fix" either to match the other.
    The numbers stay global either way: chip 13 is 13 on the light frame and
    on the dark one, never renumbered per file.
    """
    width = float(rects['logicalWidth'])
    height = float(rects['logicalHeight'])
    points = frame_points(frame, rects, config, mapping, roles)

    # The screen sits inside the bezel, so the card is the PHONE's width.
    phone_w = width + BEZEL_PAD * 2
    phone_h = height + BEZEL_PAD * 2
    canvas_w = phone_w + SVG_PAD * 2
    y = SVG_PAD

    parts = []
    caption = frame.get('caption', '') or frame_slug(frame, rects)
    status = frame.get('status')

    head = []
    text_x = SVG_PAD
    if status:
        pill_w = len(status) * SVG_LEGEND_SIZE * SVG_CHAR_W + 18.0
        head.append(f'<rect x="{SVG_PAD:.1f}" y="{y:.1f}" width="{pill_w:.1f}" '
                    f'height="22" rx="11" fill="{CHIP_COLOR}"/>')
        head.append(_svg_text(SVG_PAD + pill_w / 2, y + 15.5, status,
                              11.0, '#fff', weight='700', anchor='middle'))
        text_x = SVG_PAD + pill_w + 10.0
    head.append(_svg_text(text_x, y + 15.5, caption, SVG_LEGEND_SIZE,
                          '#111', weight='600'))
    parts.append('<g id="head" class="head">' + ''.join(head) + '</g>')
    y += SVG_HEAD_H

    b64 = base64.b64encode(png_bytes).decode('ascii')
    # ONE spelling of the reference, not two. Emitting the payload into both
    # href and xlink:href doubled every exported file for nothing.
    href = f'data:image/png;base64,{b64}'
    clip = f'clip-{frame_slug(frame, rects)}'
    screen_x = SVG_PAD + BEZEL_PAD
    screen_y = y + BEZEL_PAD

    # The page's .phone: a filled bezel with a 2px ring inset on its edge. A
    # CSS inset shadow paints inside the border box; an SVG stroke straddles
    # its path, so the ring is inset by half its width to land in the same
    # place.
    inset = BEZEL_EDGE_W / 2
    parts.append(
        f'<g id="bezel" class="bezel">'
        f'<rect x="{SVG_PAD:.1f}" y="{y:.1f}" width="{phone_w:.1f}" '
        f'height="{phone_h:.1f}" rx="{BEZEL_RADIUS:.1f}" '
        f'fill="{BEZEL_FILL}"/>'
        f'<rect x="{SVG_PAD + inset:.1f}" y="{y + inset:.1f}" '
        f'width="{phone_w - BEZEL_EDGE_W:.1f}" '
        f'height="{phone_h - BEZEL_EDGE_W:.1f}" '
        f'rx="{BEZEL_RADIUS - inset:.1f}" fill="none" '
        f'stroke="{BEZEL_EDGE}" stroke-width="{BEZEL_EDGE_W:.1f}"/></g>')

    parts.append(
        f'<defs><clipPath id="{clip}">'
        f'<rect x="{screen_x:.1f}" y="{screen_y:.1f}" width="{width:.1f}" '
        f'height="{height:.1f}" rx="{SCREEN_RADIUS:.1f}"/></clipPath></defs>')
    parts.append(
        f'<g id="screen" class="screen" clip-path="url(#{clip})">'
        f'<image x="{screen_x:.1f}" y="{screen_y:.1f}" width="{width:.1f}" '
        f'height="{height:.1f}" preserveAspectRatio="none" '
        f'xlink:href="{href}"/></g>')

    if not present:
        chips = []
        for point in points:
            # Same anchor the page uses: the element's top-right corner,
            # nudged by CHIP_SHIFT (translate(-70%,-30%) of the chip box) so
            # the chip straddles the corner instead of covering the widget.
            cx = screen_x + point['x'] - 0.4 * SVG_CHIP_R
            cy = screen_y + point['y'] + 0.4 * SVG_CHIP_R
            chips.append(
                f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{SVG_CHIP_R:.1f}" '
                f'fill="{CHIP_COLOR}" stroke="#fff" stroke-width="2"/>')
            chips.append(_svg_text(cx, cy + SVG_CHIP_TEXT * 0.35,
                                   point['number'], SVG_CHIP_TEXT,
                                   '#fff', weight='700', anchor='middle'))
        parts.append('<g id="chips" class="chips">' + ''.join(chips) + '</g>')

    y += phone_h

    if not present and points:
        y += SVG_GAP
        rows = []
        avail = phone_w - (SVG_CHIP_R * 2 + 10.0)
        for point in points:
            cx = SVG_PAD + SVG_CHIP_R
            cy = y + SVG_CHIP_R - 3.0
            rows.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" '
                        f'r="{SVG_CHIP_R - 1.0:.1f}" fill="{CHIP_COLOR}"/>')
            rows.append(_svg_text(cx, cy + SVG_LEGEND_CHIP_TEXT * 0.35,
                                  point['number'], SVG_LEGEND_CHIP_TEXT,
                                  '#fff', weight='700', anchor='middle'))
            for index, line in enumerate(_wrap(point['text'], avail,
                                               SVG_LEGEND_SIZE)):
                rows.append(_svg_text(
                    SVG_PAD + SVG_CHIP_R * 2 + 10.0,
                    cy + 4.0 + index * SVG_LEGEND_LINE, line,
                    SVG_LEGEND_SIZE, '#333'))
                if index:
                    y += SVG_LEGEND_LINE
            y += SVG_LEGEND_LINE + 5.0
        parts.append('<g id="legend" class="legend">' + ''.join(rows)
                     + '</g>')

    note = frame.get('note')
    if note and not present:
        y += SVG_GAP
        for line in _wrap(note, phone_w, 12.0):
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
    --bezel:{BEZEL_FILL}; --bezel-edge:{BEZEL_EDGE};
  }}
  @media (prefers-color-scheme: dark){{
    :root:not([data-theme="light"]){{
      --paper:#141619; --ink:#E8EAEC; --muted:#9BA1A8; --line:#2B2E33;
      --card:#1C1F23; --accent:#FF8A3D; --accent-soft:#33231A;
      --bezel:{BEZEL_FILL_DARK}; --bezel-edge:{BEZEL_EDGE_DARK};
    }}
  }}
  :root[data-theme="dark"]{{
    --paper:#141619; --ink:#E8EAEC; --muted:#9BA1A8; --line:#2B2E33;
    --card:#1C1F23; --accent:#FF8A3D; --accent-soft:#33231A;
    --bezel:{BEZEL_FILL_DARK}; --bezel-edge:{BEZEL_EDGE_DARK};
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

  .phone{{width:100%;border-radius:{BEZEL_RADIUS:.0f}px;
    padding:{BEZEL_PAD:.0f}px;background:var(--bezel);
    box-shadow:0 18px 44px rgba(0,0,0,.28),
      inset 0 0 0 {BEZEL_EDGE_W:.0f}px var(--bezel-edge)}}
  .screen{{border-radius:{SCREEN_RADIUS:.0f}px;overflow:hidden}}
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

  /* Each number is carried by ONE frame, alternating in numbering order,
     so light and dark each hold about half. The numbers a frame does not
     carry this turn are `rep` and hidden until the repeats checkbox is
     ticked. The SVG export does not alternate - see frame_svg. */
  .chip.rep,.legend .lg.rep{{display:none}}
  .repeats .chip.rep{{display:flex}}
  .repeats .legend .lg.rep{{display:inline-flex}}
  /* A chip that survived onto a later frame is a real difference - ring it
     so the eye goes there first. */
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
    roles_by_frame = resolve_roles(loaded, mapping)
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

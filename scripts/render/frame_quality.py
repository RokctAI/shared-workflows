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

"""Quality gate for rendered frames: refuse renders nobody should publish.

The render harness can finish green and still produce a frame that is
useless on a marketing site. Three shapes have actually shipped:

  * BLANK - the screen was captured before its demo data arrived. The frame
    is the page background, maybe a tab bar, maybe a spinner. Such frames
    have ~170-600 distinct colours and under 3% of pixels off the
    background; a real screen has 1000+ colours and 30%+ coverage.
  * LOADING - a CircularProgressIndicator is still on screen. The harness
    reports this itself in the sidecar (`quality.spinners`); a spinner on an
    otherwise empty page is also caught as BLANK.
  * BLOCK GLYPHS - text drawn in the FlutterTest/Ahem font because its
    family was never registered. Every glyph is a solid one-em box, so words
    become solid bars sitting on a flat background. The harness can report
    these (`quality.blockGlyphTexts`); the pixel check below catches them
    from any harness.

Nothing here needs third-party packages: PNGs are decoded with zlib (Pillow
is used only when it happens to be installed, for speed). The CLI prints one
line per frame and exits 1 if any frame is refused.

Run:  python scripts/render/frame_quality.py out/*.png
"""

import json
import os
import struct
import sys
import zlib

# Calibrated on real frames (sticks, polaris, paas_driver, paas_manager,
# supacharge; 2026-11-01). Blank frames measured 170-920 colours and
# 0.1-1.9% coverage; good frames 1000-3500 colours and 15-65% coverage.
MIN_COLOURS = 400
MIN_COVERAGE = 0.05
# An Ahem frame of the sticks team page measured 60+ solid word bars; good
# frames of every app measured 0-2.
MAX_BLOCK_GLYPHS = 6


class FrameRefused(Exception):
    """A frame that must not be composed or committed."""


# ---------------------------------------------------------------------------
# PNG decoding (8-bit, non-interlaced: what RepaintBoundary.toImage writes)
# ---------------------------------------------------------------------------

_CHANNELS = {0: 1, 2: 3, 4: 2, 6: 4}


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def decode_png(png_bytes):
    """Returns (width, height, rows) with each row a bytes object of RGB."""
    try:  # Fast path when Pillow is present; the result is identical.
        import io
        from PIL import Image  # type: ignore
        image = Image.open(io.BytesIO(png_bytes)).convert('RGB')
        width, height = image.size
        data = image.tobytes()
        stride = width * 3
        return width, height, [data[y * stride:(y + 1) * stride]
                               for y in range(height)]
    except ImportError:
        pass

    if png_bytes[:8] != b'\x89PNG\r\n\x1a\n':
        raise FrameRefused('not a PNG file')
    pos, idat, header = 8, [], None
    while pos < len(png_bytes):
        length, kind = struct.unpack('>I4s', png_bytes[pos:pos + 8])
        body = png_bytes[pos + 8:pos + 8 + length]
        if kind == b'IHDR':
            header = struct.unpack('>IIBBBBB', body)
        elif kind == b'IDAT':
            idat.append(body)
        elif kind == b'IEND':
            break
        pos += 12 + length
    if header is None:
        raise FrameRefused('PNG has no IHDR')
    width, height, depth, colour, _, _, interlace = header
    if depth != 8 or colour not in _CHANNELS or interlace:
        raise FrameRefused(f'unsupported PNG (depth {depth}, colour type '
                           f'{colour}, interlace {interlace}) - install '
                           'Pillow to check it')
    bpp = _CHANNELS[colour]
    stride = width * bpp
    raw = zlib.decompress(b''.join(idat))
    prev = bytearray(stride)
    rows = []
    for y in range(height):
        start = y * (stride + 1)
        ftype = raw[start]
        line = bytearray(raw[start + 1:start + 1 + stride])
        if ftype == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ftype == 2:
            line = bytearray((a + b) & 0xFF for a, b in zip(line, prev))
        elif ftype == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                upleft = prev[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + _paeth(left, prev[i], upleft)) & 0xFF
        prev = line
        if colour == 2:
            rows.append(bytes(line))
        elif colour == 6:
            rgb = bytearray(width * 3)
            rgb[0::3], rgb[1::3], rgb[2::3] = line[0::4], line[1::4], line[2::4]
            rows.append(bytes(rgb))
        else:  # greyscale (+alpha)
            grey = line[0::bpp]
            rgb = bytearray(width * 3)
            rgb[0::3] = rgb[1::3] = rgb[2::3] = grey
            rows.append(bytes(rgb))
    return width, height, rows


# ---------------------------------------------------------------------------
# Measurements
# ---------------------------------------------------------------------------

def colour_stats(width, rows):
    """(distinct colours, background colour, share of pixels off it)."""
    counts = {}
    for row in rows:
        for x in range(0, width * 3, 3):
            key = row[x:x + 3]
            counts[key] = counts.get(key, 0) + 1
    total = width * len(rows)
    background, most = max(counts.items(), key=lambda kv: kv[1])
    return len(counts), background, 1 - most / total


def _runs(row, width, min_len):
    """Runs of one exact colour at least min_len px long: (x0, x1, colour)."""
    out = []
    x = 0
    while x < width:
        colour = row[x * 3:x * 3 + 3]
        end = x + 1
        while end < width and row[end * 3:end * 3 + 3] == colour:
            end += 1
        if end - x >= min_len:
            out.append((x, end, colour))
        x = end
    return out


def _uniform(row, x0, x1, colour):
    if x0 < 0 or x1 > len(row) // 3:
        return False
    same = sum(1 for x in range(x0, x1) if row[x * 3:x * 3 + 3] == colour)
    return same >= 0.95 * (x1 - x0)


def block_glyphs(width, rows, dpr=3.0):
    """Count solid square-cornered bars sitting on a flat background.

    That is what a line of Ahem text looks like: each word a box of one exact
    colour, its edges straight, the same colour all round it. Real text is
    anti-aliased and never forms such a box; cards and buttons have rounded
    corners or something drawn inside them.
    """
    height = len(rows)
    min_w = max(4, int(6 * dpr))
    min_h = int(8 * dpr)
    max_h = int(48 * dpr)
    pad = 2
    open_blocks = {}
    finished = []
    for y in range(height):
        current = set(_runs(rows[y], width, min_w))
        for key in list(open_blocks):
            if key not in current:
                finished.append((key, open_blocks.pop(key), y - 1))
        for key in current:
            open_blocks.setdefault(key, y)
    finished.extend((key, top, height - 1) for key, top in open_blocks.items())

    count = 0
    for (x0, x1, colour), top, bottom in finished:
        h = bottom - top + 1
        if h < min_h or h > max_h or (x1 - x0) > 0.9 * width:
            continue
        above, below = top - pad, bottom + pad
        if above < 0 or below >= height:
            continue
        mid = rows[(top + bottom) // 2]
        left, right = x0 - pad, x1 - 1 + pad
        if left < 0 or right >= width:
            continue
        ground = mid[left * 3:left * 3 + 3]
        if ground == colour or mid[right * 3:right * 3 + 3] != ground:
            continue
        if (_uniform(rows[above], x0, x1, ground)
                and _uniform(rows[below], x0, x1, ground)):
            count += 1
    return count


def check_frame(png_bytes, rects=None, name='frame'):
    """Measures one frame; raises FrameRefused with every reason it fails.

    Returns the measurements dict when the frame passes.
    """
    rects = rects or {}
    dpr = float(rects.get('devicePixelRatio') or 3.0)
    width, height, rows = decode_png(png_bytes)
    colours, _, coverage = colour_stats(width, rows)
    blocks = block_glyphs(width, rows, dpr)
    reported = rects.get('quality') or {}
    spinners = int(reported.get('spinners') or 0)
    reported_blocks = int(reported.get('blockGlyphTexts') or 0)

    reasons = []
    if colours < MIN_COLOURS or coverage < MIN_COVERAGE:
        reasons.append(
            f'looks blank ({colours} colours, {coverage:.1%} of pixels off '
            f'the background; a real screen has {MIN_COLOURS}+ colours and '
            f'{MIN_COVERAGE:.0%}+ coverage) - the screen was probably '
            'captured before its demo data arrived')
    if spinners:
        reasons.append(f'{spinners} loading spinner(s) still on screen')
    if blocks > MAX_BLOCK_GLYPHS or reported_blocks:
        reasons.append(
            f'text drawn as block glyphs ({blocks} solid word bars found'
            + (f', harness reported {reported_blocks}' if reported_blocks
               else '')
            + ') - a font family the screen uses is not registered in '
            'loadRealFonts()')
    stats = {'width': width, 'height': height, 'colours': colours,
             'coverage': round(coverage, 4), 'blockGlyphs': blocks,
             'spinners': spinners}
    if reasons:
        raise FrameRefused(f'{name}: ' + '; '.join(reasons))
    return stats


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    refused = 0
    for path in argv:
        sidecar = os.path.splitext(path)[0] + '.json'
        rects = None
        if os.path.isfile(sidecar):
            with open(sidecar, encoding='utf-8') as handle:
                rects = json.load(handle)
        with open(path, 'rb') as handle:
            data = handle.read()
        try:
            stats = check_frame(data, rects, os.path.basename(path))
            print(f'[OK] {os.path.basename(path)}: {stats}')
        except FrameRefused as err:
            refused += 1
            print(f'[REFUSED] {err}')
    return 1 if refused else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

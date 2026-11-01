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

"""Tests for the render quality gate (scripts/render/frame_quality.py).

The gate exists so the tour bot never commits a frame that is blank, still
loading, or drawn in block glyphs. Fixtures are synthesised PNGs, so the
tests need no Flutter and no binary fixtures, and they run with and without
Pillow (the pure-zlib decoder is forced for one case).

Run:  python scripts/tests/test_render_frame_quality.py
"""

import json
import os
import struct
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'render'))

import compose_strip  # noqa: E402
import frame_quality  # noqa: E402


def _png(width, height, pixel, alpha=False):
    """An 8-bit PNG whose pixel (x, y) is pixel(x, y) -> (r, g, b).

    Rows cycle through the None, Sub and Up filters so the decoder has to
    undo each of them.
    """
    def chunk(kind, payload):
        body = kind + payload
        return (struct.pack('>I', len(payload)) + body
                + struct.pack('>I', zlib.crc32(body) & 0xFFFFFFFF))

    bpp = 4 if alpha else 3
    raw = bytearray()
    prev = None
    for y in range(height):
        line = bytearray()
        for x in range(width):
            line += bytes(pixel(x, y)) + (b'\xff' if alpha else b'')
        ftype = y % 3 if prev is not None else 0
        if ftype == 1:
            out = bytearray((line[i] - (line[i - bpp] if i >= bpp else 0))
                            & 0xFF for i in range(len(line)))
        elif ftype == 2:
            out = bytearray((a - b) & 0xFF for a, b in zip(line, prev))
        else:
            out = line
        raw.append(ftype)
        raw += out
        prev = line
    colour = 6 if alpha else 2
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height,
                                         8, colour, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(bytes(raw)))
            + chunk(b'IEND', b''))


GROUND = (246, 244, 240)


def good_screen(x, y):
    """Many colours over most of the frame, like a real populated screen."""
    if 20 <= x < 280 and 20 <= y < 280:
        return ((x * 7) % 256, (y * 5) % 256, ((x + y) * 3) % 256)
    return GROUND


def blank_screen(x, y):
    """The background and one small blob - a spinner on an empty page."""
    if 140 <= x < 150 and 140 <= y < 150:
        return (33, 150, 243)
    return GROUND


def block_glyph_screen(x, y):
    """Solid square bars on a flat card: words drawn in the Ahem font."""
    for row in range(4):
        top = 20 + row * 60
        for col in range(3):
            left = 20 + col * 90
            if left <= x < left + 70 and top <= y < top + 30:
                return (30, 30, 30)
    # Enough unrelated colour that only the glyph check can fail it.
    if y >= 260:
        return ((x * 7) % 256, (y * 11) % 256, (x * 3) % 256)
    return GROUND


class FrameQualityTest(unittest.TestCase):

    def check(self, pixel, rects=None, **kw):
        return frame_quality.check_frame(_png(300, 300, pixel, **kw),
                                         rects or {'devicePixelRatio': 3.0})

    def test_populated_frame_passes(self):
        stats = self.check(good_screen)
        self.assertGreater(stats['colours'], frame_quality.MIN_COLOURS)
        self.assertEqual(stats['blockGlyphs'], 0)

    def test_blank_frame_is_refused(self):
        with self.assertRaisesRegex(frame_quality.FrameRefused, 'looks blank'):
            self.check(blank_screen)

    def test_block_glyph_frame_is_refused(self):
        with self.assertRaisesRegex(frame_quality.FrameRefused,
                                    'block glyphs'):
            self.check(block_glyph_screen)

    def test_reported_spinner_is_refused(self):
        with self.assertRaisesRegex(frame_quality.FrameRefused, 'spinner'):
            self.check(good_screen, {'devicePixelRatio': 3.0,
                                     'quality': {'spinners': 1}})

    def test_rgba_and_pure_zlib_decoder_agree_with_rgb(self):
        saved = sys.modules.get('PIL', 'absent')
        sys.modules['PIL'] = None  # force the zlib decoder
        try:
            rgb = frame_quality.decode_png(_png(40, 30, good_screen))
            rgba = frame_quality.decode_png(_png(40, 30, good_screen,
                                                 alpha=True))
        finally:
            if saved == 'absent':
                del sys.modules['PIL']
            else:
                sys.modules['PIL'] = saved
        self.assertEqual(rgb, rgba)
        self.assertEqual(rgb[2][5][30:33], bytes(good_screen(10, 5)))


class ComposerGateTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name

    def run_compose(self, pixel, frame_extra=None, gate=True):
        with open(os.path.join(self.dir, 'a.png'), 'wb') as handle:
            handle.write(_png(300, 300, pixel))
        with open(os.path.join(self.dir, 'a.json'), 'w') as handle:
            json.dump({'logicalWidth': 100.0, 'logicalHeight': 100.0,
                       'devicePixelRatio': 3.0, 'elements': []}, handle)
        frame = {'png': 'a.png', 'rects': 'a.json', 'caption': 'A'}
        frame.update(frame_extra or {})
        config = os.path.join(self.dir, 'strip.json')
        with open(config, 'w') as handle:
            json.dump({'title': 'T', 'frames': [frame]}, handle)
        out = os.path.join(self.dir, 'strip.html')
        svg = os.path.join(self.dir, 'svg')
        compose_strip.compose(config, out, emit_svg=svg, quality_gate=gate)
        return out, svg

    def test_refused_frame_writes_nothing(self):
        with self.assertRaisesRegex(compose_strip.ConfigError,
                                    'quality gate refused 1 frame'):
            self.run_compose(blank_screen)
        self.assertFalse(os.path.exists(os.path.join(self.dir, 'strip.html')))
        self.assertFalse(os.path.exists(os.path.join(self.dir, 'svg')))

    def test_good_frame_composes(self):
        out, svg = self.run_compose(good_screen)
        self.assertTrue(os.path.isfile(out))
        self.assertTrue(os.listdir(svg))

    def test_frame_can_opt_out_for_a_deliberate_before_shot(self):
        out, _ = self.run_compose(blank_screen, {'quality_gate': False})
        self.assertTrue(os.path.isfile(out))


if __name__ == '__main__':
    unittest.main()

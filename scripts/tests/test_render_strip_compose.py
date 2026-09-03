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


"""Tests for the review-strip composer (scripts/render/compose_strip.py).

The composer's job is to make a review page that cannot lie about the render
it came from, so the guarded properties are the ones a reviewer relies on:

1. Numbers are GLOBAL and STABLE. The same element key carries the same
   number in every frame on the page, a committed numbering map is honoured
   verbatim, and a retired number is never handed out to a new element - so a
   comment saying "26 is too tight" still means what it meant last week.
2. Chips are placed from measured rects, one per element, per frame.
3. The status vocabulary is closed. An unknown tag is an error, not a pill
   the reviewer has to guess at.
4. The page is self-contained (images inlined, no external fetches) and is a
   single scroll - no pan/zoom canvas, which is a rejected review format.
5. Presentation mode exists: a chips toggle plus the CSS that hides the
   review scaffolding.

Fixtures are synthesised here (a 1x1 PNG built by hand, rect JSON written to
a temp dir), so the tests need no Flutter, no clones and no binary fixtures.

Run:  python scripts/tests/test_render_strip_compose.py
      python -m unittest discover -s scripts/tests    (also works)
"""

import json
import os
import re
import struct
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'render'))

import compose_strip  # noqa: E402


def _png_bytes():
    """A valid 1x1 opaque PNG, built here so no binary fixture is needed."""
    def chunk(kind, payload):
        body = kind + payload
        return (struct.pack('>I', len(payload)) + body
                + struct.pack('>I', zlib.crc32(body) & 0xFFFFFFFF))

    header = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', header)
            + chunk(b'IDAT', zlib.compress(b'\x00\xff\x66\x00'))
            + chunk(b'IEND', b''))


def _rects(elements):
    return {
        'variant': 'test',
        'logicalWidth': 390.0,
        'logicalHeight': 800.0,
        'devicePixelRatio': 3.0,
        'elements': elements,
    }


def _element(number, key, label, y):
    return {'number': number, 'key': key, 'label': label,
            'x': 16.0, 'y': y, 'w': 358.0, 'h': 64.0}


class ComposerTestCase(unittest.TestCase):
    """Base: writes harness-shaped outputs into a temp dir."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name

    def write_frame(self, name, elements):
        with open(os.path.join(self.dir, f'{name}.png'), 'wb') as handle:
            handle.write(_png_bytes())
        with open(os.path.join(self.dir, f'{name}.json'), 'w',
                  encoding='utf-8') as handle:
            json.dump(_rects(elements), handle)

    def compose(self, config, emit=None):
        path = os.path.join(self.dir, 'strip.json')
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(config, handle)
        out = os.path.join(self.dir, 'strip.html')
        return compose_strip.compose(path, out, emit_numbering=emit)


class NumberingTests(ComposerTestCase):

    def test_same_key_keeps_one_number_across_frames(self):
        """Global, not per-frame: a before/after pair must agree."""
        self.write_frame('a', [_element(1, 'hdr', 'Header', 10),
                               _element(2, 'row', 'Row', 90)])
        # Second frame drops the header, so positional numbering would slide
        # 'row' from 2 to 1 - the exact failure the key binding prevents.
        self.write_frame('b', [_element(1, 'row', 'Row', 10)])

        _page, mapping, _new = self.compose({
            'title': 'T',
            'frames': [
                {'png': 'a.png', 'rects': 'a.json', 'caption': 'A'},
                {'png': 'b.png', 'rects': 'b.json', 'caption': 'B'},
            ],
        })
        self.assertEqual(mapping['hdr'], 1)
        self.assertEqual(mapping['row'], 2)

    def test_committed_map_is_honoured_and_new_keys_append(self):
        self.write_frame('a', [_element(1, 'hdr', 'Header', 10),
                               _element(2, 'new', 'New thing', 90)])
        _page, mapping, new = self.compose({
            'title': 'T',
            'frames': [{'png': 'a.png', 'rects': 'a.json', 'caption': 'A'}],
            'numbering': {'map': {'hdr': 7}},
        })
        self.assertEqual(mapping['hdr'], 7, 'committed number was renumbered')
        self.assertEqual(new, ['new'])
        self.assertEqual(mapping['new'], 1, 'new key should take a free number')

    def test_retired_numbers_are_never_reissued(self):
        self.write_frame('a', [_element(1, 'fresh', 'Fresh', 10)])
        _page, mapping, _new = self.compose({
            'title': 'T',
            'frames': [{'png': 'a.png', 'rects': 'a.json', 'caption': 'A'}],
            'numbering': {'map': {}, 'retired': {'1': 'deleted card'}},
        })
        self.assertEqual(mapping['fresh'], 2,
                         'a retired number was handed to a new element')

    def test_retired_numbers_render_as_tombstones(self):
        self.write_frame('a', [_element(1, 'fresh', 'Fresh', 10)])
        page, _mapping, _new = self.compose({
            'title': 'T',
            'frames': [{'png': 'a.png', 'rects': 'a.json', 'caption': 'A'}],
            'numbering': {'retired': {'26': 'expandable cards block'}},
        })
        self.assertIn('Retired numbers', page)
        self.assertIn('expandable cards block', page)
        self.assertIn('class="dead"', page)

    def test_emit_numbering_writes_a_committable_map(self):
        self.write_frame('a', [_element(1, 'hdr', 'Header', 10)])
        emit = os.path.join(self.dir, 'numbering.json')
        self.compose({
            'title': 'T',
            'frames': [{'png': 'a.png', 'rects': 'a.json', 'caption': 'A'}],
            'numbering': {'retired': {'4': 'gone'}},
        }, emit=emit)
        with open(emit, encoding='utf-8') as handle:
            written = json.load(handle)
        self.assertEqual(written['map'], {'hdr': 1})
        self.assertEqual(written['retired'], {'4': 'gone'})

    def test_label_is_the_fallback_key(self):
        """Pre-`key` harness output still composes, keyed by label."""
        element = _element(1, None, 'Identity header', 10)
        del element['key']
        self.write_frame('a', [element])
        _page, mapping, _new = self.compose({
            'title': 'T',
            'frames': [{'png': 'a.png', 'rects': 'a.json', 'caption': 'A'}],
        })
        self.assertEqual(mapping['Identity header'], 1)


class PageShapeTests(ComposerTestCase):

    def _two_frame_page(self):
        self.write_frame('light', [_element(1, 'hdr', 'Header', 10),
                                   _element(2, 'row', 'Row', 90)])
        self.write_frame('dark', [_element(1, 'hdr', 'Header', 10),
                                  _element(2, 'row', 'Row', 90)])
        page, _mapping, _new = self.compose({
            'title': 'Screen review',
            'labels': {'hdr': 'identity header'},
            'frames': [
                {'png': 'light.png', 'rects': 'light.json', 'section': 'Now',
                 'caption': 'light', 'status': 'SHIPPED', 'note': 'main abc123'},
                {'png': 'dark.png', 'rects': 'dark.json', 'section': 'Now',
                 'caption': 'dark', 'status': 'PROPOSED'},
            ],
        })
        return page

    def test_one_chip_per_element_per_frame(self):
        page = self._two_frame_page()
        self.assertEqual(page.count('class="chip"'), 4)

    def test_chip_position_comes_from_the_measured_rect(self):
        """left = (x + w) / logicalWidth, top = y / logicalHeight, as %."""
        self.write_frame('a', [_element(1, 'hdr', 'Header', 200.0)])
        page, _mapping, _new = self.compose({
            'title': 'T',
            'frames': [{'png': 'a.png', 'rects': 'a.json', 'caption': 'A'}],
        })
        match = re.search(r'class="chip" style="left:([\d.]+)%;top:([\d.]+)%"',
                          page)
        self.assertIsNotNone(match, 'chip carries no measured position')
        self.assertAlmostEqual(float(match.group(1)),
                               (16.0 + 358.0) / 390.0 * 100, places=1)
        self.assertAlmostEqual(float(match.group(2)),
                               200.0 / 800.0 * 100, places=1)

    def test_status_pills_render_and_the_vocabulary_is_closed(self):
        page = self._two_frame_page()
        self.assertIn('>SHIPPED<', page)
        self.assertIn('>PROPOSED<', page)
        self.assertIn('class="pill s-shipped"', page)

        self.write_frame('x', [_element(1, 'hdr', 'Header', 10)])
        with self.assertRaises(compose_strip.ConfigError) as caught:
            self.compose({
                'title': 'T',
                'frames': [{'png': 'x.png', 'rects': 'x.json',
                            'caption': 'X', 'status': 'WIP'}],
            })
        self.assertIn('unknown status', str(caught.exception))

    def test_legend_uses_alias_then_frame_override(self):
        page = self._two_frame_page()
        self.assertIn('identity header', page)

        self.write_frame('y', [_element(1, 'hdr', 'Header', 10)])
        page, _mapping, _new = self.compose({
            'title': 'T',
            'labels': {'hdr': 'page-wide alias'},
            'frames': [{'png': 'y.png', 'rects': 'y.json', 'caption': 'Y',
                        'legend': {'hdr': 'frame override'}}],
        })
        self.assertIn('frame override', page)
        self.assertNotIn('page-wide alias', page)

    def test_page_is_self_contained_and_single_scroll(self):
        page = self._two_frame_page()
        self.assertIn('data:image/png;base64,', page)
        external = re.findall(r'(?:src|href)="(https?://[^"]+)"', page)
        self.assertEqual(external, [], 'page reaches out to the network')
        self.assertNotIn('<canvas', page, 'pan/zoom canvas is a rejected format')

    def test_presentation_mode_toggle_exists(self):
        page = self._two_frame_page()
        self.assertIn('id="chipsToggle"', page)
        self.assertIn('.present .chips', page)
        self.assertIn("classList.toggle('present'", page)

    def test_chips_default_false_ships_in_presentation_mode(self):
        self.write_frame('a', [_element(1, 'hdr', 'Header', 10)])
        page, _mapping, _new = self.compose({
            'title': 'T', 'chips_default': False,
            'frames': [{'png': 'a.png', 'rects': 'a.json', 'caption': 'A'}],
        })
        self.assertIn('class="wrap present"', page)
        self.assertNotIn('id="chipsToggle" checked', page)

    def test_theme_aware_chrome(self):
        page = self._two_frame_page()
        self.assertIn('prefers-color-scheme: dark', page)
        self.assertIn(':root[data-theme="dark"]', page)
        self.assertIn(':root:not([data-theme="light"])', page)

    def test_notes_and_sections_render(self):
        self.write_frame('a', [_element(1, 'hdr', 'Header', 10)])
        page, _mapping, _new = self.compose({
            'title': 'T',
            'frames': [{'png': 'a.png', 'rects': 'a.json', 'caption': 'A',
                        'section': 'Shipped today'}],
            'notes': [{'kicker': 'what is stubbed',
                       'body': ['the network fetch'],
                       'items': ['nav hooks are no-ops']}],
        })
        self.assertIn('Shipped today', page)
        self.assertIn('what is stubbed', page)
        self.assertIn('the network fetch', page)
        self.assertIn('<li>nav hooks are no-ops</li>', page)

    def test_captions_and_labels_are_escaped(self):
        self.write_frame('a', [_element(1, 'hdr', '<b>Header</b> & co', 10)])
        page, _mapping, _new = self.compose({
            'title': 'T',
            'frames': [{'png': 'a.png', 'rects': 'a.json',
                        'caption': 'A <script>x</script>'}],
        })
        self.assertNotIn('<script>x</script>', page)
        self.assertIn('&lt;b&gt;Header&lt;/b&gt; &amp; co', page)


class InputValidationTests(ComposerTestCase):

    def test_missing_harness_output_is_a_clear_error(self):
        with self.assertRaises(compose_strip.ConfigError) as caught:
            self.compose({
                'title': 'T',
                'frames': [{'png': 'nope.png', 'rects': 'nope.json',
                            'caption': 'A'}],
            })
        self.assertIn('missing harness output', str(caught.exception))

    def test_non_harness_json_is_rejected(self):
        with open(os.path.join(self.dir, 'a.png'), 'wb') as handle:
            handle.write(_png_bytes())
        with open(os.path.join(self.dir, 'a.json'), 'w',
                  encoding='utf-8') as handle:
            json.dump({'hello': 'world'}, handle)
        with self.assertRaises(compose_strip.ConfigError) as caught:
            self.compose({
                'title': 'T',
                'frames': [{'png': 'a.png', 'rects': 'a.json',
                            'caption': 'A'}],
            })
        self.assertIn('render-harness sidecar', str(caught.exception))

    def test_config_without_frames_is_rejected(self):
        with self.assertRaises(compose_strip.ConfigError):
            self.compose({'title': 'T', 'frames': []})


class WorkedExampleTests(unittest.TestCase):
    """The shipped example config must stay loadable and self-consistent."""

    EXAMPLE = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'render', 'examples', 'lms-profile.strip.json')

    def test_example_config_is_valid(self):
        with open(self.EXAMPLE, encoding='utf-8') as handle:
            config = json.load(handle)
        self.assertEqual(len(config['frames']), 4)
        for frame in config['frames']:
            self.assertIn(frame['status'], compose_strip.STATUS_TAGS)

        numbers = list(config['numbering']['map'].values())
        self.assertEqual(len(numbers), len(set(numbers)),
                         'the committed numbering map has a duplicate number')
        retired = {int(n) for n in config['numbering']['retired']}
        self.assertFalse(retired & set(numbers),
                         'a retired number is still in use')


if __name__ == '__main__':
    unittest.main(verbosity=2)

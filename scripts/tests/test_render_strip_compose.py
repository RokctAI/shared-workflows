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
import xml.dom.minidom
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


def _png_grid(width, height, ink, ground=(250, 250, 250)):
    """A real multi-pixel RGB PNG: horizontal bars of `ink` on `ground`.

    Passing ink == ground makes a FLAT image - the "white ink left on a white
    card" shape the dark-mode chip diff is there to catch.
    """
    def chunk(kind, payload):
        body = kind + payload
        return (struct.pack('>I', len(payload)) + body
                + struct.pack('>I', zlib.crc32(body) & 0xFFFFFFFF))

    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter: None
        colour = ink if (y // 4) % 2 else ground
        raw += bytes(colour) * width
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height,
                                         8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(bytes(raw)))
            + chunk(b'IEND', b''))


def _rects(elements, variant='test'):
    return {
        'variant': variant,
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

    def write_frame(self, name, elements, png=None):
        with open(os.path.join(self.dir, f'{name}.png'), 'wb') as handle:
            handle.write(png if png is not None else _png_bytes())
        with open(os.path.join(self.dir, f'{name}.json'), 'w',
                  encoding='utf-8') as handle:
            json.dump(_rects(elements, variant=name), handle)

    def compose(self, config, emit=None):
        """(page, mapping, new keys) - the SVG paths have their own helper."""
        page, mapping, assigned, _svgs = self.compose_full(config, emit=emit)
        return page, mapping, assigned

    def compose_full(self, config, emit=None, emit_svg=None):
        path = os.path.join(self.dir, 'strip.json')
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(config, handle)
        out = os.path.join(self.dir, 'strip.html')
        return compose_strip.compose(path, out, emit_numbering=emit,
                                     emit_svg=emit_svg)


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

    def test_one_chip_per_element_and_repeats_are_marked(self):
        """Every element still gets a chip on every frame it appears on -
        but a repeat is marked `rep`, not drawn a second time by default."""
        page = self._two_frame_page()
        self.assertEqual(page.count('class="chip"'), 2, 'primary chips')
        self.assertEqual(page.count('class="chip rep"'), 2, 'repeat chips')

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


class SvgExportTests(ComposerTestCase):
    """One SVG per frame, for dropping into a user guide or a deck.

    The page is the review format; these are the placement format. What has
    to hold: one file per FRAME (not one combined file), a genuine vector
    wrapper (the screenshot is the only raster in it), self-contained,
    predictable names, and a chip-free variant beside the annotated one.
    """

    def _emit(self, **frame_extra):
        self.write_frame('profile_light', [_element(1, 'hdr', 'Header', 10),
                                           _element(2, 'row', 'Row', 200)])
        out = os.path.join(self.dir, 'svg')
        frame = {'png': 'profile_light.png', 'rects': 'profile_light.json',
                 'caption': 'courier profile - light', 'status': 'SHIPPED'}
        frame.update(frame_extra)
        _page, _mapping, _new, svgs = self.compose_full(
            {'title': 'T', 'labels': {'hdr': 'Identity header'},
             'frames': [frame]}, emit_svg=out)
        return out, svgs

    def _read(self, out, name):
        with open(os.path.join(out, name), encoding='utf-8') as handle:
            return handle.read()

    def test_two_files_per_frame_named_from_the_variant(self):
        out, svgs = self._emit()
        self.assertEqual(sorted(os.path.basename(p) for p in svgs),
                         ['profile-light.annotated.svg',
                          'profile-light.clean.svg'])
        for path in svgs:
            self.assertTrue(os.path.isfile(path))
        self.assertEqual(len(svgs), 2, 'one annotated + one clean per frame')

    def test_one_file_per_frame_not_one_combined_file(self):
        self.write_frame('a', [_element(1, 'hdr', 'Header', 10)])
        self.write_frame('b', [_element(1, 'hdr', 'Header', 10)])
        out = os.path.join(self.dir, 'svg')
        _p, _m, _n, svgs = self.compose_full({
            'title': 'T',
            'frames': [
                {'png': 'a.png', 'rects': 'a.json', 'caption': 'A'},
                {'png': 'b.png', 'rects': 'b.json', 'caption': 'B'},
            ]}, emit_svg=out)
        self.assertEqual(len(svgs), 4, 'two frames -> four files')

    def test_is_a_vector_wrapper_not_a_flattened_bitmap(self):
        """The screen is the ONLY raster; the annotation is real vector."""
        out, _svgs = self._emit()
        svg = self._read(out, 'profile-light.annotated.svg')
        self.assertEqual(svg.count('<image '), 1,
                         'exactly one raster - the screenshot')
        self.assertGreaterEqual(svg.count('<circle '), 2, 'chips are shapes')
        self.assertGreaterEqual(svg.count('<text '), 4, 'chips/labels are text')

    def test_chip_number_is_selectable_text_in_the_markup(self):
        out, _svgs = self._emit()
        svg = self._read(out, 'profile-light.annotated.svg')
        numbers = re.findall(r'<text[^>]*>(\d+)</text>', svg)
        self.assertIn('1', numbers)
        self.assertIn('2', numbers)

    def test_legend_labels_are_vector_text(self):
        out, _svgs = self._emit()
        svg = self._read(out, 'profile-light.annotated.svg')
        self.assertIn('>Identity header<', svg,
                      'the alias, as real text, not baked into a bitmap')

    def test_clean_variant_drops_the_annotation(self):
        out, _svgs = self._emit()
        clean = self._read(out, 'profile-light.clean.svg')
        annotated = self._read(out, 'profile-light.annotated.svg')
        self.assertEqual(clean.count('<circle '), 0, 'no chips')
        self.assertNotIn('>Identity header<', clean, 'no legend')
        self.assertEqual(clean.count('<image '), 1, 'the screen survives')
        self.assertIn('>courier profile - light<', clean, 'caption survives')
        self.assertLess(len(clean), len(annotated))

    def test_self_contained_no_external_references(self):
        out, _svgs = self._emit()
        for name in ('profile-light.annotated.svg', 'profile-light.clean.svg'):
            svg = self._read(out, name)
            self.assertIn('data:image/png;base64,', svg)
            self.assertEqual(re.findall(r'href="(?!data:)([^"]+)"', svg), [],
                             f'{name} references something outside itself')

    def test_it_is_well_formed_xml(self):
        out, svgs = self._emit()
        for path in svgs:
            xml.dom.minidom.parse(path)

    def test_no_svg_is_written_unless_asked(self):
        self.write_frame('a', [_element(1, 'hdr', 'Header', 10)])
        _p, _m, _n, svgs = self.compose_full(
            {'title': 'T',
             'frames': [{'png': 'a.png', 'rects': 'a.json', 'caption': 'A'}]})
        self.assertEqual(svgs, [])

    def test_the_payload_is_emitted_once_not_into_two_attributes(self):
        """The screenshot is the whole file; writing it twice doubled it."""
        out, svgs = self._emit()
        for path in svgs:
            svg = self._read(out, os.path.basename(path))
            self.assertEqual(svg.count('data:image/png;base64,'), 1,
                             f'{os.path.basename(path)} carries the base64 '
                             'payload more than once')
            self.assertEqual(svg.count('<image '), 1)

    def test_the_reference_is_the_xlink_spelling(self):
        """SVG 1.1's spelling, which every design-app importer reads.

        Chromium, librsvg and cairosvg all resolve either spelling, so the
        renderers cast no vote; the SVG 1.1 importers in Illustrator,
        Affinity and Figma are the ones that only read `xlink:href`.
        """
        out, _svgs = self._emit()
        svg = self._read(out, 'profile-light.clean.svg')
        self.assertIn('xlink:href="data:image/png;base64,', svg)
        self.assertNotIn(' href="data:', svg, 'the SVG 2 spelling is dropped')
        self.assertIn(f'xmlns:xlink="{compose_strip.XLINK_NS}"', svg,
                      'xlink: is only legal with its namespace declared')

    def test_chip_radius_matches_the_page(self):
        """The page's chip is a 17px box; 13.0 buried its neighbour.

        On the driver frame chips 16 and 17 are 11.8px apart: at r=13 the
        lower chip covered ~80% of the upper one and neither number could be
        read. r=8.5 is the page's own 17px chip.
        """
        self.assertEqual(compose_strip.SVG_CHIP_R, 8.5)
        out, _svgs = self._emit()
        svg = self._read(out, 'profile-light.annotated.svg')
        chips = re.search(r'<g id="chips".*?</g>', svg, re.S).group(0)
        radii = {float(r) for r in re.findall(r'\sr="([\d.]+)"', chips)}
        self.assertEqual(radii, {8.5})

    def test_status_pill_uses_the_page_s_own_colour_constant(self):
        """`.s-shipped` is CHIP_COLOR; the SVG hard-coded #111."""
        out, _svgs = self._emit()
        svg = self._read(out, 'profile-light.annotated.svg')
        head = re.search(r'<g id="head".*?</g>', svg, re.S).group(0)
        pill = re.search(r'<rect[^>]*rx="11"[^>]*/>', head).group(0)
        self.assertIn(f'fill="{compose_strip.CHIP_COLOR}"', pill)
        self.assertNotIn('#111', pill, 'the pill was hard-coded near-black')
        page, _m, _n = self.compose({
            'title': 'T',
            'frames': [{'png': 'profile_light.png',
                        'rects': 'profile_light.json', 'caption': 'c',
                        'status': 'SHIPPED'}]})
        self.assertIn(f'.s-shipped{{color:#FFF;background:'
                      f'{compose_strip.CHIP_COLOR}}}', page,
                      'page and SVG must read the same constant')

    def test_font_family_is_a_resolvable_stack(self):
        """`sans` is not a CSS generic - the generic is `sans-serif`.

        Left as `sans` it resolves like an unknown family and falls through
        to the browser's standard font (measured 352.3px on a legend line
        that the resolved stack sets in 310.0px).
        """
        out, svgs = self._emit()
        for path in svgs:
            svg = self._read(out, os.path.basename(path))
            self.assertNotIn('font-family="sans"', svg)
            for family in re.findall(r'font-family="([^"]*)"', svg):
                self.assertTrue(family.endswith('sans-serif'),
                                f'{family!r} does not end in a CSS generic')
            self.assertIn(compose_strip.SVG_FONT_STACK, svg)
        self.assertNotIn('"', compose_strip.SVG_FONT_STACK,
                         'double quotes would break the XML attribute')

    def test_every_group_carries_an_id_for_design_app_layer_names(self):
        """Without ids Figma names the imported layers Group 1 / Group 2."""
        out, _svgs = self._emit()
        svg = self._read(out, 'profile-light.annotated.svg')
        classes = re.findall(r'<g id="([^"]+)" class="([^"]+)"', svg)
        self.assertEqual(dict(classes),
                         {'head': 'head', 'bezel': 'bezel',
                          'screen': 'screen', 'chips': 'chips',
                          'legend': 'legend'})
        self.assertEqual(svg.count('<g '), len(classes),
                         'every group is named, not just some')

    def test_the_phone_bezel_is_drawn_from_the_page_s_constants(self):
        """The page wraps every screen in a device bezel; the SVG drew a
        1px grey outline and called it a frame."""
        out, _svgs = self._emit()
        svg = self._read(out, 'profile-light.clean.svg')
        bezel = re.search(r'<g id="bezel".*?</g>', svg, re.S).group(0)
        self.assertIn(f'fill="{compose_strip.BEZEL_FILL}"', bezel)
        self.assertIn(f'stroke="{compose_strip.BEZEL_EDGE}"', bezel)
        self.assertIn(f'rx="{compose_strip.BEZEL_RADIUS:.1f}"', bezel)
        self.assertNotIn('#dcdcdc', svg, 'the placeholder outline is gone')
        # The screen is inset by the bezel padding, and the canvas grew to
        # fit the bezel instead of clipping it.
        pad = compose_strip.SVG_PAD + compose_strip.BEZEL_PAD
        self.assertIn(f'<image x="{pad:.1f}"', svg)
        self.assertIn(f'rx="{compose_strip.SCREEN_RADIUS:.1f}"', svg)
        width = float(re.search(r'viewBox="0 0 ([\d.]+)', svg).group(1))
        self.assertEqual(width, 390.0 + compose_strip.BEZEL_PAD * 2
                         + compose_strip.SVG_PAD * 2)

    def test_bezel_geometry_is_the_page_s_geometry(self):
        self.write_frame('profile_light', [_element(1, 'hdr', 'Header', 10)])
        page, _m, _n = self.compose({
            'title': 'T',
            'frames': [{'png': 'profile_light.png',
                        'rects': 'profile_light.json', 'caption': 'c'}]})
        self.assertIn(f'border-radius:{compose_strip.BEZEL_RADIUS:.0f}px',
                      page)
        self.assertIn(f'padding:{compose_strip.BEZEL_PAD:.0f}px', page)
        self.assertIn(f'border-radius:{compose_strip.SCREEN_RADIUS:.0f}px',
                      page)

    def test_two_frames_on_one_png_keep_distinct_names(self):
        self.write_frame('same', [_element(1, 'hdr', 'Header', 10)])
        out = os.path.join(self.dir, 'svg')
        _p, _m, _n, svgs = self.compose_full({
            'title': 'T',
            'frames': [
                {'png': 'same.png', 'rects': 'same.json', 'caption': 'before'},
                {'png': 'same.png', 'rects': 'same.json', 'caption': 'after'},
            ]}, emit_svg=out)
        names = sorted(os.path.basename(p) for p in svgs)
        self.assertEqual(len(set(names)), 4, f'names collided: {names}')


class ChipAlternationTests(ComposerTestCase):
    """Each number is carried by ONE frame, alternating in numbering order.

    A screen rendered light AND dark used to put every number on both frames,
    so 11 elements read as 22 points. The rule before this one - "the first
    frame owns every number, a later frame keeps only what measurably
    changed" - fixed the double-count but left the dark frame bare. The rule
    now: walk the numbers in order and hand them to the frames in turn, so
    light and dark each carry about half.
    """

    def _pair(self, elements_a, elements_b, **config_extra):
        self.write_frame('light', elements_a)
        self.write_frame('dark', elements_b)
        config = {
            'title': 'T',
            'frames': [
                {'png': 'light.png', 'rects': 'light.json', 'caption': 'light'},
                {'png': 'dark.png', 'rects': 'dark.json', 'caption': 'dark'},
            ]}
        config.update(config_extra)
        return self.compose(config)

    @staticmethod
    def _chips_per_frame(page):
        """The drawn (non-repeat) chip numbers, per frame, in page order."""
        return [re.findall(r'<i class="chip" [^>]*>(\d+)</i>', figure)
                for figure in page.split('<figure class="frame">')[1:]]

    def _four(self):
        elements = [_element(1, 'a', 'A', 0), _element(2, 'b', 'B', 100),
                    _element(3, 'c', 'C', 200), _element(4, 'd', 'D', 300)]
        return self._pair(elements, list(elements))

    def test_numbers_alternate_across_the_two_frames(self):
        """1 on light, 2 on dark, 3 on light, 4 on dark."""
        page, _mapping, _new = self._four()
        self.assertEqual(self._chips_per_frame(page),
                         [['1', '3'], ['2', '4']])

    def test_each_number_appears_exactly_once_with_the_toggle_off(self):
        page, mapping, _new = self._four()
        drawn = [n for frame in self._chips_per_frame(page) for n in frame]
        self.assertEqual(sorted(drawn, key=int),
                         [str(n) for n in sorted(mapping.values())])
        self.assertEqual(len(drawn), len(set(drawn)), 'a number was said twice')

    def test_neither_frame_is_left_bare(self):
        """The bug this replaced: the dark frame shipped with no chips."""
        page, _mapping, _new = self._four()
        for index, frame in enumerate(self._chips_per_frame(page)):
            self.assertTrue(frame, f'frame {index} carries no numbers at all')

    def test_the_split_is_even(self):
        page, _mapping, _new = self._four()
        light, dark = (len(f) for f in self._chips_per_frame(page))
        self.assertLessEqual(abs(light - dark), 1)

    def test_numbers_stay_global_not_renumbered_per_frame(self):
        """A number means the same element wherever it appears."""
        page, mapping, _new = self._four()
        self.assertEqual(mapping, {'a': 1, 'b': 2, 'c': 3, 'd': 4})
        # The hidden half is marked, not deleted, so the legend still reads.
        self.assertEqual(page.count('class="chip rep"'), 4)
        self.assertIn('class="lg rep"', page)

    def test_a_frame_specific_element_does_not_consume_a_turn(self):
        """It can only be drawn on the one frame it exists on, so it must
        not push the alternation of the shared numbers off balance."""
        shared = [_element(1, 'a', 'A', 0), _element(2, 'b', 'B', 100),
                  _element(3, 'c', 'C', 200)]
        page, mapping, _new = self._pair(
            shared + [{'number': 4, 'key': 'only_light', 'label': 'Only light',
                       'x': 16.0, 'y': 400.0, 'w': 358.0, 'h': 64.0}],
            list(shared))
        light, dark = self._chips_per_frame(page)
        self.assertEqual(mapping['only_light'], 4)
        # 1 and 3 to light, 2 to dark - unchanged by the extra element - and
        # the light-only element drawn where it exists.
        self.assertEqual(sorted(light, key=int), ['1', '3', '4'])
        self.assertEqual(dark, ['2'])

    def test_an_element_on_one_frame_only_is_always_drawn_there(self):
        page, _mapping, _new = self._pair(
            [_element(1, 'a', 'A', 0)],
            [_element(1, 'a', 'A', 0),
             {'number': 2, 'key': 'only_dark', 'label': 'Only dark',
              'x': 16.0, 'y': 300.0, 'w': 358.0, 'h': 64.0}])
        _light, dark = self._chips_per_frame(page)
        self.assertIn('2', dark, 'a dark-only element must be chipped on dark')

    def test_the_page_alternates_but_the_svg_export_does_not(self):
        """The one difference that must NOT be "fixed" into agreement.

        The page's frames are read side by side, so a number is said once.
        An exported SVG is used ALONE, so it carries every element on the
        frame - otherwise a deck slide ships unlabelled widgets.
        """
        elements = [_element(1, 'a', 'A', 0), _element(2, 'b', 'B', 100)]
        self.write_frame('light', elements)
        self.write_frame('dark', list(elements))
        out = os.path.join(self.dir, 'svg')
        page, _mapping, _new, _svgs = self.compose_full({
            'title': 'T',
            'frames': [
                {'png': 'light.png', 'rects': 'light.json', 'caption': 'light'},
                {'png': 'dark.png', 'rects': 'dark.json', 'caption': 'dark'},
            ]}, emit_svg=out)

        # Page: one number each, alternating.
        self.assertEqual(self._chips_per_frame(page), [['1'], ['2']])

        # SVG: BOTH numbers on BOTH frames, and the same numbers.
        for name in ('light.annotated.svg', 'dark.annotated.svg'):
            with open(os.path.join(out, name), encoding='utf-8') as handle:
                svg = handle.read()
            chips = re.search(r'<g id="chips".*?</g>', svg, re.S).group(0)
            self.assertEqual(
                sorted(re.findall(r'>(\d+)</text>', chips), key=int),
                ['1', '2'], f'{name} must carry every element on the frame')

    def test_repeats_toggle_exists_and_reuses_the_chips_mechanism(self):
        page, _mapping, _new = self._four()
        self.assertIn('id="repeatsToggle"', page)
        self.assertIn("classList.toggle('repeats'", page)
        # Same shape as the chips toggle it sits beside.
        self.assertIn('id="chipsToggle"', page)
        self.assertIn("classList.toggle('present'", page)
        # And the CSS that makes the checkbox mean something.
        self.assertIn('.chip.rep', page)
        self.assertIn('.repeats .chip.rep', page)

    def test_repeats_default_true_shows_every_number_on_every_frame(self):
        page, _mapping, _new = self._four()
        self.write_frame('light2', [_element(1, 'a', 'A', 0)])
        self.write_frame('dark2', [_element(1, 'a', 'A', 0)])
        on, _mapping, _new = self.compose({
            'title': 'T', 'repeats_default': True,
            'frames': [
                {'png': 'light2.png', 'rects': 'light2.json', 'caption': 'l'},
                {'png': 'dark2.png', 'rects': 'dark2.json', 'caption': 'd'},
            ]})
        self.assertIn('class="wrap repeats"', on)
        self.assertIn('id="repeatsToggle" checked', on)
        # The alternation is the DEFAULT VIEW, not a hard restriction: the
        # hidden half is still in the markup for the toggle to reveal.
        self.assertEqual(page.count('class="chip rep"'), 4)

    def test_emit_numbering_still_round_trips(self):
        emit = os.path.join(self.dir, 'numbering.json')
        self.write_frame('light', [_element(1, 'hdr', 'Header', 10)])
        self.write_frame('dark', [_element(1, 'hdr', 'Header', 10)])
        self.compose({
            'title': 'T',
            'frames': [
                {'png': 'light.png', 'rects': 'light.json', 'caption': 'l'},
                {'png': 'dark.png', 'rects': 'dark.json', 'caption': 'd'},
            ]}, emit=emit)
        with open(emit, encoding='utf-8') as handle:
            written = json.load(handle)
        self.assertEqual(written, {'map': {'hdr': 1}, 'retired': {}})

    def test_a_sidecar_without_h_does_not_crash_the_page(self):
        """Older harnesses wrote fewer rect fields. A missing dimension must
        never take the whole page down."""
        old_shape = {'key': 'hdr', 'label': 'Header', 'x': 16.0, 'y': 10.0,
                     'w': 358.0}
        self.write_frame('a', [old_shape], png=_png_grid(64, 64, (20, 20, 20)))
        self.write_frame('b', [old_shape], png=_png_grid(64, 64, (20, 20, 20)))
        page, mapping, _new = self.compose({
            'title': 'T',
            'frames': [
                {'png': 'a.png', 'rects': 'a.json', 'caption': 'A'},
                {'png': 'b.png', 'rects': 'b.json', 'caption': 'B'},
            ]})
        self.assertEqual(mapping, {'hdr': 1})
        self.assertEqual(page.count('class="chip"'), 1)
        self.assertEqual(page.count('class="chip rep"'), 1)

    def test_a_single_frame_page_carries_every_number(self):
        """Nothing to alternate with, so the one frame keeps the whole set."""
        self.write_frame('a', [_element(1, 'hdr', 'Header', 10)],
                         png=_png_grid(64, 64, (20, 20, 20)))
        page, _mapping, _new = self.compose({
            'title': 'T',
            'frames': [{'png': 'a.png', 'rects': 'a.json', 'caption': 'A'}]})
        self.assertEqual(page.count('class="chip"'), 1)
        self.assertNotIn('class="chip rep"', page)
        # The CSS rule always ships; the per-frame explainer must not.
        self.assertNotIn('<div class="frame-diff">', page)

    def test_alternation_never_reads_a_pixel(self):
        """It is decided from the numbering and the rects alone.

        The 1x1 fixture carries no measurable content at all; the split is
        still correct, because nothing about it depends on the render."""
        self.write_frame('a', [_element(1, 'hdr', 'Header', 10)])
        self.write_frame('b', [_element(1, 'hdr', 'Header', 10)])
        page, _mapping, _new = self.compose({
            'title': 'T',
            'frames': [
                {'png': 'a.png', 'rects': 'a.json', 'caption': 'A'},
                {'png': 'b.png', 'rects': 'b.json', 'caption': 'B'},
            ]})
        self.assertEqual(page.count('class="chip"'), 1)
        self.assertEqual(page.count('class="chip rep"'), 1)


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

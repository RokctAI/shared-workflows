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


"""Tests for the README's render-strip block (scripts/tour/readme_sections.py).

The tour renders the review strip BEFORE its emulator legs and commits the
composed page inside the tour output directory, so the README's generated
sections have to point at it - but only where it exists. The properties that
matter:

1. No page, no block. Most of the fleet has no ``test/render`` harness, and
   a repo without one must not grow an empty section or a dead link.
2. Page present, exactly one block, linking the committed relative path.
3. The block follows the gallery when there is one, and still lands
   sensibly when there is not.
4. Re-running is a no-op (the tour runs this on every push to main).
5. Every generated line stays inside 80 columns, so default markdownlint
   MD013 passes - the module enforces this by raising, and a link long
   enough to blow the limit would take the whole tour commit down with it.

Run:  python3 scripts/tests/test_tour_readme_render_strip.py
      python3 -m unittest discover -s scripts/tests    (also works)
"""

import base64
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tour')
)

import readme_sections  # noqa: E402

PNG_1X1 = base64.b64decode(
    b'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAE'
    b'hQGAhKmMIQAAAABJRU5ErkJggg=='
)

README = "# Demo App\n\nA shell.\n\n## Getting started\n\nRun it.\n"


class RenderStripBlock(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "README.md").write_text(README, encoding="utf-8")
        self.addCleanup(self._tmp.cleanup)

    # -- helpers ---------------------------------------------------------

    def add_stills(self):
        store = self.root / "marketing" / "tour" / "store"
        store.mkdir(parents=True, exist_ok=True)
        for name in ("01-welcome.png", "02-orders.png"):
            (store / name).write_bytes(PNG_1X1)

    def add_strip(self):
        page = self.root / readme_sections.RENDER_STRIP
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text("<!doctype html><title>strip</title>", encoding="utf-8")

    def run_sections(self):
        readme_sections.main(["--repo-root", str(self.root)])
        return (self.root / "README.md").read_text(encoding="utf-8")

    # -- tests -----------------------------------------------------------

    def test_no_page_no_block(self):
        """A repo with no render harness must not grow a block at all."""
        self.add_stills()
        out = self.run_sections()
        self.assertNotIn(readme_sections.RENDER_START, out)
        self.assertNotIn(readme_sections.RENDER_END, out)
        self.assertNotIn("render-strip", out)

    def test_builder_returns_none_when_absent(self):
        self.assertIsNone(readme_sections.build_render_strip_block(self.root))

    def test_page_present_links_the_committed_path(self):
        self.add_stills()
        self.add_strip()
        out = self.run_sections()
        self.assertEqual(out.count(readme_sections.RENDER_START), 1)
        self.assertEqual(out.count(readme_sections.RENDER_END), 1)
        self.assertIn(
            "(%s)" % readme_sections.RENDER_STRIP.as_posix(), out
        )
        # Relative, in-repo link - never an absolute or external URL.
        self.assertNotIn("https://", out.split(readme_sections.RENDER_START)[1]
                         .split(readme_sections.RENDER_END)[0])

    def test_block_follows_the_gallery(self):
        self.add_stills()
        self.add_strip()
        out = self.run_sections()
        self.assertLess(
            out.index(readme_sections.GALLERY_END),
            out.index(readme_sections.RENDER_START),
        )

    def test_block_lands_without_a_gallery(self):
        self.add_strip()
        out = self.run_sections()
        self.assertNotIn(readme_sections.GALLERY_START, out)
        self.assertIn(readme_sections.RENDER_START, out)
        # The original README survives around it.
        self.assertIn("## Getting started", out)
        self.assertTrue(out.startswith("# Demo App"))

    def test_rerun_is_a_no_op(self):
        self.add_stills()
        self.add_strip()
        first = self.run_sections()
        self.assertEqual(first, self.run_sections())

    def test_generated_lines_fit_eighty_columns(self):
        self.add_strip()
        block = readme_sections.build_render_strip_block(self.root)
        self.assertIsNotNone(block)
        for line in block:
            self.assertLessEqual(
                len(line), readme_sections.WIDTH,
                "markdownlint MD013 would reject: %r" % line,
            )


if __name__ == '__main__':
    unittest.main(verbosity=2)

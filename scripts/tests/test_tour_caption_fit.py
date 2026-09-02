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


"""Tests for the caption fit guard (scripts/tour/assemble.py).

A store still is composed by drawing the caption block into a FIXED box and
then pasting the phone card on top of it, so a caption the box cannot hold is
never reflowed - it is silently clipped. Two ways out of the box, and the Play
listing shipped one of each before this guard existed:

1. Too many rows - the block is taller than the gap between the canvas edge and
   the phone, so `top` clamps to CAPTION_MIN_EDGE and the last rows render
   underneath the phone frame. paas_manager's pos_checkout still lost its
   closing line this way.
2. A row too long - wrap_tokens admits an over-wide token when it is alone on
   its line, and a highlight phrase never splits, so an over-long phrase runs
   past the wrap width and off the canvas. paas_manager's menu still lost the
   last letter of its highlight this way.

These tests pin both detections, pin that a caption which fits stays silent,
and pin that the wide reel's much narrower caption column warns rather than
fails (an overrun there crowds the phone instead of losing characters off a
canvas edge 1920px away).

Run:  python scripts/tests/test_tour_caption_fit.py
      python -m unittest discover -s scripts/tests    (also works)
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "scripts", "tour"))

try:
    from PIL import Image, ImageDraw  # noqa: F401
except ImportError:  # pragma: no cover - CI installs Pillow for the tour stage
    Image = None

import assemble  # noqa: E402

# The phone leg's bottom-anchored beat: the caption hangs above a phone whose
# bezel top rests here. Derived the same way build_beat does, from the 1080x1920
# emulator still, so the numbers below are the real published geometry.
PHONE_EDGE = 715

# Captions exactly as they shipped, with the highlight already split out the
# way merge_fragments.extract_highlight leaves them.
TOO_MANY_ROWS = (
    "Take cash or a pay-link QR the customer scans on their own phone; if the "
    "till drops offline they still pay the link and a 6-digit code confirms it "
    "at the counter - the sale syncs itself later."
)
ROW_TOO_LONG = (
    "Your whole menu in one place - products, add-ons and extras, each on its "
    "own tab, priced and stocked."
)
FITS = (
    "New, accepted, ready, on the way - every order moves through one queue the "
    "moment it lands."
)


@unittest.skipIf(Image is None, "Pillow is not installed")
class CaptionFitTest(unittest.TestCase):
    def setUp(self):
        self.failures = []
        self.warnings = []
        self._fail = assemble.fail
        self._warn = assemble.warn
        assemble.fail = self.failures.append
        assemble.warn = self.warnings.append
        assemble.apply_device_preset("phone")

    def tearDown(self):
        assemble.fail = self._fail
        assemble.warn = self._warn

    def still(self, text, highlight):
        return assemble.caption_overlay(
            text,
            highlight=highlight,
            position="top",
            phone_edge=PHONE_EDGE,
            step_key="a_step",
        )

    def test_caption_that_fits_is_silent(self):
        self.still(FITS, "every order")
        self.assertEqual(self.failures, [])

    def test_too_many_rows_fails_with_the_row_budget(self):
        self.still(TOO_MANY_ROWS, "a 6-digit code")
        self.assertEqual(len(self.failures), 1, self.failures)
        message = self.failures[0]
        self.assertIn("a_step", message)
        self.assertIn("8 rows", message)
        # The budget is what an author has to write back inside, so it has to
        # be in the message rather than left to be rediscovered.
        self.assertIn("it holds 7", message)

    def test_row_too_long_names_the_highlight_phrase(self):
        self.still(ROW_TOO_LONG, "products, add-ons and extras")
        self.assertEqual(len(self.failures), 1, self.failures)
        message = self.failures[0]
        self.assertIn("products, add-ons and extras", message)
        self.assertIn("off the canvas edge", message)

    def test_a_row_that_only_breaks_the_margin_says_so(self):
        # Wide enough to leave the 72px text margin, narrow enough to stay on
        # the canvas: the render keeps every character but looks flush-right.
        self.still("Musina FM - Can you handle the Heat? - opens straight onto "
                   "the record player.", "Can you handle the Heat?")
        self.assertEqual(len(self.failures), 1, self.failures)
        self.assertIn("into the caption margin", self.failures[0])
        self.assertNotIn("off the canvas edge", self.failures[0])

    def test_wide_reel_warns_instead_of_failing(self):
        assemble.caption_column(
            "Driver puts your whole delivery day in one app - sign in to get "
            "started.",
            highlight="your whole delivery day",
            step_key="welcome",
        )
        self.assertEqual(self.failures, [])
        self.assertEqual(len(self.warnings), 1, self.warnings)
        self.assertIn("wide reel", self.warnings[0])


if __name__ == "__main__":
    unittest.main()

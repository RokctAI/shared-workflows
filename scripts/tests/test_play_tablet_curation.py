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

"""Tests for the tablet listing's pick-list (scripts/play/upload_listing_assets.py).

marketing/store/screenshots.txt curates which stills reach the Play listing.
Until this change it curated the PHONE leg only, so RokctAI/paas_manager#106
could keep a misleading still off phoneScreenshots for good but could only
DELETE the tablet copy by hand - and assemble.py's write_store_stills wipes and
rewrites marketing/tour/tablet/store/ on every tour run, which puts the deleted
still straight back onto a public listing.

These tests pin the three states the pick-list can be in, for the tablet leg:

1. Absent      - first-8-by-filename, exactly as before (fleet-wide default).
2. Comment-only - same fallback; a seeded placeholder curates nothing.
3. Curated     - the listed order IS the upload order, and an unlisted still
                 is genuinely dropped rather than merely reordered.

Plus the two properties that make ONE list serve BOTH legs: the phone leg's
behaviour is untouched, and a key written for one leg's numbering still matches
the other leg's when a dropped step renumbered it.

Run:  python3 scripts/tests/test_play_tablet_curation.py
      python3 -m unittest discover -s scripts/tests    (also works)
"""

import importlib.util
import os
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UPLOADER = os.path.join(REPO_ROOT, "scripts", "play", "upload_listing_assets.py")

_spec = importlib.util.spec_from_file_location("upload_listing_assets", UPLOADER)
uploader = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(uploader)


def write_png(path, size=(1600, 2560)):
    """A real (tiny-but-valid) portrait PNG at `size`, so image_size() reads it."""
    from PIL import Image

    Image.new("RGB", size, (10, 12, 20)).save(path, format="PNG")


class TabletPickList(unittest.TestCase):
    def setUp(self):
        self.app_dir = tempfile.mkdtemp(prefix="app_")
        self.phone_dir = os.path.join(self.app_dir, uploader.STORE_DIR)
        self.tablet_dir = os.path.join(self.app_dir, uploader.TABLET_STORE_DIR)
        os.makedirs(self.phone_dir)
        os.makedirs(self.tablet_dir)
        os.makedirs(os.path.join(self.app_dir, "marketing", "store"))
        self.steps = ["01-welcome", "02-signin", "03-orders", "04-profile"]
        for key in self.steps:
            write_png(os.path.join(self.phone_dir, key + ".png"), (1080, 1920))
            write_png(os.path.join(self.tablet_dir, key + ".png"), (1600, 2560))

    def picklist(self, text):
        path = os.path.join(self.app_dir, uploader.SCREENSHOTS_FILE)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def names(self, paths):
        return [os.path.basename(p) for p in paths]

    def tablet(self):
        return uploader.discover_tablet_screenshots(
            self.tablet_dir, uploader.read_curated_keys(self.app_dir)
        )

    def phone(self):
        return uploader.discover_images(
            self.phone_dir, uploader.read_curated_keys(self.app_dir)
        ).get("phoneScreenshots", [])

    # -- state 1: no pick-list -------------------------------------------------
    def test_absent_file_keeps_filename_order(self):
        self.assertIsNone(uploader.read_curated_keys(self.app_dir))
        self.assertEqual(self.names(self.tablet()), [k + ".png" for k in self.steps])

    def test_absent_file_still_caps_at_eight(self):
        for extra in range(5, 12):
            write_png(os.path.join(self.tablet_dir, f"{extra:02d}-more.png"))
        self.assertEqual(len(self.tablet()), uploader.PHONE_MAX_COUNT)

    # -- state 2: comment-only pick-list ---------------------------------------
    def test_comment_only_file_keeps_filename_order(self):
        self.picklist("# pick the stills for the listing\n\n#   02-signin\n")
        self.assertIsNone(uploader.read_curated_keys(self.app_dir))
        self.assertEqual(self.names(self.tablet()), [k + ".png" for k in self.steps])

    # -- state 3: a real pick-list ---------------------------------------------
    def test_picklist_orders_and_drops_tablet_stills(self):
        self.picklist("# curated\n03-orders\n01-welcome.png\n")
        self.assertEqual(self.names(self.tablet()), ["03-orders.png", "01-welcome.png"])

    def test_unlisted_still_stays_off_the_tablet_listing(self):
        # The paas_manager#106 case: the misleading still is simply not listed,
        # so the next tour run rewriting the directory cannot bring it back.
        self.picklist("01-welcome\n03-orders\n04-profile\n")
        self.assertNotIn("02-signin.png", self.names(self.tablet()))

    def test_unmatched_key_is_skipped_not_fatal(self):
        self.picklist("99-does-not-exist\n02-signin\n")
        self.assertEqual(self.names(self.tablet()), ["02-signin.png"])

    def test_picklist_matching_nothing_falls_back(self):
        self.picklist("99-nope\n98-also-nope\n")
        self.assertEqual(self.names(self.tablet()), [k + ".png" for k in self.steps])

    # -- one list, both legs ---------------------------------------------------
    def test_phone_leg_sees_the_same_curated_order(self):
        self.picklist("03-orders\n01-welcome\n")
        self.assertEqual(self.names(self.phone()), ["03-orders.png", "01-welcome.png"])
        self.assertEqual(self.names(self.phone()), self.names(self.tablet()))

    def test_key_still_matches_when_a_leg_renumbered(self):
        # The tablet leg dropped 02-signin, so everything after it shifted down
        # by one. A phone-numbered key must still find the tablet's still.
        os.remove(os.path.join(self.tablet_dir, "02-signin.png"))
        os.rename(
            os.path.join(self.tablet_dir, "03-orders.png"),
            os.path.join(self.tablet_dir, "02-orders.png"),
        )
        os.rename(
            os.path.join(self.tablet_dir, "04-profile.png"),
            os.path.join(self.tablet_dir, "03-profile.png"),
        )
        self.picklist("03-orders\n04-profile\n")
        self.assertEqual(self.names(self.tablet()), ["02-orders.png", "03-profile.png"])
        self.assertEqual(self.names(self.phone()), ["03-orders.png", "04-profile.png"])

    def test_exact_filename_beats_the_numberless_alias(self):
        # Two stills share a step key across numbering; the exact key wins.
        write_png(os.path.join(self.tablet_dir, "05-orders.png"))
        self.picklist("05-orders\n")
        self.assertEqual(self.names(self.tablet()), ["05-orders.png"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

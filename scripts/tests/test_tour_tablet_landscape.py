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

"""Tests for the tablet leg's LANDSCAPE capture and canvas.

Ray's ruling: a tablet is held on its long edge, so the tablet leg captures
2560x1600 and the store stills are laid out on that landscape canvas. Three
things have to hold together for that to be true end to end, and each is
easy to half-revert:

1. Both emulator legs (the tablet attempt and its retry) actually boot
   landscape - the first through `wm size`, the retry through its AVD's own
   config.ini - and both stay past the 840dp multi-pane breakpoint.
2. assemble.py's `tablet` preset is a landscape canvas inside Play's
   screenshot rules, and its bottom crop still swallows the launcher taskbar
   the emulator burns into every capture.
3. The phone preset is untouched: applying it changes no constant, which is
   what keeps every phone still byte-identical.

Run:  python3 scripts/tests/test_tour_tablet_landscape.py
      python3 -m unittest discover -s scripts/tests    (also works)
"""

import importlib.util
import os
import re
import sys
import unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
WORKFLOW = os.path.join(REPO, ".github", "workflows", "universal-guided-tour.yml")
ASSEMBLE = os.path.join(REPO, "scripts", "tour", "assemble.py")
UPLOADER = os.path.join(REPO, "scripts", "play", "upload_listing_assets.py")

# Play's screenshot rules, the ones the tablet canvas has to satisfy.
PLAY_MIN_PX, PLAY_MAX_PX = 320, 3840
PLAY_MAX_SIDE_RATIO = 2.0
# The launcher taskbar the tablet emulator burns into the bottom of every
# capture: ~73dp, which is ~110px at the first leg's density 240 and ~147px
# at the retry's 320. The crop has to hide the larger of the two.
TASKBAR_DP = 73.0
EXPANDED_DP = 840  # PlaneHost.planeCountFor's three-plane breakpoint


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def workflow():
    with open(WORKFLOW, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def tablet_legs():
    steps = workflow()["jobs"]["tour"]["steps"]
    return {
        s["name"]: s
        for s in steps
        if "reactivecircus/android-emulator-runner" in s.get("uses", "")
        and "Tablet" in s["name"]
    }


class TabletLegGeometry(unittest.TestCase):
    """The emulator legs: landscape pixels, multi-pane dp."""

    def setUp(self):
        self.legs = tablet_legs()
        self.assertEqual(
            sorted(self.legs),
            ["Run Emulator and Tour (Tablet Retry)", "Run Emulator and Tour (Tablet)"],
            "the tablet legs were renamed - this test can no longer see them",
        )

    def test_first_attempt_forces_a_landscape_canvas(self):
        env = self.legs["Run Emulator and Tour (Tablet)"]["env"]
        width, height = (int(v) for v in env["TOUR_WM_SIZE"].split("x"))
        self.assertGreater(
            width, height,
            "the tablet leg's wm size is not landscape - a tablet is held on "
            "its long edge, and the base display size is what decides which "
            "orientation rotation 0 means",
        )
        self.assertEqual((width, height), (2560, 1600))

    def test_retry_boots_landscape_from_its_own_avd_config(self):
        leg = self.legs["Run Emulator and Tour (Tablet Retry)"]
        cfg = leg["with"]["pre-emulator-launch-script"]
        self.assertIn("hw.lcd.width=2560", cfg)
        self.assertIn("hw.lcd.height=1600", cfg)
        self.assertIn("hw.initialOrientation=landscape", cfg)
        self.assertIn("skin.name=2560x1600", cfg)
        self.assertEqual(
            leg["env"]["TOUR_SKIP_DISPLAY_OVERRIDE"], "1",
            "the retry's whole point is booting its geometry natively",
        )

    def test_both_legs_stay_past_the_multi_pane_breakpoint(self):
        for name, leg in self.legs.items():
            width, _ = (int(v) for v in leg["env"]["TOUR_WM_SIZE"].split("x"))
            density = int(leg["env"]["TOUR_WM_DENSITY"])
            dp = width / (density / 160.0)
            self.assertGreaterEqual(
                dp, EXPANDED_DP,
                f"{name}: {width}px at density {density} is {dp:.0f}dp wide, "
                f"under the {EXPANDED_DP}dp breakpoint - the leg would ship a "
                "foldable/phone layout on a tablet listing",
            )

    def test_rotation_is_pinned_and_never_forced_to_portrait(self):
        run = [
            s for s in workflow()["jobs"]["tour"]["steps"]
            if s.get("name") == "Prepare Tour Script"
        ][0]["run"]
        self.assertIn("adb shell settings put system accelerometer_rotation 0", run)
        self.assertIn("adb shell settings put system user_rotation 0", run)
        self.assertNotIn(
            "user_rotation 1", run,
            "rotation stays at 0 (the display's natural orientation); the "
            "canvas comes from wm size, not from rotating a portrait panel",
        )


class TabletPreset(unittest.TestCase):
    """assemble.py's tablet preset: landscape, Play-legal, taskbar-free."""

    @classmethod
    def setUpClass(cls):
        cls.assemble = load(ASSEMBLE, "assemble_landscape_test")
        cls.preset = cls.assemble.DEVICE_PRESETS["tablet"]

    def test_the_canvas_is_landscape_and_matches_the_capture(self):
        self.assertEqual(
            (self.preset["WIDTH"], self.preset["HEIGHT"]), (2560, 1600),
            "the tablet canvas must be the shape the tablet leg captures",
        )

    def test_the_canvas_satisfies_plays_screenshot_rules(self):
        w, h = self.preset["WIDTH"], self.preset["HEIGHT"]
        for side in (w, h):
            self.assertGreaterEqual(side, PLAY_MIN_PX)
            self.assertLessEqual(side, PLAY_MAX_PX)
        self.assertLessEqual(
            max(w, h), PLAY_MAX_SIDE_RATIO * min(w, h),
            "Play rejects a screenshot whose longer side is more than twice "
            "the shorter",
        )

    def test_the_bottom_crop_hides_the_launcher_taskbar(self):
        """At rest, a bottom-anchored card must crop past the taskbar.

        The crop is a share of the CARD's height, so it has to be read back
        through the fit scale to say how much of the RAW capture it hides -
        which is the number the taskbar lives in.
        """
        a, preset = self.assemble, self.preset
        raw_w, raw_h = preset["WIDTH"], preset["HEIGHT"]
        scale = min(preset["FRAME_MAX_W"] / raw_w, preset["FRAME_MAX_H"] / raw_h)
        inner_h = round(raw_h * scale)
        card_h = inner_h + 2 * preset["FRAME_BEZEL"]
        crop = round(preset["CROP_FRACTION"] * card_h)
        raw_hidden = (crop - preset["FRAME_BEZEL"]) / scale
        worst_taskbar = TASKBAR_DP * (320 / 160.0)  # the retry's density
        self.assertGreater(
            raw_hidden, worst_taskbar,
            f"the crop hides {raw_hidden:.0f} raw px but the taskbar is "
            f"{worst_taskbar:.0f}px at density 320 - it would show in every still",
        )
        self.assertLess(
            raw_hidden, 0.25 * raw_h,
            "cropping more than a quarter of the screen throws away the "
            "content the still is meant to show",
        )
        self.assertGreater(a.CROP_FRACTION, 0)  # module default untouched so far

    def test_the_caption_zone_holds_a_four_line_caption(self):
        """The card rests low enough to leave the caption real room.

        A landscape card is much shorter than a portrait one, so the caption
        box above it is the thing a careless preset silently squeezes to
        nothing - and an overrun is a hard failure of the whole leg.
        """
        a, preset = self.assemble, self.preset
        raw_w, raw_h = preset["WIDTH"], preset["HEIGHT"]
        scale = min(preset["FRAME_MAX_W"] / raw_w, preset["FRAME_MAX_H"] / raw_h)
        card_h = round(raw_h * scale) + 2 * preset["FRAME_BEZEL"]
        crop = round(preset["CROP_FRACTION"] * card_h)
        y_rest = preset["HEIGHT"] + crop - a.FRAME_MARGIN - card_h
        caption_room = (y_rest + a.FRAME_MARGIN) - a.CAPTION_MIN_EDGE
        self.assertGreaterEqual(
            caption_room, 4 * preset["CAPTION_LINE_HEIGHT"],
            "fewer than four caption lines fit above the tablet card",
        )

    def test_the_caption_type_scales_with_the_wider_canvas(self):
        self.assertGreater(
            self.preset["CAPTION_FONT_SIZE"], self.assemble.CAPTION_FONT_SIZE,
            "64px type on a 2560px canvas reads smaller than it does on the "
            "phone's 1080px one - the tablet preset has to raise it",
        )

    def test_the_phone_preset_changes_nothing(self):
        self.assertEqual(
            self.assemble.DEVICE_PRESETS["phone"], {},
            "an empty phone preset is what keeps phone output byte-identical "
            "to runs that predate --device",
        )


class TabletListingUpload(unittest.TestCase):
    """The Play uploader takes the landscape stills the leg now writes."""

    @classmethod
    def setUpClass(cls):
        cls.uploader = load(UPLOADER, "upload_listing_assets_landscape_test")

    def png(self, tmp, name, size):
        from PIL import Image

        path = os.path.join(tmp, name)
        Image.new("RGB", size, (10, 12, 20)).save(path, format="PNG")
        return path

    def discovered(self, sizes):
        import tempfile

        tmp = tempfile.mkdtemp(prefix="tablet_store_")
        for i, size in enumerate(sizes):
            self.png(tmp, f"{i + 1:02d}-step.png", size)
        return [
            os.path.basename(p)
            for p in self.uploader.discover_tablet_screenshots(tmp, None)
        ]

    def test_landscape_tablet_stills_reach_the_listing(self):
        self.assertEqual(self.discovered([(2560, 1600)]), ["01-step.png"])

    def test_portrait_tablet_stills_still_reach_the_listing(self):
        self.assertEqual(self.discovered([(1600, 2560)]), ["01-step.png"])

    def test_an_out_of_ratio_still_is_skipped(self):
        # 2.5:1 - Play refuses a longer side more than twice the shorter.
        self.assertEqual(self.discovered([(3000, 1200)]), [])

    def test_an_out_of_bounds_still_is_skipped(self):
        self.assertEqual(self.discovered([(200, 160)]), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

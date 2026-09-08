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

"""Tests for the tablet legs' switch to gesture navigation.

Every landscape tablet still carried the launcher's 60dp taskbar along its
bottom edge. The pixel_tablet API 34 image boots in three-button navigation,
and on Android 14 that mode keeps the taskbar PINNED across every capture;
gesture navigation gives the transient taskbar, which stashes itself inside
apps. `cmd overlay enable-exclusive --category
com.android.internal.systemui.navbar.gestural` flips the mode without a
SystemUI restart (the launcher just rebuilds its taskbar), so run_tour.sh runs
it - gated on TOUR_GESTURE_NAV=1, which only the tablet legs set - right after
the rotation pin and before the app is installed.

The ordering is the part that is easy to break: the switch has to land before
`wm size`/`wm density` re-enter immersive mode, before the APK exists (so the
pre-tour ANR clear still covers a launcher hiccup), and before the
immersive-mode dialog is pre-confirmed (so a rebuilt taskbar cannot bring the
"swipe to reveal" bubble back). These tests read the REAL workflow the same way
test_tour_immersive_dialog.py does, cutting the run_tour.sh heredoc out of the
Prepare Tour Script step.

Run:  python3 scripts/tests/test_tour_tablet_gesture_nav.py
      python3 -m unittest discover -s scripts/tests    (also works)
"""

import os
import unittest

import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKFLOW = os.path.join(REPO_ROOT, ".github", "workflows", "universal-guided-tour.yml")

GESTURE_GATE = 'if [ "${TOUR_GESTURE_NAV:-}" = "1" ]; then'
GESTURE_OVERLAY = (
    "adb shell cmd overlay enable-exclusive "
    "--category com.android.internal.systemui.navbar.gestural"
)
ROTATION_LINE = "adb shell settings put system user_rotation 0 || true"
DENSITY_LINE = 'adb shell wm density "$WM_DENSITY" || true'
INSTALL_LINE = 'adb install -r "$TOUR_APK"'
IMMERSIVE_LINE = "adb shell settings put secure immersive_mode_confirmations confirmed || true"


def workflow():
    with open(WORKFLOW, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def steps_by_name(wf):
    return {s["name"]: s for s in wf["jobs"]["tour"]["steps"] if "name" in s}


def tour_script():
    """The body of run_tour.sh exactly as the Prepare Tour Script step writes it."""
    steps = steps_by_name(workflow())
    assert "Prepare Tour Script" in steps, (
        "no step named 'Prepare Tour Script' - it was renamed or removed, and "
        f"this test can no longer see the emulator setup. Steps: {sorted(steps)}"
    )
    lines = steps["Prepare Tour Script"]["run"].splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == "cat > run_tour.sh <<'SCRIPT'"]
    assert len(starts) == 1, f"expected exactly one run_tour.sh heredoc, found {len(starts)}"
    start = starts[0] + 1
    ends = [i for i in range(start, len(lines)) if lines[i].strip() == "SCRIPT"]
    assert ends, "run_tour.sh heredoc is never terminated"
    return [line.strip() for line in lines[start:ends[0]]]


def emulator_steps(wf):
    """Every step that hands a script to the android-emulator-runner action."""
    return [
        s
        for s in wf["jobs"]["tour"]["steps"]
        if "reactivecircus/android-emulator-runner" in s.get("uses", "")
    ]


def first_index(script, needle):
    hits = [i for i, line in enumerate(script) if needle in line]
    assert hits, f"expected a line containing {needle!r} in run_tour.sh"
    return hits[0]


class GestureNavigationSwitch(unittest.TestCase):
    """run_tour.sh: the overlay switch, gated and in the right place."""

    def setUp(self):
        self.script = tour_script()

    def test_the_overlay_switch_is_gated_on_tour_gesture_nav(self):
        script = self.script
        gate = first_index(script, GESTURE_GATE)
        overlay = first_index(script, GESTURE_OVERLAY)
        closes = [i for i in range(gate + 1, len(script)) if script[i] == "fi"]
        self.assertTrue(closes, "the TOUR_GESTURE_NAV block is never closed")
        self.assertLess(gate, overlay, "the overlay switch sits outside its gate")
        self.assertLess(
            overlay, closes[0],
            "the overlay switch runs unconditionally - the phone legs would "
            "switch navigation mode too",
        )
        self.assertEqual(
            len([line for line in script if GESTURE_OVERLAY in line]), 1,
            "the gestural overlay should be enabled exactly once",
        )

    def test_it_runs_after_the_rotation_pin_and_before_the_display_override(self):
        script = self.script
        overlay = first_index(script, GESTURE_OVERLAY)
        self.assertLess(
            first_index(script, ROTATION_LINE), overlay,
            "rotation is pinned first so the rebuilt taskbar lands on a fixed canvas",
        )
        self.assertLess(
            overlay, first_index(script, DENSITY_LINE),
            "the navigation mode has to be settled before wm size/density "
            "re-enter immersive mode",
        )

    def test_it_runs_before_the_app_is_installed(self):
        script = self.script
        self.assertLess(
            first_index(script, GESTURE_OVERLAY),
            first_index(script, INSTALL_LINE),
            "the switch must land while only the launcher exists, so the "
            "pre-tour ANR clear still covers it and no still captures the flip",
        )

    def test_the_immersive_dialog_is_confirmed_after_the_switch(self):
        script = self.script
        self.assertLess(
            first_index(script, GESTURE_OVERLAY),
            first_index(script, IMMERSIVE_LINE),
            "immersive_mode_confirmations must be set AFTER the taskbar is "
            "rebuilt, or the 'swipe to reveal' bubble can come back",
        )


class GestureNavigationLegs(unittest.TestCase):
    """Only the tablet legs opt in; the phone legs keep their navigation."""

    def setUp(self):
        legs = emulator_steps(workflow())
        self.tablet = {s["name"]: s for s in legs if "Tablet" in s["name"]}
        self.phone = {s["name"]: s for s in legs if "Tablet" not in s["name"]}
        self.assertEqual(
            sorted(self.tablet),
            ["Run Emulator and Tour (Tablet Retry)", "Run Emulator and Tour (Tablet)"],
            "the tablet legs were renamed - this test can no longer see them",
        )
        self.assertTrue(self.phone, "no phone emulator leg found")

    def test_both_tablet_legs_set_tour_gesture_nav_and_no_phone_leg_does(self):
        for name, leg in self.tablet.items():
            self.assertEqual(
                leg.get("env", {}).get("TOUR_GESTURE_NAV"), "1",
                f"{name} does not set TOUR_GESTURE_NAV=1 - its stills keep the "
                "pinned three-button taskbar",
            )
        for name, leg in self.phone.items():
            self.assertNotIn(
                "TOUR_GESTURE_NAV", leg.get("env", {}) or {},
                f"{name} sets TOUR_GESTURE_NAV - the phone legs must stay "
                "byte-identical to the historical captures",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)

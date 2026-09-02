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


"""Tests for the immersive-mode confirmation guard in the guided tour.

Captures take the WHOLE framebuffer (`adb exec-out screencap -p`), so any
system window sitting over the app is burned into the published still. Forcing
`wm size`/`wm density` puts the emulator into immersive mode, and the first
time an app goes full screen Android raises its own confirmation window -
"Viewing full screen / To exit, swipe down from the top / Got it" - which
logcat records as Window{... ImmersiveModeConfirmation}.

The ANR watcher cannot catch it and must not be stretched to: ANR_WINDOW_RE in
scripts/tour/capture_screenshots.py matches "Application Not Responding" /
"Application Error" windows, and this is neither an ANR nor a crash. It is
correctly ignored, and equally correctly ruins the still - a Play asset shipped
with the dialog burned over the app. The fix is to mark the dialog
pre-confirmed on the emulator so it never draws.

These tests read the REAL workflow: they load it with yaml.safe_load, pull the
named step's run body, bind its `${{ }}` expressions (an unbound one is a
failure, so a new expression cannot slip through unchecked), and cut out the
run_tour.sh heredoc that every leg executes. A renamed step fails the test
rather than silently skipping it.

Run:  python3 scripts/tests/test_tour_immersive_dialog.py
      python3 -m unittest discover -s scripts/tests    (also works)
"""

import os
import re
import unittest

import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKFLOW = os.path.join(REPO_ROOT, ".github", "workflows", "universal-guided-tour.yml")

EXPR = re.compile(r"\$\{\{\s*([A-Za-z0-9_.\-]+)\s*\}\}")

# The one line under test, byte for byte. `secure` (not `system`) is the right
# namespace for immersive_mode_confirmations, and `|| true` keeps it as
# failure-tolerant as the rotation/size/density lines it sits with - an API
# level that does not know the key must not take the tour down.
IMMERSIVE_LINE = "adb shell settings put secure immersive_mode_confirmations confirmed || true"

# Every leg hands the emulator runner this one script, which is why a single
# line in it covers phone, tablet and both retries.
TOUR_SCRIPT_INVOCATION = "bash ./run_tour.sh"


def workflow():
    with open(WORKFLOW, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def steps_by_name(wf):
    return {s["name"]: s for s in wf["jobs"]["tour"]["steps"] if "name" in s}


def bind(script, values):
    """Substitute the workflow's `${{ ... }}` expressions with real values."""

    def one(match):
        key = match.group(1)
        if key not in values:
            raise AssertionError(f"tour script uses an unbound expression: {key}")
        return values[key]

    return EXPR.sub(one, script)


def tour_script():
    """The body of run_tour.sh exactly as the Prepare Tour Script step writes it."""
    steps = steps_by_name(workflow())
    assert "Prepare Tour Script" in steps, (
        "no step named 'Prepare Tour Script' - it was renamed or removed, and "
        f"this test can no longer see the emulator setup. Steps: {sorted(steps)}"
    )
    run = bind(steps["Prepare Tour Script"]["run"], {})
    lines = run.splitlines()
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


class ImmersiveDialogTest(unittest.TestCase):
    def test_emulator_setup_preconfirms_the_immersive_dialog(self):
        self.assertIn(
            IMMERSIVE_LINE,
            tour_script(),
            "run_tour.sh does not pre-confirm the immersive-mode dialog, so "
            "Android's 'Viewing full screen' window can burn into the stills",
        )

    def test_it_is_set_with_the_other_display_settings(self):
        """It belongs with the rotation/size/density lines, not somewhere later."""
        script = tour_script()
        self.assertLess(
            script.index('adb shell wm density "$WM_DENSITY" || true'),
            script.index(IMMERSIVE_LINE),
            "the setting should follow the wm size/density lines that trigger "
            "immersive mode in the first place",
        )

    def test_it_is_applied_before_anything_can_go_full_screen(self):
        """Nothing is installed or driven until the dialog is already confirmed."""
        script = tour_script()
        where = script.index(IMMERSIVE_LINE)
        for later in ('adb install -r "$TOUR_APK"', "flutter test integration_test/guided_tour_test.dart"):
            hits = [i for i, line in enumerate(script) if later in line]
            self.assertTrue(hits, f"expected a line containing {later!r} in run_tour.sh")
            self.assertLess(
                where,
                hits[0],
                f"the immersive dialog must be pre-confirmed before {later!r} runs",
            )

    def test_every_leg_runs_the_script_that_carries_the_setting(self):
        """Phone, tablet and both retries: no leg gets its own unguarded setup."""
        legs = emulator_steps(workflow())
        self.assertEqual(
            [s["name"] for s in legs],
            [
                "Run Emulator and Tour",
                "Run Emulator and Tour (Retry)",
                "Run Emulator and Tour (Tablet)",
                "Run Emulator and Tour (Tablet Retry)",
            ],
            "the set of emulator legs changed - a new leg must run run_tour.sh "
            "too, or it captures the immersive dialog",
        )
        for leg in legs:
            self.assertEqual(
                leg["with"]["script"].strip(),
                TOUR_SCRIPT_INVOCATION,
                f"leg {leg['name']!r} does not run the shared tour script",
            )


if __name__ == "__main__":
    unittest.main()

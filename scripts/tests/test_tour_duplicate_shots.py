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


"""Tests for the duplicate-screenshot guard (scripts/tour/assemble.py).

The old guard, shots_all_identical, only noticed when EVERY captured still was
byte-identical, and its call site only warned - escalation to a failure sat
behind --require-varied, which universal-guided-tour.yml never passes. So the
common fault was invisible: a duplicated PAIR, two steps that captured the same
pixels because one of them never reached its own screen. supacharge's tour
published two identical stills under two different captions that way.

duplicate_shot_groups replaces it. It hashes every capture into an ordered map
keyed by digest and returns every group of two or more step keys, in step
order, and the call site fails on any group - naming both keys, so the step
that did not arrive is identifiable from the log alone. An all-identical run is
just the extreme case, and keeps its stronger "regressed to placeholder frames"
wording.

--require-varied is kept as an accepted no-op so existing callers keep working.

Run:  python3 scripts/tests/test_tour_duplicate_shots.py
      python3 -m unittest discover -s scripts/tests    (also works)
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
ASSEMBLE = os.path.join(REPO, "scripts", "tour", "assemble.py")
sys.path.insert(0, os.path.join(REPO, "scripts", "tour"))

import assemble  # noqa: E402

# Distinct byte strings standing in for captured PNGs. The guard hashes file
# CONTENT, so it neither knows nor cares that these are not real images.
PIXELS = {
    "welcome": b"welcome-pixels",
    "home": b"home-pixels",
    "orders": b"orders-pixels",
    "profile": b"profile-pixels",
}


class DuplicateShotGroupsTest(unittest.TestCase):
    """The detector itself."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="tour_shots_")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def shots(self, contents):
        """Write {key: bytes} to disk and return the {key: path} find_shots yields."""
        shots = {}
        for index, (key, blob) in enumerate(contents.items(), start=1):
            path = os.path.join(self.dir, f"{index:02d}-{key}.png")
            with open(path, "wb") as handle:
                handle.write(blob)
            shots[key] = path
        return shots

    def test_a_duplicated_pair_inside_a_larger_set_is_found(self):
        """The case the old all-identical check could never see."""
        groups = self.shots({
            "welcome": PIXELS["welcome"],
            "home": PIXELS["home"],
            # 'orders' never left the home screen, so it captured home again.
            "orders": PIXELS["home"],
            "profile": PIXELS["profile"],
        })
        self.assertEqual(assemble.duplicate_shot_groups(groups), [["home", "orders"]])

    def test_groups_come_back_in_step_order(self):
        """Two independent pairs, each listed in the order the steps run."""
        groups = self.shots({
            "welcome": PIXELS["welcome"],
            "home": PIXELS["home"],
            "orders": PIXELS["welcome"],
            "profile": PIXELS["home"],
        })
        self.assertEqual(
            assemble.duplicate_shot_groups(groups),
            [["welcome", "orders"], ["home", "profile"]],
        )

    def test_a_varied_run_has_no_groups(self):
        self.assertEqual(assemble.duplicate_shot_groups(self.shots(PIXELS)), [])

    def test_a_single_capture_is_not_a_duplicate_of_itself(self):
        self.assertEqual(
            assemble.duplicate_shot_groups(self.shots({"welcome": PIXELS["welcome"]})), []
        )

    def test_an_all_identical_run_is_one_group_of_everything(self):
        same = {key: b"placeholder-frame" for key in PIXELS}
        self.assertEqual(
            assemble.duplicate_shot_groups(self.shots(same)),
            [["welcome", "home", "orders", "profile"]],
        )


class AssembleRefusalTest(unittest.TestCase):
    """The call site: assemble.py's real exit code and message."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="tour_run_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.shots_dir = os.path.join(self.dir, "shots")
        os.makedirs(self.shots_dir)

    def run_assemble(self, contents, extra_args=()):
        keys = list(contents)
        for index, key in enumerate(keys, start=1):
            with open(os.path.join(self.shots_dir, f"{index:02d}-{key}.png"), "wb") as handle:
                handle.write(contents[key])
        resolved = os.path.join(self.dir, "tour.resolved.json")
        with open(resolved, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "app": {"name": "Demo", "tagline": "A demo", "slug": "demo"},
                    "steps": [
                        {"key": key, "title": key, "caption": f"{key} caption"}
                        for key in keys
                    ],
                },
                handle,
            )
        return subprocess.run(
            [sys.executable, ASSEMBLE,
             "--resolved", resolved,
             "--shots", self.shots_dir,
             "--out", os.path.join(self.dir, "out"),
             "--guide", *extra_args],
            capture_output=True, text=True, cwd=REPO,
        )

    def test_a_duplicated_pair_fails_and_names_both_keys(self):
        result = self.run_assemble({
            "welcome": PIXELS["welcome"],
            "home": PIXELS["home"],
            "orders": PIXELS["home"],
            "profile": PIXELS["profile"],
        })
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("duplicate screenshots", result.stdout)
        self.assertIn("home == orders", result.stdout)
        # Not the all-identical wording: only two of the four match.
        self.assertNotIn("regressed to placeholder frames", result.stdout)

    def test_an_all_identical_run_keeps_the_placeholder_wording(self):
        result = self.run_assemble({key: b"placeholder-frame" for key in PIXELS})
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("regressed to placeholder frames", result.stdout)
        self.assertIn("ALL 4 captured screenshots are byte-identical", result.stdout)

    def test_a_varied_run_is_not_refused(self):
        result = self.run_assemble(dict(PIXELS))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("duplicate screenshots", result.stdout)
        self.assertNotIn("byte-identical", result.stdout)
        # It went all the way through, so the guard is what let it past.
        self.assertIn("feature-guide.md", result.stdout)

    def test_require_varied_is_still_accepted_and_changes_nothing(self):
        """Kept as a no-op so existing invocations do not break."""
        contents = {
            "welcome": PIXELS["welcome"],
            "home": PIXELS["home"],
            "orders": PIXELS["home"],
            "profile": PIXELS["profile"],
        }
        without = self.run_assemble(contents)
        with_flag = self.run_assemble(contents, extra_args=("--require-varied",))
        self.assertEqual(with_flag.returncode, without.returncode)
        self.assertNotIn("unrecognized arguments", with_flag.stderr)
        self.assertIn("duplicate screenshots", with_flag.stdout)
        self.assertIn("home == orders", with_flag.stdout)


if __name__ == "__main__":
    unittest.main()

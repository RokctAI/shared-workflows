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

"""Tests for the deadline radar's deadline-day boundary.

A store deadline is in force ON the deadline date, not from the day after:
on 2026-08-31 a Play app still targeting API 35 can no longer ship updates.
The radar used to compare `today > base`, so on the deadline day itself it
reported a non-compliant repo as AT RISK and suppressed the "updates are
blocked" callout in the issue body - the day the warning matters most.

These tests pin the boundary on all three days around a deadline.

Run:  python3 scripts/tests/test_deadline_radar_boundary.py
      python3 -m unittest discover -s scripts/tests    (also works)
"""

import datetime as dt
import importlib.util
import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RADAR = os.path.join(REPO_ROOT, "scripts", "deadline-radar", "check_deadlines.py")

_spec = importlib.util.spec_from_file_location("check_deadlines", RADAR)
radar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(radar)

DEADLINE = {
    "id": "play-target-api-36",
    "title": "Google Play target API 36",
    "description": "Play requires updates to target API 36 from the deadline.",
    "deadline": "2026-08-31",
    "extension": "2026-11-01",
    "check": "target_sdk",
    "threshold": 36,
}

BASE = dt.date(2026, 8, 31)
DAY_BEFORE = BASE - dt.timedelta(days=1)
DAY_AFTER = BASE + dt.timedelta(days=1)


def fact(target_sdk):
    return {"display": "supacharge", "template": False, "target_sdk": target_sdk,
            "flutter_version": None, "readable": True}


class DeadlineDayCountsAsPassed(unittest.TestCase):

    def test_non_compliant_repo_across_the_boundary(self):
        self.assertEqual(radar.status_for(False, DEADLINE, DAY_BEFORE), "AT RISK")
        self.assertEqual(radar.status_for(False, DEADLINE, BASE), "BEHIND")
        self.assertEqual(radar.status_for(False, DEADLINE, DAY_AFTER), "BEHIND")

    def test_compliant_repo_stays_ok_across_the_boundary(self):
        for day in (DAY_BEFORE, BASE, DAY_AFTER):
            self.assertEqual(radar.status_for(True, DEADLINE, day), "OK")

    def test_unknown_repo_stays_unknown_across_the_boundary(self):
        for day in (DAY_BEFORE, BASE, DAY_AFTER):
            self.assertEqual(radar.status_for(None, DEADLINE, day), "UNKNOWN")

    def test_summary_counts_the_deadline_day_as_behind(self):
        result = radar.evaluate_deadline(DEADLINE, [fact(35)], BASE)
        self.assertEqual((result["behind"], result["at_risk"]), (1, 0))
        before = radar.evaluate_deadline(DEADLINE, [fact(35)], DAY_BEFORE)
        self.assertEqual((before["behind"], before["at_risk"]), (0, 1))

    def test_blocked_callout_appears_on_the_deadline_day(self):
        needle = "The base deadline has passed"
        for day, expected in ((DAY_BEFORE, False), (BASE, True), (DAY_AFTER, True)):
            result = radar.evaluate_deadline(DEADLINE, [fact(35)], day)
            body = radar.build_issue_body(DEADLINE, result, day)
            self.assertEqual(needle in body, expected, f"callout on {day}")

    def test_callout_stops_after_the_extension_date(self):
        extension = dt.date.fromisoformat(DEADLINE["extension"])
        result = radar.evaluate_deadline(DEADLINE, [fact(35)], extension)
        self.assertIn("The base deadline has passed", radar.build_issue_body(DEADLINE, result, extension))
        past = extension + dt.timedelta(days=1)
        result = radar.evaluate_deadline(DEADLINE, [fact(35)], past)
        self.assertNotIn("The base deadline has passed", radar.build_issue_body(DEADLINE, result, past))


if __name__ == "__main__":
    unittest.main(verbosity=2)

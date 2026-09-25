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

"""Tests for sdk_cmd_issue_sync.py: body rendering and the per-SDK
open/update/reopen/close decision (no network).

Run:  python scripts/tests/test_sdk_validator_cmd_issue_sync.py
"""

import os
import sys
import unittest

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS_DIR)

import sdk_cmd_issue_sync as sync  # noqa: E402

E = [{"cmd": "control:b", "file": "lib/b.dart"},
     {"cmd": "api.a", "file": "lib/a.dart"}]


def issue(n, sdk, state="open", pr=False):
    i = {"number": n, "state": state, "body": f"x\n{sync.marker(sdk)}\ny"}
    if pr:
        i["pull_request"] = {}
    return i


class RenderBody(unittest.TestCase):
    def test_marker_rows_and_links(self):
        b = sync.render_body("tender", E, "https://run/1", "RokctAI/tender")
        self.assertTrue(b.startswith("<!-- cmd-check:tender -->\n"))
        self.assertIn("**2** gateway cmd(s)", b)
        self.assertLess(b.index("`api.a`"), b.index("`control:b`"))
        self.assertIn("| `api.a` | `lib/a.dart` |", b)
        self.assertIn("https://run/1", b)
        self.assertIn("`RokctAI/tender`", b)

    def test_deterministic(self):
        self.assertEqual(sync.render_body("s", E), sync.render_body("s", list(reversed(E))))


class Plan(unittest.TestCase):
    def acts(self, report, issues):
        return [(a, s, n) for a, s, n, _ in sync.plan(report, issues)]

    def test_open_when_missing(self):
        self.assertEqual(self.acts({"s": E}, []), [("open", "s", None)])

    def test_update_open_issue(self):
        self.assertEqual(self.acts({"s": E}, [issue(7, "s")]), [("update", "s", 7)])

    def test_reopen_closed_instead_of_duplicate(self):
        self.assertEqual(self.acts({"s": E}, [issue(3, "s", "closed")]),
                         [("reopen", "s", 3)])

    def test_prefers_open_issue(self):
        self.assertEqual(self.acts({"s": E}, [issue(3, "s", "closed"), issue(9, "s")]),
                         [("update", "s", 9)])

    def test_close_at_zero(self):
        self.assertEqual(self.acts({"s": []}, [issue(7, "s")]), [("close", "s", 7)])

    def test_zero_without_open_issue_is_noop(self):
        self.assertEqual(self.acts({"s": []}, [issue(7, "s", "closed")]), [("noop", "s", None)])
        self.assertEqual(self.acts({"s": []}, []), [("noop", "s", None)])

    def test_marker_is_exact_per_sdk(self):
        # 'tender' must not match the issue of 'tender_extra' and vice versa.
        self.assertEqual(self.acts({"tender": E}, [issue(5, "tender_extra")]),
                         [("open", "tender", None)])

    def test_pull_requests_ignored(self):
        self.assertEqual(self.acts({"s": E}, [issue(4, "s", pr=True)]), [("open", "s", None)])

    def test_sdks_not_in_report_untouched(self):
        self.assertEqual(self.acts({}, [issue(7, "s")]), [])


class Main(unittest.TestCase):
    def test_missing_report_exits_zero(self):
        self.assertEqual(sync.main(["/nonexistent/report.json"]), 0)


if __name__ == "__main__":
    unittest.main()

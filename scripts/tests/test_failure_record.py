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

"""Tests for scripts/failure_record.py (structured consumer failure records).

Run:  python3 scripts/tests/test_failure_record.py
"""

import importlib.util
import json
import os
import tempfile
import unittest
from types import SimpleNamespace

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO_ROOT, "scripts", "failure_record.py")

_spec = importlib.util.spec_from_file_location("failure_record", SCRIPT)
fr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fr)


def opts(log, **kw):
    base = dict(
        log=log,
        stage="build",
        job=None,
        failure_class="build",
        screenshot_artifact=None,
        screenshot_file="verification.png",
    )
    base.update(kw)
    return SimpleNamespace(**base)


class FailureRecordTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.tmp)

    def tearDown(self):
        os.chdir(self.cwd)

    def log(self, text):
        path = os.path.join(self.tmp, "build_log.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def test_missing_log_leaves_fields_null(self):
        rec = fr.build_record(opts(None))
        self.assertIsNone(rec["cmd"])
        self.assertIsNone(rec["log_tail"])
        self.assertIsNone(rec["error_summary"])
        self.assertIsNone(rec["sdk"]["name"])
        self.assertEqual(rec["failure_class"], "build")

    def test_api_failure_sets_cmd_args_and_class(self):
        path = self.log(
            "starting\nGET /api/method/rokct.pos.get_items?limit=5&page=2\n"
            "DioException [bad response]: status code of 500\n"
        )
        rec = fr.build_record(
            opts(path, stage="emulator-verify", failure_class="runtime")
        )
        self.assertEqual(rec["cmd"], "rokct.pos.get_items")
        self.assertEqual(rec["args"], {"limit": "5", "page": "2"})
        self.assertEqual(rec["failure_class"], "api")

    def test_gateway_cmd_from_json_body(self):
        path = self.log(
            "POST https://x.rokct.ai/api/v1/method/rokct.platform.api\n"
            'data: {"cmd": "pos.get_items", "limit": 5}\n'
            "DioException [bad response]: status code of 417\n"
        )
        rec = fr.build_record(opts(path))
        self.assertEqual(rec["cmd"], "pos.get_items")
        self.assertEqual(rec["args"], {"limit": 5})
        self.assertEqual(rec["failure_class"], "api")

    def test_gateway_cmd_from_query_args(self):
        path = self.log(
            "POST /api/v1/method/rokct.platform.api?cmd=auth.login&device=x HTTP 500\n"
        )
        rec = fr.build_record(opts(path))
        self.assertEqual(rec["cmd"], "auth.login")
        self.assertEqual(rec["args"], {"device": "x"})

    def test_gateway_without_error_is_not_api(self):
        path = self.log(
            "POST /api/v1/method/rokct.platform.api\n"
            '{"cmd": "pos.get_items"}\nall good\n'
        )
        self.assertIsNone(fr.build_record(opts(path))["cmd"])

    def test_endpoint_without_error_is_not_api(self):
        path = self.log("calls /api/method/foo.bar fine\nError: compile failed\n")
        rec = fr.build_record(opts(path))
        self.assertIsNone(rec["cmd"])
        self.assertEqual(rec["failure_class"], "build")
        self.assertEqual(rec["error_summary"], "Error: compile failed")

    def test_infra_and_tail_length(self):
        lines = [f"line {i}" for i in range(500)] + ["Could not resolve host: pub.dev"]
        rec = fr.build_record(opts(self.log("\n".join(lines))))
        self.assertEqual(rec["failure_class"], "infra")
        self.assertEqual(len(rec["log_tail"].splitlines()), fr.LOG_TAIL_LINES)

    def test_screenshot_only_when_file_exists(self):
        rec = fr.build_record(opts(None, screenshot_artifact="verification-results"))
        self.assertIsNone(rec["screenshot_artifact"])
        open("verification.png", "wb").close()
        rec = fr.build_record(opts(None, screenshot_artifact="verification-results"))
        self.assertEqual(rec["screenshot_artifact"], "verification-results")

    def test_render_with_overlay_and_unknowns(self):
        rec = fr.build_record(opts(None))
        rec = fr.merge(
            rec,
            {
                "sdk": {
                    "name": "core",
                    "from_version": "abc",
                    "to_version": "def",
                    "x": None,
                }
            },
        )
        md = fr.render(rec)
        self.assertIn("## Failure record", md)
        self.assertIn("`abc -> def`", md)
        self.assertIn("| API cmd | _unknown_ |", md)

    def test_main_never_raises(self):
        self.assertEqual(
            fr.main(["render", "/nonexistent.json", "--overlay", "{bad"]), 0
        )
        self.assertEqual(fr.main(["bogus"]), 0)
        out = os.path.join(self.tmp, "rec.json")
        self.assertEqual(fr.main(["write", "--out", out, "--stage", "build"]), 0)
        with open(out, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["stage"], "build")


if __name__ == "__main__":
    unittest.main()

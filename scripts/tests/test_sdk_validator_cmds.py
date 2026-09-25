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

"""Tests for sdk_validator.py's gateway cmd check.

Every cmd a dart half POSTs to rokct.platform.api must be whitelisted by the
SAME SDK's frappe half (or a frappe SDK that half declares as a dependency).

Run:  python scripts/tests/test_sdk_validator_cmds.py
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS_DIR)

import sdk_validator  # noqa: E402


class FakeLogger:
    def __init__(self):
        self.lines = []

    def log(self, message, level="INFO", sdk_name=None):
        self.lines.append((level, message, sdk_name))


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def frappe_manifest(name, methods, deps=None):
    tenant = {"hooks": {"whitelisted_methods": {
        m: m.replace("{app_name}.", "{app_name}." + name + ".") for m in methods}}}
    if deps is not None:
        tenant["dependencies"] = deps
    return json.dumps({"name": name, "app_type": {"tenant": tenant}})


class ExtractDartCmdsTest(unittest.TestCase):
    def test_literals_interpolation_and_comments(self):
        src = """
        // 'api.commented.out' must not count
        /* 'api.block.comment' */
        class R {
          static const _cmd = 'api.blog';
          static const String cmd = 'tenant.api.log_frontend_error';
          static const controlCmd = 'control:track_event';
          f() => post({'cmd': 'api.user.login'});
          g() => post({'cmd': '$_cmd.get_blogs'});
          h() => post({'cmd': '${_cmd}.get_blog'});
          i(x) => post({'cmd': '$x.dynamic'});
          j() => print('not a cmd');
          k() => launch('https://x.test/api/v1');
        }
        """
        self.assertEqual(sdk_validator.extract_dart_cmds(src), {
            "api.user.login", "api.blog.get_blogs", "api.blog.get_blog",
            "tenant.api.log_frontend_error", "control:track_event",
        })


class ValidateGatewayCmdsTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="cmdcheck_"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def _sdk(self, module, dart_src, methods, deps=None, templates_src=None):
        mod = self.root / module
        write(mod / "dart" / "manifest.json",
              json.dumps({"name": module + "_sdk"}))
        write(mod / "dart" / "lib" / "src" / "repo.dart", dart_src)
        if templates_src:
            write(mod / "dart" / "templates" / "t.dart", templates_src)
        # test/ is never scanned
        write(mod / "dart" / "test" / "t_test.dart",
              "expect(c, 'api.only.in_tests');")
        if methods is not None:
            write(mod / "frappe" / "manifest.json",
                  frappe_manifest(module, methods, deps))

    def _run(self, sdk):
        _, sdk_data = sdk_validator.parse_manifests(
            sdk_validator.find_manifests(str(self.root)))
        flavor = sdk_validator.parse_flavor_manifests(
            sdk_validator.find_flavor_manifests(str(self.root)))
        by_root = {Path(i["root_dir"]).resolve(): i["manifest_path"]
                   for i in flavor.values() if i["flavor"] == "frappe"}
        by_name = {k[:-len(" (frappe)")]: i["manifest_path"]
                   for k, i in flavor.items() if i["flavor"] == "frappe"}
        logger = FakeLogger()
        missing = sdk_validator.validate_gateway_cmds(
            sdk, sdk_data[sdk], by_root, by_name, logger)
        return missing, logger

    def test_all_resolved_in_own_frappe_half(self):
        self._sdk("shop", "p({'cmd': 'api.shop.get'}); q('control:ping');",
                  ["{app_name}.api.shop.get", "control:ping"])
        missing, logger = self._run("shop_sdk")
        self.assertEqual(missing, 0)
        self.assertFalse([l for l in logger.lines if l[0] == "WARNING"])

    def test_cmd_only_in_other_sdk_is_flagged(self):
        self._sdk("base", "x", ["{app_name}.api.system.get_settings"])
        self._sdk("shop", "p({'cmd': 'api.system.get_settings'});",
                  ["{app_name}.api.shop.get"],
                  templates_src="p({'cmd': 'api.shop.missing'});")
        missing, logger = self._run("shop_sdk")
        self.assertEqual(missing, 2)
        msgs = " ".join(l[1] for l in logger.lines)
        self.assertIn("'api.system.get_settings'", msgs)
        self.assertIn("'api.shop.missing'", msgs)
        self.assertIn("templates/t.dart", msgs)
        self.assertNotIn("api.only.in_tests", msgs)

    def test_declared_dependency_resolves(self):
        self._sdk("base", "x", ["{app_name}.api.system.get_settings"])
        self._sdk("shop", "p({'cmd': 'api.system.get_settings'});",
                  ["{app_name}.api.shop.get"], deps=["requests", "base"])
        missing, _ = self._run("shop_sdk")
        self.assertEqual(missing, 0)

    def test_no_frappe_half_is_skipped(self):
        self._sdk("dartonly", "p({'cmd': 'api.x.y'});", None)
        self._sdk("other", "x", [])
        missing, logger = self._run("dartonly_sdk")
        self.assertIsNone(missing)
        self.assertFalse(logger.lines)

    def test_cmd_report_json(self):
        self._sdk("base", "p({'cmd': 'api.base.ok'});", ["{app_name}.api.base.ok"])
        self._sdk("shop", "p({'cmd': 'api.system.get_settings'});",
                  ["{app_name}.api.shop.get"])
        self._sdk("dartonly", "p({'cmd': 'api.x.y'});", None)
        out = self.root / "report.json"
        argv, cwd = sys.argv, os.getcwd()
        os.chdir(self.root)
        try:
            sys.argv = ["sdk_validator.py", "--root", str(self.root),
                        "--cmd-report", str(out)]
            sdk_validator.main()
        finally:
            sys.argv = argv
            os.chdir(cwd)
        report = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(report, {
            "base_sdk": [],
            "shop_sdk": [{"cmd": "api.system.get_settings",
                          "file": "lib/src/repo.dart"}],
        })


if __name__ == "__main__":
    unittest.main()

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

"""Tests for sdk_validator.py's raw Frappe path and hardcoded UI string checks.

Run:  python scripts/tests/test_sdk_validator_raw_paths_ui_strings.py
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS_DIR)

import sdk_validator as v  # noqa: E402


class RawPathTests(unittest.TestCase):
    def test_flags_method_and_resource(self):
        text = ("final a = '/api/method/frappe.auth.get_logged_user';\n"
                "final b = '/api/v1/method/foo.bar';\n"
                "fetch(`/api/resource/Item/${id}`);\n")
        self.assertEqual([n for n, _ in v.find_raw_paths(text)], [1, 2, 3])

    def test_gateway_constant_is_not_flagged(self):
        text = ("const gw = '/api/v1/method/rokct.platform.api';\n"
                "const gw2 = \"/api/method/rokct.platform.api\";\n")
        self.assertEqual(v.find_raw_paths(text), [])

    def test_bypass_comment_allowlists(self):
        text = ("post('/api/method/upload_file'); "
                "// bypasses gateway: multipart upload\n"
                "post('/api/method/login'); // bypasses gateway:\n")
        self.assertEqual([n for n, _ in v.find_raw_paths(text)], [2])


    def test_comment_lines_skipped(self):
        text = ("/// clients never build `/api/method/...` urls\n"
                "  * see /api/resource/Item\n")
        self.assertEqual(v.find_raw_paths(text), [])


class UiStringTests(unittest.TestCase):
    def test_flags_literals(self):
        text = ("Text('Hello world'),\n"
                "const Text(\"Save\"),\n"
                "Text(AppHelpers.getTranslation(TrKeys.save)),\n")
        self.assertEqual(v.find_hardcoded_ui_strings(text),
                         [(1, 'Hello world'), (2, 'Save')])

    def test_non_copy_literals_skipped(self):
        text = "Text(''),\nText('$count'),\nText('${a.b} / 5'),\n"
        self.assertEqual(v.find_hardcoded_ui_strings(text), [])

    def test_ignore_comment_and_commented_code(self):
        text = ("Text('v1.2'), // i18n-ignore: version label\n"
                "// Text('old'),\n"
                "Text('x'), // i18n-ignore:\n")
        self.assertEqual(v.find_hardcoded_ui_strings(text), [(3, 'x')])


class CollectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _write(self, rel, text):
        p = self.tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf-8')

    def test_per_file_counts_skip_tests_generated_examples(self):
        bad = "Text('Hi'); Text('There');\nfinal u = '/api/resource/X';\n"
        self._write('lib/a.dart', bad)
        self._write('lib/a.g.dart', bad)
        self._write('lib/a.freezed.dart', bad)
        self._write('lib/example/e.dart', bad)
        self._write('test/a_test.dart', bad)
        self._write('lib/b_test.dart', bad)
        self.assertEqual(v.collect_hardcoded_ui_strings(self.tmp),
                         {'lib/a.dart': 2})
        self.assertEqual(v.collect_raw_paths(self.tmp / 'lib', self.tmp),
                         {'lib/a.dart': 1})

    def test_nextjs_half(self):
        self._write('src/api.ts', "fetch('/api/method/x.y')\n")
        self._write('src/api.test.ts', "fetch('/api/method/x.y')\n")
        self._write('node_modules/p/i.js', "fetch('/api/method/x.y')\n")
        self.assertEqual(v.collect_raw_paths(self.tmp), {'src/api.ts': 1})


if __name__ == '__main__':
    unittest.main()

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

"""Tests for sdk_validator.py's icon set (Remixicon only) check.

Run:  python scripts/tests/test_sdk_validator_icons.py
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


class FindIconTests(unittest.TestCase):
    def test_flags_material_and_cupertino(self):
        text = ("Icon(Icons.add_rounded),\n"
                "Icon(CupertinoIcons.xmark_circle),\n"
                "Icon(Remix.add_line),\n")
        self.assertEqual(v.find_non_remix_icons(text),
                         [(1, 'Icons.add_rounded'),
                          (2, 'CupertinoIcons.xmark_circle')])

    def test_lookalike_classes_not_flagged(self):
        text = "Icon(RemixIcons.add); Icon(AppIcons.cart);\n"
        self.assertEqual(v.find_non_remix_icons(text), [])

    def test_flags_web_and_dart_packages(self):
        text = ("import { Check } from 'lucide-react';\n"
                "import { FiX } from \"react-icons/fi\";\n"
                "import 'package:font_awesome_flutter/font_awesome_flutter.dart';\n"
                "import { RiCheckLine } from '@remixicon/react';\n")
        self.assertEqual([n for n, _ in v.find_non_remix_icons(text)], [1, 2, 3])

    def test_exception_and_comments_skipped(self):
        text = ("Icon(Icons.adaptive.share), // icon-exception: platform share\n"
                "// Icons.add was here\n"
                "Icon(Icons.close), // icon-exception:\n")
        self.assertEqual([n for n, _ in v.find_non_remix_icons(text)], [3])


class CollectIconTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _write(self, rel, body):
        p = self.tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding='utf-8')

    def test_scans_lib_and_templates_only(self):
        self._write('lib/a.dart', 'Icon(Icons.add);\nIcon(Icons.remove);\n')
        self._write('templates/b.dart', 'Icon(Icons.home);\n')
        self._write('test/c_test.dart', 'Icon(Icons.home);\n')
        self._write('tool/d.dart', 'Icon(Icons.home);\n')
        self.assertEqual(
            v.collect_non_remix_icons(self.tmp, subdirs=['lib', 'templates']),
            {'lib/a.dart': 2, 'templates/b.dart': 1})


if __name__ == '__main__':
    unittest.main()

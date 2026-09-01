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

"""Tests for the {demo_email} tour placeholder (scripts/tour/merge_fragments.py).

The shared auth fragment signs the guided tour in with one hardcoded demo
account. MockAuthRepository maps that address to a role, and an app shell whose
session_policy rejects that role (paas_manager allows only 'seller') bounces the
tour back to /login, so the run captures a handful of screenshots and dies.

setup.demo_email in the shell's own tour/app.tour.yaml is how a shell picks its
account. These tests pin the two halves of that:

1. Default — a manifest with no setup.demo_email substitutes
   demo.student@example.com, so every shell that does not opt in is unchanged.
2. Override — setup.demo_email reaches {demo_email} inside a fragment's dart
   block (not just captions/titles: the sign-in email lives in dart).

Run:  python scripts/tests/test_tour_demo_email.py
      python -m unittest discover -s scripts/tests    (also works)
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
MERGER = os.path.join(REPO, "scripts", "tour", "merge_fragments.py")

# A stand-in for users' auth/dart/templates/tour/auth.tour.yaml: the demo
# sign-in step, with the email as a placeholder inside a dart block.
AUTH_FRAGMENT = """\
steps:
  - key: demo_sign_in
    action: dart
    settle: 6
    title: Sign in
    caption: Signing {app_name} in.
    dart: |
      login.setEmail('{demo_email}');
      login.setPassword('demo-learners-2026');
"""

APP_MANIFEST = """\
app:
  name: Test Shell
  tagline: A tagline
{setup}tour:
  - fragment: auth
"""


def _write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path


class DemoEmailPlaceholder(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="tour-demo-email-")
        # Composed cache copy of the auth fragment - keeps the merge offline.
        _write(self.root, os.path.join(".rokct", "cache", "auth", "templates",
                                       "tour", "auth.tour.yaml"), AUTH_FRAGMENT)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _merge(self, setup_block):
        _write(self.root, os.path.join("tour", "app.tour.yaml"),
               APP_MANIFEST.format(setup=setup_block))
        result = subprocess.run(
            [sys.executable, MERGER],
            cwd=self.root, capture_output=True, text=True, timeout=300,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        with io.open(os.path.join(self.root, "tour.resolved.json"),
                     encoding="utf-8") as f:
            plan = json.load(f)
        step = next(s for s in plan["steps"] if s["key"] == "demo_sign_in")
        # The resolved JSON carries caption/route metadata only - the dart
        # body is emitted solely into the generated steps file.
        with io.open(os.path.join(self.root, "integration_test",
                                  "tour_steps.g.dart"), encoding="utf-8") as f:
            dart = f.read()
        return step, dart, result.stdout + result.stderr

    def test_default_when_shell_declares_none(self):
        _step, dart, out = self._merge("")
        self.assertIn("login.setEmail('demo.student@example.com');", dart)
        self.assertNotIn("{demo_email}", dart)
        self.assertIn("demo account: demo.student@example.com (default)", out)

    def test_shell_override_reaches_the_dart_block(self):
        _step, dart, out = self._merge("setup:\n  demo_email: manager@demo.rokct.ai\n")
        self.assertIn("login.setEmail('manager@demo.rokct.ai');", dart)
        self.assertNotIn("demo.student@example.com", dart)
        self.assertNotIn("{demo_email}", dart)
        self.assertIn("demo account: manager@demo.rokct.ai", out)

    def test_captions_still_substitute(self):
        step, _dart, _out = self._merge("")
        self.assertEqual("Signing Test Shell in.", step["caption"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

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

"""Tests for the placeholder-aware syntax check and first-party prune override.

1. Placeholder-aware syntax check (compliance/__init__.py): an install-time
   template file whose ONLY parse failure comes from `{app_name}`-style
   placeholder tokens must not produce a `syntax-error` finding; genuinely
   broken Python must keep producing one; valid Python (dict/set literals,
   f-strings) is untouched because the substitution path only runs after a
   real SyntaxError.

2. First-party prune override (compliance/config.py + compliance_scanner.py):
   the vendored-framework exclude names ("frappe", "erpnext", "payments",
   "hrms", "lms") must not prune a first-party fleet module of the same name
   (agent/lms, pay/payments, pay/hrms). A directory carrying an SDK manifest
   half — frappe/manifest.json, nextjs/manifest.json, dart/manifest.json, or a
   manifest.json directly inside it — is owned code and stays in the walk;
   vendored framework checkouts (no manifests) stay excluded.

Run:  python scripts/tests/test_template_placeholders_and_prune.py
      python -m unittest discover -s scripts/tests    (also works)
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS_DIR)

from compliance import scan_file, is_template_syntax_error  # noqa: E402
from compliance.config import is_first_party_module_dir  # noqa: E402

SCANNER = os.path.join(SCRIPTS_DIR, "compliance_scanner.py")

# The real fleet template idiom (polaris-frappe et al.): imports and module
# paths carry `{app_name}` until install-time composition into a host app.
TEMPLATE_SOURCE = (
    'import frappe\n'
    'from {app_name}.polaris.tenant import gl_posting\n'
    'from {app_name}.{module_name}.api import handler\n'
    '\n'
    'def compose(site_name: str) -> dict:\n'
    '    """Wire the module into {app_name} at install time."""\n'
    '    return gl_posting.setup(site_name)\n'
)

BROKEN_SOURCE = (
    'def f(:\n'
    '    return 1\n'
)

VALID_BRACES_SOURCE = (
    'def g(name: str) -> dict:\n'
    '    """Braces galore — dict, set, f-string."""\n'
    '    d = {"k": 1}\n'
    '    s = {1, 2}\n'
    '    return {"msg": f"hello {name}", "d": d, "s": s}\n'
)


def _write(root, relpath, content):
    full = os.path.join(root, relpath.replace("/", os.sep))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    return full


class TestPlaceholderAwareSyntaxCheck(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="fixt_")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _checks(self, relpath, content):
        full = _write(tempfile.mkdtemp(prefix="c_", dir=self.root), relpath, content)
        return {e["check"] for e in scan_file(full)}

    def test_template_file_produces_no_syntax_error(self):
        found = self._checks("app/templates/gl_hooks.py", TEMPLATE_SOURCE)
        self.assertNotIn("syntax-error", found)

    def test_genuinely_broken_file_still_flags(self):
        found = self._checks("app/broken.py", BROKEN_SOURCE)
        self.assertIn("syntax-error", found)

    def test_valid_file_with_braces_is_untouched(self):
        found = self._checks("app/braces.py", VALID_BRACES_SOURCE)
        self.assertNotIn("syntax-error", found)

    def test_template_that_is_also_broken_still_flags(self):
        """A placeholder file with an independent syntax error keeps flagging."""
        src = 'from {app_name}.api import x\ndef f(:\n    return x\n'
        found = self._checks("app/tmpl_broken.py", src)
        self.assertIn("syntax-error", found)

    def test_broken_file_without_placeholders_never_enters_substitution(self):
        self.assertFalse(is_template_syntax_error(BROKEN_SOURCE, "broken.py"))

    def test_template_source_is_recognised(self):
        self.assertTrue(is_template_syntax_error(TEMPLATE_SOURCE, "tmpl.py"))

    def test_pattern_is_conservative_lowercase_snake_case(self):
        """{app_name}/{module_name}-style tokens qualify; {Upper}/{123} do not."""
        self.assertTrue(is_template_syntax_error(
            "from {app_name}.x import y\n", "t.py"))
        self.assertTrue(is_template_syntax_error(
            "from {module_name} import z\n", "t.py"))
        # An uppercase token is not the fleet template idiom — stays flagged.
        self.assertFalse(is_template_syntax_error(
            "from {AppName}.x import y\n", "t.py"))

    def test_other_checks_still_run_on_template_files(self):
        """Skipping the syntax-error finding must not skip file-level checkers.

        AST-visitor checks can't run on an unparseable template (true before
        this change too), but raw-content FILE_CHECKERS — layer 11's
        auth-hardcoded-token here — must keep firing.
        """
        src = TEMPLATE_SOURCE + 'access_token = "abcdef1234567890"\n'
        found = self._checks("app/session_hooks.py", src)
        self.assertNotIn("syntax-error", found)
        self.assertIn("auth-hardcoded-token", found)


class TestFirstPartyModuleDetection(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="fixt_")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_module_dir_with_flavor_halves_is_first_party(self):
        """agent/lms shape: lms/{frappe,nextjs,dart}/manifest.json."""
        lms = os.path.join(self.root, "lms")
        _write(self.root, "lms/frappe/manifest.json", "{}")
        self.assertTrue(is_first_party_module_dir(lms))

    def test_each_flavor_half_marker_counts(self):
        for flavor in ("frappe", "nextjs", "dart"):
            mod = os.path.join(self.root, f"mod_{flavor}")
            _write(self.root, f"mod_{flavor}/{flavor}/manifest.json", "{}")
            self.assertTrue(is_first_party_module_dir(mod), flavor)

    def test_flavor_half_dir_itself_is_first_party(self):
        """lms/frappe/ carries manifest.json directly — the same rule keeps it
        in the walk when the walk descends INTO lms/ and meets 'frappe'."""
        half = os.path.join(self.root, "lms", "frappe")
        _write(self.root, "lms/frappe/manifest.json", "{}")
        self.assertTrue(is_first_party_module_dir(half))

    def test_vendored_framework_checkout_is_not_first_party(self):
        """Upstream frappe/erpnext checkouts have no SDK manifests — pruned."""
        vendored = os.path.join(self.root, "frappe")
        _write(self.root, "frappe/frappe/utils.py", "x = 1\n")
        _write(self.root, "frappe/setup.py", "y = 2\n")
        self.assertFalse(is_first_party_module_dir(vendored))

    def test_missing_dir_is_not_first_party(self):
        self.assertFalse(
            is_first_party_module_dir(os.path.join(self.root, "nope")))


class TestScannerWalkKeepsFirstPartyModules(unittest.TestCase):
    """End-to-end through compliance_scanner.py's real walk."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="fixt_")
        # Synthetic repo root:
        #   app.py                       — always scanned
        #   lms/frappe/manifest.json     — first-party module (agent/lms shape)
        #   lms/frappe/src/models.py     — must be scanned AFTER the fix
        #   frappe/frappe/utils.py       — vendored checkout, must STAY pruned
        _write(self.root, "app.py", "x = 1\n")
        _write(self.root, "lms/frappe/manifest.json", "{}")
        _write(self.root, "lms/frappe/src/models.py", "y = 2\n")
        _write(self.root, "frappe/frappe/utils.py", "z = 3\n")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_first_party_module_scanned_vendored_checkout_pruned(self):
        result = subprocess.run(
            [sys.executable, SCANNER],
            cwd=self.root, capture_output=True, text=True, timeout=300,
            env={**os.environ, "CI": "false", "GITHUB_ACTIONS": "false"},
        )
        # app.py + lms/frappe/src/models.py — and NOT frappe/frappe/utils.py.
        self.assertIn("Auditing 2 source files", result.stdout,
                      f"stdout was:\n{result.stdout}\nstderr:\n{result.stderr}")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)

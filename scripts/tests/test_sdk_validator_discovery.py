#!/usr/bin/env python3
# Copyright (c) 2026 RokctAI
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

"""Tests for sdk_validator.py's SDK flavor-half discovery.

Covers three invariants of the frappe/nextjs discovery added alongside the
dart discovery:

1. Additivity — `*/frappe/manifest.json` and `*/nextjs/manifest.json` halves
   are discovered, keyed distinctly (a module's dart and nextjs manifests may
   share a "name"), and never overlap what find_manifests() claims.
2. Vendored-framework safety — a vendored Frappe framework checkout (a
   frappe/ directory WITHOUT a manifest.json at its root) is never treated
   as an SDK half.
3. Dart output is byte-identical — running the full validator over a fixture
   workspace with and without flavor halves present produces the exact same
   dart audit lines, in the same order; flavor coverage is purely appended.

Run:  python scripts/tests/test_sdk_validator_discovery.py
      python -m unittest discover -s scripts/tests    (also works)
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS_DIR)

import sdk_validator  # noqa: E402

VALIDATOR = os.path.join(SCRIPTS_DIR, "sdk_validator.py")

TIMESTAMP_RE = re.compile(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] ")


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)


def build_dart_sdk(root):
    """Minimal dart SDK half: moda/dart with a census-conforming skeleton."""
    dart = root / "moda" / "dart"
    write_json(dart / "manifest.json", {
        "name": "moda_sdk",
        "version": "1.0.0",
        "installs": [],
    })
    src = dart / "lib" / "src"
    for rel in ("di", "application/feature",
                "infrastructure/repositories", "domain/interface"):
        d = src / rel
        d.mkdir(parents=True, exist_ok=True)
        (d / "placeholder.dart").write_text("// ok\n", encoding="utf-8")


def build_flavor_halves(root):
    """moda/frappe + moda/nextjs halves, plus vendored decoys."""
    frappe = root / "moda" / "frappe"
    write_json(frappe / "manifest.json", {
        "name": "moda",
        "description": "frappe half",
        "app_type": {"control": {"hooks": {}}},
    })
    (frappe / "src").mkdir(parents=True, exist_ok=True)
    (frappe / "src" / "api.py").write_text("VALUE = 1\n", encoding="utf-8")

    nextjs = root / "moda" / "nextjs"
    write_json(nextjs / "manifest.json", {
        "name": "moda_sdk",  # deliberately the same name as the dart half
        "version": "1.0.0",
        "installs": [{"from": "templates/app", "to": "app"}],
    })
    (nextjs / "templates" / "app").mkdir(parents=True, exist_ok=True)
    (nextjs / "templates" / "app" / "page.tsx").write_text(
        "export {}\n", encoding="utf-8")

    # Vendored Frappe FRAMEWORK checkout: a frappe/ dir with code but no
    # manifest.json at its root. Must never be discovered as an SDK half.
    vendored = root / "apps" / "frappe"
    (vendored / "frappe").mkdir(parents=True, exist_ok=True)
    (vendored / "frappe" / "hooks.py").write_text("app_name = 'frappe'\n",
                                                  encoding="utf-8")
    # A manifest deeper inside the vendored tree (not directly in a
    # frappe/ or nextjs/ dir) must not be discovered either.
    write_json(vendored / "frappe" / "somepkg" / "manifest.json",
               {"name": "not_an_sdk"})


def run_validator(root, cwd):
    env = os.environ.copy()
    env.pop("GITHUB_WORKSPACE", None)
    proc = subprocess.run(
        [sys.executable, VALIDATOR, "--root", str(root)],
        cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=env,
    )
    lines = []
    for line in proc.stdout.splitlines():
        line = TIMESTAMP_RE.sub("", line)
        # The workspace root path differs per fixture; normalize it away.
        line = line.replace(str(root), "<ROOT>")
        lines.append(line)
    return lines


class TestFlavorDiscovery(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sdkval_test_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _workspace(self, name, with_flavors):
        root = self.tmp / name
        build_dart_sdk(root)
        if with_flavors:
            build_flavor_halves(root)
        return root

    def test_flavor_halves_discovered_and_disjoint_from_dart(self):
        root = self._workspace("ws", with_flavors=True)
        dart = sdk_validator.find_manifests(str(root))
        flavors = sdk_validator.find_flavor_manifests(str(root))

        self.assertEqual(
            [str(root / "moda" / "dart" / "manifest.json")], dart)
        self.assertEqual(
            {(str(root / "moda" / "frappe" / "manifest.json"), "frappe"),
             (str(root / "moda" / "nextjs" / "manifest.json"), "nextjs")},
            set(flavors))
        # No path is ever claimed by both discoveries.
        self.assertFalse(set(dart) & {p for p, _ in flavors})

    def test_vendored_framework_dir_is_not_an_sdk_half(self):
        root = self._workspace("ws", with_flavors=True)
        flavors = {p for p, _ in
                   sdk_validator.find_flavor_manifests(str(root))}
        for path in flavors:
            self.assertNotIn(os.path.join("apps", "frappe"), path)

    def test_flavor_labels_do_not_collide_with_dart_names(self):
        root = self._workspace("ws", with_flavors=True)
        flavors = sdk_validator.find_flavor_manifests(str(root))
        data = sdk_validator.parse_flavor_manifests(flavors)
        # nextjs half shares name "moda_sdk" with the dart half; the label
        # keeps them distinct.
        self.assertEqual({"moda (frappe)", "moda_sdk (nextjs)"},
                         set(data.keys()))

    def test_flavor_manifest_missing_from_path_is_an_error(self):
        root = self._workspace("ws", with_flavors=True)
        bad = root / "moda" / "nextjs" / "manifest.json"
        write_json(bad, {
            "name": "moda_sdk",
            "installs": [{"from": "templates/missing", "to": "app"}],
        })

        class Collector:
            def __init__(self):
                self.errors = []

            def log(self, message, level="INFO", sdk_name=None):
                if level == "ERROR":
                    self.errors.append(message)

        collector = Collector()
        ok = sdk_validator.validate_flavor_manifest(
            "moda_sdk (nextjs)", bad.parent, str(bad), collector)
        self.assertFalse(ok)
        self.assertTrue(any("templates/missing" in m
                            for m in collector.errors))

    def test_dart_output_is_byte_identical_with_flavors_present(self):
        root_a = self._workspace("ws_a", with_flavors=False)
        root_b = self._workspace("ws_b", with_flavors=True)

        cwd_a = self.tmp / "run_a"
        cwd_b = self.tmp / "run_b"
        cwd_a.mkdir()
        cwd_b.mkdir()
        lines_a = run_validator(root_a, cwd_a)
        lines_b = run_validator(root_b, cwd_b)

        # Strip the purely-additive flavor lines from run B: the discovery
        # count line and the appended flavor-audit block.
        stripped_b = []
        in_flavor_block = False
        for line in lines_b:
            if line.startswith("[INFO] Discovered ") and "flavor" in line:
                continue
            if line.startswith("[INFO] --- Auditing SDK flavor half:"):
                in_flavor_block = True
                continue
            if in_flavor_block and line.startswith("[INFO] Global audit"):
                in_flavor_block = False
            if in_flavor_block:
                continue
            stripped_b.append(line)

        self.assertEqual(lines_a, stripped_b)
        # And run B did actually audit the flavor halves.
        self.assertTrue(any("Auditing SDK flavor half: moda (frappe)" in ln
                            for ln in lines_b))
        self.assertTrue(any("Auditing SDK flavor half: moda_sdk (nextjs)" in ln
                            for ln in lines_b))


if __name__ == "__main__":
    unittest.main(verbosity=2)

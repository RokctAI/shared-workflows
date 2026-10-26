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
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "render", "merge_render_fragments.py")

FRAG = textwrap.dedent("""
    screens:
      - name: tutors
        widget: TutorDiscoveryRouteView
        import: package:{package}/presentation/routes/lms_route_pages.dart
      - name: courses
        caption: Course catalog
        widget: CourseCatalogRouteView
        import: package:{package}/presentation/routes/lms_route_pages.dart
""")


def run(root, extra=()):
    return subprocess.run(
        [sys.executable, SCRIPT, "--cache-dir", os.path.join(root, "cache"),
         "--pubspec", os.path.join(root, "pubspec.yaml"),
         "--out-dir", os.path.join(root, "out"), *extra],
        capture_output=True, text=True)


class RenderFragments(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        with open(os.path.join(self.root, "pubspec.yaml"), "w") as f:
            f.write("name: supacharge\n")

    def tearDown(self):
        self.tmp.cleanup()

    def frag(self, text, sdk="lms_sdk"):
        d = os.path.join(self.root, "cache", sdk, "templates", "render")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{sdk}.render.yaml"), "w") as f:
            f.write(text)

    def test_generates_dart_and_frames(self):
        self.frag(FRAG)
        r = run(self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        dart = open(os.path.join(self.root, "out", "render_screens.g.dart")).read()
        self.assertIn("package:supacharge/presentation/routes/lms_route_pages.dart", dart)
        self.assertIn("'tutors': GeneratedScreen(() => const TutorDiscoveryRouteView()", dart)
        frames = json.load(open(os.path.join(self.root, "out", "strip.frames.g.json")))
        self.assertEqual(len(frames), 4)
        self.assertEqual(frames[2]["caption"], "Course catalog - dark")

    def test_no_fragments_is_not_a_failure(self):
        r = run(self.root)
        self.assertEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.root, "out", "render_screens.g.dart")))

    def test_no_fragments_needs_no_pyyaml(self):
        blocker = os.path.join(self.root, "blocker")
        os.makedirs(blocker)
        with open(os.path.join(blocker, "yaml.py"), "w") as f:
            f.write("raise ImportError('no yaml here')\n")
        env = dict(os.environ, PYTHONPATH=blocker)
        r = subprocess.run(
            [sys.executable, SCRIPT, "--cache-dir", os.path.join(self.root, "cache"),
             "--pubspec", os.path.join(self.root, "pubspec.yaml"),
             "--out-dir", os.path.join(self.root, "out")],
            capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_duplicate_name_fails(self):
        self.frag(FRAG)
        self.frag(FRAG, sdk="other_sdk")
        self.assertNotEqual(run(self.root).returncode, 0)


if __name__ == "__main__":
    unittest.main()

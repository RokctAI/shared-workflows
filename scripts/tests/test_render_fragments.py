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


class TourIsTheScreenList(RenderFragments):
    """--tour-resolved: the tour picks the screens; nothing is listed twice."""

    def tour(self, *keys):
        path = os.path.join(self.root, "tour.resolved.json")
        with open(path, "w") as f:
            json.dump({"steps": [{"key": k, "action": "route"} for k in keys]}, f)
        return path

    def strip(self):
        path = os.path.join(self.root, "strip.json")
        with open(path, "w") as f:
            json.dump({"frames": [{"caption": "own", "png": "own.png", "rects": "own.json"}]}, f)
        return path

    def run_tour(self, tour, extra=()):
        out = os.path.join(self.root, "merged.json")
        r = run(self.root, ["--tour-resolved", tour, "--strip-config", self.strip(),
                            "--out-strip-config", out, *extra])
        return r, out

    def test_only_tour_steps_render_and_the_rest_are_skipped_with_a_reason(self):
        self.frag(FRAG)
        r, out = self.run_tour(self.tour("courses", "welcome"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        dart = open(os.path.join(self.root, "out", "render_screens.g.dart")).read()
        self.assertIn("'courses'", dart)
        self.assertNotIn("'tutors'", dart)  # a fragment screen that is not a tour step
        self.assertIn("skipped tour step 'welcome'", r.stdout)
        self.assertIn("ignoring fragment screen 'tutors'", r.stdout)
        frames = json.load(open(out))["frames"]
        self.assertEqual([f["png"] for f in frames],
                         ["own.png", "courses_dark.png", "courses_light.png"])
        self.assertTrue(frames[1]["generated"])
        self.assertNotIn("generated", frames[0])

    def test_explicit_frame_wins_for_the_same_tour_screen(self):
        self.frag(FRAG)
        path = os.path.join(self.root, "strip.json")
        with open(path, "w") as f:
            json.dump({"frames": [
                {"caption": "chips", "png": "tutors_light.png", "rects": "x.json"},
                {"caption": "chips2", "tour": "courses", "png": "c.png", "rects": "c.json"}]}, f)
        out = os.path.join(self.root, "merged.json")
        r = run(self.root, ["--tour-resolved", self.tour("tutors", "courses"),
                            "--strip-config", path, "--out-strip-config", out])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        pngs = [f["png"] for f in json.load(open(out))["frames"]]
        self.assertEqual(pngs, ["tutors_light.png", "c.png", "tutors_dark.png"])

    def test_tour_with_no_fragments_skips_everything_and_does_not_fail(self):
        r, out = self.run_tour(self.tour("welcome", "home"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("0 renderable, 2 skipped", r.stdout)
        self.assertFalse(os.path.exists(out))

    def test_skipped_steps_are_written_machine_readable(self):
        self.frag(FRAG)
        r, _ = self.run_tour(self.tour("courses", "welcome"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        data = json.load(open(os.path.join(self.root, "out", "tour_skipped.g.json")))
        self.assertEqual([e["key"] for e in data], ["welcome"])
        self.assertIn("no render fragment", data[0]["reason"])

    def test_skipped_list_groups_no_page_and_failed_screens(self):
        tour_skipped = os.path.join(self.root, "tour_skipped.g.json")
        json.dump([{"key": "welcome", "reason": "x"}], open(tour_skipped, "w"))
        harness = os.path.join(self.root, "skipped.jsonl")
        with open(harness, "w") as f:
            for mode in ("dark", "light"):
                f.write(json.dumps({"key": "search", "mode": mode,
                                    "reason": "Bad state: not registered\nsecond line"}) + "\n")
        md = os.path.join(self.root, "sub", "render-skipped.md")
        r = subprocess.run([sys.executable, SCRIPT, "--write-skipped-md", md,
                            "--tour-skipped", tour_skipped, "--harness-skipped", harness],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text = open(md).read()
        self.assertIn("- welcome - no standalone page (opens from a tap)", text)
        self.assertIn("- search (dark, light) - failed to draw: Bad state: not registered", text)
        self.assertNotIn("second line", text)
        self.assertNotIn("All tour screens drawn", text)

    def test_skipped_list_says_all_drawn_when_nothing_skipped(self):
        md = os.path.join(self.root, "render-skipped.md")
        r = subprocess.run([sys.executable, SCRIPT, "--write-skipped-md", md,
                            "--tour-skipped", os.path.join(self.root, "none.json"),
                            "--harness-skipped", os.path.join(self.root, "none.jsonl")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("All tour screens drawn.", open(md).read())

    def test_prune_drops_only_generated_frames_the_harness_did_not_render(self):
        self.frag(FRAG)
        r, out = self.run_tour(self.tour("tutors", "courses"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        render_out = os.path.join(self.root, "rendered")
        os.makedirs(render_out)
        for name in ("tutors_dark", "tutors_light"):
            for ext in ("png", "json"):
                open(os.path.join(render_out, f"{name}.{ext}"), "w").close()
        pruned = os.path.join(self.root, "pruned.json")
        r = subprocess.run(
            [sys.executable, SCRIPT, "--prune-config", out, "--base-dir", render_out,
             "--out-strip-config", pruned], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("skipped 'Course catalog - dark'", r.stdout)
        pngs = [f["png"] for f in json.load(open(pruned))["frames"]]
        # explicit frame kept even though its png is absent; courses dropped
        self.assertEqual(pngs, ["own.png", "tutors_dark.png", "tutors_light.png"])


if __name__ == "__main__":
    unittest.main()

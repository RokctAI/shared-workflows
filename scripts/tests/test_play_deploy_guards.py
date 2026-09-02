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

"""Tests for the two Play-deploy safety refusals.

The Play deploy is one credential fix away from an unattended, destructive
store push, by two independent routes:

1. The gate's weekly-limit and nothing-new rules are each written as "the last
   value is SET and matches". With no readable .play-store-release-state.json
   every last value is empty, so not one of them can refuse and the gate passes
   anything. A state nobody can read must be refused, not read as permission.
2. upload_assets refreshes an image type with images().deleteall() followed by
   uploads - Play has no replace. For an app whose screenshots were set by hand
   in Play Console, that delete takes down the only copy. The replacement set
   has to be established BEFORE anything is removed.

These tests run the gate's REAL bash - lifted out of the workflow, with the
`${{ }}` expressions bound to the values under test - so they pin the shipped
logic rather than a paraphrase of it.

Run:  python3 scripts/tests/test_play_deploy_guards.py
      python3 -m unittest discover -s scripts/tests    (also works)
"""

import importlib.util
import json
import os
import re
import subprocess
import tempfile
import unittest

import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKFLOW = os.path.join(REPO_ROOT, ".github", "workflows", "universal-play-deploy.yml")
UPLOADER = os.path.join(REPO_ROOT, "scripts", "play", "upload_listing_assets.py")

_spec = importlib.util.spec_from_file_location("upload_listing_assets", UPLOADER)
uploader = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(uploader)

EXPR = re.compile(r"\$\{\{\s*([A-Za-z0-9_.\-]+)\s*\}\}")


def gate_steps():
    """The gate job's 'Read Release State Marker' and 'Decide' run: blocks."""
    with open(WORKFLOW, encoding="utf-8") as handle:
        workflow = yaml.safe_load(handle)
    steps = {s["name"]: s for s in workflow["jobs"]["gate"]["steps"] if "name" in s}
    return steps["Read Release State Marker"]["run"], steps["Decide"]["run"]


def bind(script, values):
    """Substitute the workflow's `${{ ... }}` expressions with real values."""

    def one(match):
        key = match.group(1)
        if key not in values:
            raise AssertionError(f"gate script uses an unbound expression: {key}")
        return values[key]

    return EXPR.sub(one, script)


def run_gate(state_file, allow_first="false", on_main="true", version="1.2.3", sha="deadbeef"):
    """Run both gate steps for real; returns (exit code, outputs, stdout)."""
    read_step, decide_step = gate_steps()
    workdir = tempfile.mkdtemp(prefix="gate_")
    output = os.path.join(workdir, "GITHUB_OUTPUT")
    open(output, "w").close()
    env = dict(os.environ, GITHUB_OUTPUT=output)

    def outputs():
        parsed = {}
        with open(output, encoding="utf-8") as handle:
            for line in handle:
                if "=" in line:
                    name, _, value = line.rstrip("\n").partition("=")
                    parsed[name] = value
        return parsed

    read = bind(read_step, {"inputs.state_file": state_file})
    first = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", read],
        cwd=workdir, env=env, capture_output=True, text=True,
    )
    if first.returncode:
        return first.returncode, outputs(), first.stdout + first.stderr

    read_out = outputs()
    decide = bind(
        decide_step,
        {
            "steps.current_version.outputs.version": version,
            "steps.pkg.outputs.package_name": "com.example.app",
            "github.sha": sha,
            "steps.state.outputs.last_version": read_out.get("last_version", ""),
            "steps.state.outputs.last_week": read_out.get("last_week", ""),
            "steps.state.outputs.last_sha": read_out.get("last_sha", ""),
            "steps.state.outputs.state_known": read_out.get("state_known", ""),
            "steps.state.outputs.state_problem": read_out.get("state_problem", ""),
            "steps.branch_check.outputs.on_main": on_main,
            "inputs.state_file": state_file,
            "inputs.allow_first_release": allow_first,
        },
    )
    second = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", decide],
        cwd=workdir, env=env, capture_output=True, text=True,
    )
    return second.returncode, outputs(), first.stdout + second.stdout + second.stderr


class ReleaseStateGate(unittest.TestCase):
    def marker(self, payload):
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        handle.write(payload if isinstance(payload, str) else json.dumps(payload))
        handle.close()
        return handle.name

    def missing_path(self):
        return os.path.join(tempfile.mkdtemp(prefix="nostate_"), ".play-state.json")

    # -- refusal paths ---------------------------------------------------------
    def test_absent_marker_refuses_red(self):
        path = self.missing_path()
        code, outputs, log = run_gate(path)
        self.assertEqual(outputs["proceed"], "false")
        self.assertEqual(outputs["reason"], "release-state-unknown")
        self.assertEqual(code, 1, "an unknown release state must fail the gate, not no-op")
        self.assertIn(path, log)
        self.assertIn("Refusing to deploy", log)

    def test_unreadable_marker_refuses(self):
        code, outputs, log = run_gate(self.marker("{not json at all"))
        self.assertEqual(outputs["reason"], "release-state-unknown")
        self.assertEqual(code, 1)
        self.assertIn("could not be read as JSON", log)

    def test_partial_marker_refuses(self):
        # last_release_sha missing => the "no new commits" rule is inert.
        path = self.marker({"last_version": "1.0.0", "last_release_iso_week": "2026-W01"})
        code, outputs, log = run_gate(path)
        self.assertEqual(outputs["reason"], "release-state-unknown")
        self.assertEqual(code, 1)
        self.assertIn("is missing last_version", log)

    # -- the deliberate opt-in -------------------------------------------------
    def test_opt_in_allows_the_first_release(self):
        code, outputs, log = run_gate(self.missing_path(), allow_first="true")
        self.assertEqual(outputs["proceed"], "true")
        self.assertEqual(code, 0)
        self.assertIn("::warning::", log)
        self.assertIn("REPLACE every listing image", log)

    def test_an_earlier_no_op_reason_keeps_its_clean_exit(self):
        # A branch that was never going to deploy stays an ordinary green
        # no-op; the state refusal only speaks for runs that would otherwise
        # have gone out.
        code, outputs, log = run_gate(self.missing_path(), on_main="false")
        self.assertEqual(outputs["reason"], "not-on-main")
        self.assertEqual(code, 0)
        self.assertIn("No-op", log)

    def test_opt_in_does_not_override_the_other_rules(self):
        # Still narrowing: opting in to an unknown state does not buy a
        # deploy off a non-main branch.
        code, outputs, _ = run_gate(self.missing_path(), allow_first="true", on_main="false")
        self.assertEqual(outputs["proceed"], "false")
        self.assertEqual(outputs["reason"], "not-on-main")
        self.assertEqual(code, 0)

    # -- a healthy, gated deploy is unchanged ----------------------------------
    def test_complete_marker_still_proceeds(self):
        path = self.marker(
            {
                "last_version": "1.0.0",
                "last_release_iso_week": "1999-W01",
                "last_release_sha": "0000000",
            }
        )
        code, outputs, _ = run_gate(path, version="1.2.3", sha="deadbeef")
        self.assertEqual(outputs["proceed"], "true")
        self.assertEqual(code, 0)

    def test_complete_marker_still_no_ops_on_same_version(self):
        path = self.marker(
            {
                "last_version": "1.2.3",
                "last_release_iso_week": "1999-W01",
                "last_release_sha": "0000000",
            }
        )
        code, outputs, log = run_gate(path, version="1.2.3")
        self.assertEqual(outputs["reason"], "version-unchanged-since-last-release")
        self.assertEqual(code, 0, "an ordinary no-op stays green")
        self.assertIn("No-op", log)


class VerifyBeforeDelete(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="assets_")

    def png(self, name, size=(1080, 1920)):
        from PIL import Image

        path = os.path.join(self.dir, name)
        Image.new("RGB", size, (1, 2, 3)).save(path, format="PNG")
        return path

    def test_a_good_set_has_no_problems(self):
        assets = {"phoneScreenshots": [self.png("01-a.png"), self.png("02-b.png")]}
        self.assertEqual(uploader.verify_upload_set(assets), [])

    def test_missing_file_is_refused(self):
        path = self.png("01-a.png")
        os.remove(path)
        problems = uploader.verify_upload_set({"phoneScreenshots": [path]})
        self.assertEqual(len(problems), 1)
        self.assertIn("no longer on disk", problems[0])

    def test_unreadable_image_is_refused(self):
        path = self.png("01-a.png")
        with open(path, "wb") as handle:
            handle.write(b"not a png")
        problems = uploader.verify_upload_set({"phoneScreenshots": [path]})
        self.assertEqual(len(problems), 1)
        self.assertIn("no longer readable as an image", problems[0])

    def test_unknown_extension_is_refused(self):
        path = os.path.join(self.dir, "01-a.gif")
        with open(path, "wb") as handle:
            handle.write(b"GIF89a")
        problems = uploader.verify_upload_set({"phoneScreenshots": [path]})
        self.assertEqual(len(problems), 1)
        self.assertIn("no upload MIME type", problems[0])

    def test_oversized_image_is_refused(self):
        path = self.png("01-a.png")
        with open(path, "ab") as handle:
            handle.write(b"\0" * (uploader.MAX_IMAGE_BYTES + 1))
        problems = uploader.verify_upload_set({"phoneScreenshots": [path]})
        self.assertEqual(len(problems), 1)
        self.assertIn("listing-image limit", problems[0])

    def test_empty_type_is_refused_rather_than_clearing_the_listing(self):
        problems = uploader.verify_upload_set({"tenInchScreenshots": []})
        self.assertEqual(len(problems), 1)
        self.assertIn("clearing it would leave", problems[0])

    def test_every_bad_file_is_named_not_just_the_first(self):
        good = self.png("01-a.png")
        gone = self.png("02-b.png")
        os.remove(gone)
        problems = uploader.verify_upload_set(
            {"phoneScreenshots": [good, gone], "tenInchScreenshots": []}
        )
        self.assertEqual(len(problems), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)

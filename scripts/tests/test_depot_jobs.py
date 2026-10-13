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

"""Tests for scripts/depot/ (repo-side jobs for depot_sdk storage repos).

Run:  python3 scripts/tests/test_depot_jobs.py

Each test builds a real bare git repo as the "GitHub" remote plus a clone the
job runs in, so commit, push, retry and resume paths are exercised for real.
Google's Picker API and the face models are faked.
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))

from scripts.depot import (  # noqa: E402
    exif_job,
    gitops,
    jobs,
    layout,
    net,
    people_job,
    picker_import,
    size_report,
)
from scripts.depot.index import RepoIndex  # noqa: E402


def sh(cwd, *args):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


class RepoCase(unittest.TestCase):
    """A bare remote with a connected depot (manifest only) and a clone."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="depot-test-")
        self.remote = os.path.join(self.tmp, "remote.git")
        sh(self.tmp, "git", "init", "-q", "--bare", "-b", "main", self.remote)
        seed = os.path.join(self.tmp, "seed")
        sh(self.tmp, "git", "clone", "-q", self.remote, seed)
        manifest = {
            "layout_version": 1,
            "depot_id": "d1",
            "shard": 0,
            "updated_at": "2026-10-01T00:00:00.000Z",
            "shards": {},
        }
        gitops.write_file(seed, layout.MANIFEST_PATH, layout.encode_json(manifest))
        self.commit_all(seed, "Set up depot storage")
        sh(seed, "git", "push", "-q", "origin", "HEAD:main")
        self.root = os.path.join(self.tmp, "work")
        sh(self.tmp, "git", "clone", "-q", self.remote, self.root)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def commit_all(self, cwd, msg):
        sh(cwd, "git", "add", "-A")
        sh(
            cwd,
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-q",
            "-m",
            msg,
        )

    def remote_json(self, rel):
        out = subprocess.run(
            ["git", "--git-dir", self.remote, "show", f"main:{rel}"],
            capture_output=True,
            check=True,
        ).stdout
        return json.loads(out)

    def remote_has(self, rel):
        return (
            subprocess.run(
                ["git", "--git-dir", self.remote, "cat-file", "-e", f"main:{rel}"],
                capture_output=True,
            ).returncode
            == 0
        )

    def remote_log(self):
        return subprocess.run(
            ["git", "--git-dir", self.remote, "log", "--format=%s", "main"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()


class LayoutParity(unittest.TestCase):
    """Must agree with depot_sdk's DepotLayout and depot_models.dart."""

    SHA = "ab12cd34ef56ab12cd34ef56ab12cd34ef56ab12cd34ef56ab12cd34ef56ab12"

    def test_paths(self):
        self.assertEqual(
            layout.object_path(self.SHA, "jpg"), f"depot/objects/ab/{self.SHA}.jpg"
        )
        self.assertEqual(
            layout.object_path(self.SHA, ""), f"depot/objects/ab/{self.SHA}"
        )
        self.assertEqual(layout.thumb_path(self.SHA), f"depot/thumbs/ab/{self.SHA}.jpg")
        self.assertEqual(layout.meta_path(self.SHA), f"depot/meta/ab/{self.SHA}.json")
        self.assertEqual(layout.shard_path("2026-01-05"), "depot/index/2026/01/05.json")
        self.assertEqual(layout.shard_path("undated"), "depot/index/undated.json")

    def test_day_key_is_utc(self):
        from datetime import timedelta

        plus2 = timezone(timedelta(hours=2))
        self.assertEqual(
            layout.day_key(datetime(2026, 10, 12, 23, 30, tzinfo=plus2)), "2026-10-12"
        )
        self.assertEqual(
            layout.day_key(datetime(2026, 10, 12, 1, 0, tzinfo=plus2)), "2026-10-11"
        )
        self.assertEqual(layout.day_key(None), "undated")

    def test_extensions(self):
        for name, ext in [
            ("IMG_0042.JPG", "jpg"),
            ("report.final.xlsx", "xlsx"),
            ("README", ""),
            (".hidden", ""),
            ("trailing.", ""),
            ("weird.ext with space", ""),
        ]:
            self.assertEqual(layout.extension_of(name), ext, name)

    def test_iso_matches_dart(self):
        self.assertEqual(
            layout.iso(datetime(2026, 10, 12, 12, tzinfo=timezone.utc)),
            "2026-10-12T12:00:00.000Z",
        )

    def test_entry_keys_in_dart_order(self):
        when = datetime(2026, 10, 12, tzinfo=timezone.utc)
        v = layout.version_json(1, "a" * 64, 3, "me/photos", "p", when)
        self.assertEqual(
            list(v),
            [
                "version",
                "sha256",
                "size",
                "repo",
                "path",
                "thumb_path",
                "commit_sha",
                "created_at",
            ],
        )
        e = layout.entry_json("f", "n", "image/jpeg", when, when, [v])
        self.assertEqual(
            list(e),
            [
                "file_id",
                "name",
                "mime",
                "folder_id",
                "created_at",
                "modified_at",
                "deleted_at",
                "current",
                "versions",
                "tags",
            ],
        )

    def test_json_encoding_matches_dart(self):
        self.assertEqual(
            layout.encode_json({"a": [1], "b": {}}),
            b'{\n  "a": [\n    1\n  ],\n  "b": {}\n}\n',
        )


class IndexAndNotes(RepoCase):
    def test_put_move_and_counts(self):
        idx = RepoIndex(self.root)
        when = datetime(2026, 10, 12, tzinfo=timezone.utc)
        e = layout.entry_json("f1", "a.jpg", "image/jpeg", None, when, [])
        idx.put("undated", e)
        idx.write(when)
        idx = RepoIndex(self.root)
        idx.move(idx.shard("undated")["entries"]["f1"], "undated", "2026-01-02")
        idx.write(when)
        with open(os.path.join(self.root, layout.MANIFEST_PATH)) as fh:
            m = json.load(fh)
        self.assertEqual(m["shards"]["undated"]["count"], 0)
        self.assertEqual(m["shards"]["2026-01-02"]["count"], 1)

    def test_notes_reject_unknown_status(self):
        with self.assertRaises(ValueError):
            jobs.write(self.root, "x", "k", "paused")
        jobs.write(self.root, "x", "k", "running", page_token="p2")
        self.assertEqual(jobs.read(self.root, "x")["page_token"], "p2")

    def test_missing_manifest_is_refused(self):
        os.remove(os.path.join(self.root, layout.MANIFEST_PATH))
        with self.assertRaises(FileNotFoundError):
            RepoIndex(self.root)


class CommitBatch(RepoCase):
    def test_retries_on_top_of_a_concurrent_push(self):
        other = os.path.join(self.tmp, "phone")
        sh(self.tmp, "git", "clone", "-q", self.remote, other)
        calls = []

        def apply():
            calls.append(1)
            if len(calls) == 1:  # the phone commits while this job works
                gitops.write_file(other, "depot/phone.txt", b"phone\n")
                self.commit_all(other, "Back up 1 file")
                sh(other, "git", "push", "-q", "origin", "HEAD:main")
            gitops.write_file(self.root, "depot/job.txt", b"job\n")
            return ["depot/job.txt"]

        sha = gitops.commit_batch(self.root, apply, "job")
        self.assertTrue(sha)
        # first fetch already sees nothing; the push races on attempt 1 only
        self.assertTrue(self.remote_has("depot/phone.txt"))
        self.assertTrue(self.remote_has("depot/job.txt"))

    def test_nothing_to_commit(self):
        self.assertIsNone(gitops.commit_batch(self.root, lambda: [], "noop"))


class SizeReport(RepoCase):
    def test_writes_then_skips_tiny_changes(self):
        size_report.run(self.root, 5 * 1024**3, 9 * 1024**3)
        r = self.remote_json(layout.SIZE_REPORT_PATH)
        self.assertFalse(r["near_limit"])
        self.assertIsNone(size_report.run(self.root, 5 * 1024**3 + 10, 9 * 1024**3))
        size_report.run(self.root, 9 * 1024**3, 9 * 1024**3)
        self.assertTrue(self.remote_json(layout.SIZE_REPORT_PATH)["near_limit"])


def jpeg(color=(200, 30, 30), exif=None, size=(640, 480)):
    from PIL import Image

    im = Image.new("RGB", size, color)
    out = io.BytesIO()
    if exif is not None:
        im.save(out, "JPEG", exif=exif)
    else:
        im.save(out, "JPEG")
    return out.getvalue()


class FakePicker:
    def __init__(self, pages, expire_after_downloads=None):
        self.pages = pages  # {page_token_or_None: (items, next)}
        self.blobs = {}
        self.downloads = 0
        self.expire_after = expire_after_downloads

    def add(
        self, item_id, data, created="2026-10-01T08:00:00Z", name=None, kind="PHOTO"
    ):
        self.blobs[item_id] = data
        return {
            "id": item_id,
            "createTime": created,
            "type": kind,
            "mediaFile": {
                "baseUrl": f"https://x/{item_id}",
                "mimeType": "image/jpeg",
                "filename": name or f"{item_id}.jpg",
            },
        }

    def page(self, session_id, page_token=None, page_size=10):
        return self.pages[page_token]

    def download(self, item):
        if self.expire_after is not None and self.downloads >= self.expire_after:
            raise picker_import.TokenExpired()
        self.downloads += 1
        return self.blobs[item["id"]]


class PickerImport(RepoCase):
    def test_imports_pages_dedupes_and_finishes(self):
        f = FakePicker({})
        a = f.add("a", jpeg((10, 10, 10)))
        b = f.add("b", jpeg((20, 20, 20)), created="2025-01-02T10:00:00Z")
        dup = f.add("c", f.blobs["a"])  # same bytes as a
        f.pages = {None: ([a, b], "p2"), "p2": ([dup], None)}
        status = picker_import.run(
            self.root, repo="me/photos", session_id="s1", client=f
        )
        self.assertEqual(status, "done")
        note = self.remote_json("depot/jobs/import-s1.json")
        self.assertEqual(
            (note["status"], note["imported"], note["skipped"]), ("done", 2, 1)
        )
        day = self.remote_json("depot/index/2026/10/01.json")
        (entry,) = day["entries"].values()
        v = entry["versions"][0]
        self.assertEqual(v["repo"], "me/photos")
        self.assertTrue(self.remote_has(v["path"]))
        self.assertTrue(self.remote_has(v["thumb_path"]))
        self.assertEqual(entry["tags"], {"source": "google_photos"})
        m = self.remote_json(layout.MANIFEST_PATH)
        self.assertEqual(set(m["shards"]), {"2026-10-01", "2025-01-02"})
        self.assertTrue(
            any(
                s.startswith("Import 2 items from Google Photos")
                for s in self.remote_log()
            )
        )

    def test_expired_token_stops_and_the_next_run_resumes(self):
        f = FakePicker({}, expire_after_downloads=2)
        p1 = [f.add("a", jpeg((1, 1, 1))), f.add("b", jpeg((2, 2, 2)))]
        p2 = [f.add("c", jpeg((3, 3, 3)))]
        f.pages = {None: (p1, "p2"), "p2": (p2, None)}
        self.assertEqual(
            picker_import.run(self.root, repo="me/photos", session_id="s", client=f),
            "needs_token",
        )
        note = self.remote_json("depot/jobs/import-s.json")
        self.assertEqual(
            (note["status"], note["page_token"], note["imported"]),
            ("needs_token", "p2", 2),
        )
        f.expire_after = None  # a fresh token
        self.assertEqual(
            picker_import.run(self.root, repo="me/photos", session_id="s", client=f),
            "done",
        )
        self.assertEqual(self.remote_json("depot/jobs/import-s.json")["imported"], 3)

    def test_full_repo_hands_over(self):
        f = FakePicker({})
        f.pages = {
            None: ([f.add("a", jpeg())], "p2"),
            "p2": ([f.add("b", jpeg((9, 9, 9)))], None),
        }
        status = picker_import.run(
            self.root,
            repo="me/photos",
            session_id="s",
            client=f,
            size_fn=lambda: 10**12,
            limit_bytes=10**9,
        )
        self.assertEqual(status, "repo_full")
        note = self.remote_json("depot/jobs/import-s.json")
        self.assertEqual((note["status"], note["page_token"]), ("repo_full", "p2"))

    def test_done_job_is_left_alone(self):
        jobs.write(self.root, "import-s", "picker_import", "done")
        self.assertEqual(
            picker_import.run(self.root, repo="r", session_id="s", client=None), "done"
        )


class PickerClientErrors(unittest.TestCase):
    def test_maps_google_errors(self):
        def expired(url, **kw):
            raise net.HttpError(401, "")

        with self.assertRaises(picker_import.TokenExpired):
            picker_import.PickerClient("t", fetch=expired).page("s")

        def not_ready(url, **kw):
            raise net.HttpError(400, '{"error":{"status":"FAILED_PRECONDITION"}}')

        with self.assertRaises(picker_import.PickerNotReady):
            picker_import.PickerClient("t", fetch=not_ready).page("s")

    def test_download_suffix(self):
        seen = []
        client = picker_import.PickerClient(
            "t", fetch=lambda url, **kw: seen.append(url) or b"x"
        )
        client.download({"type": "VIDEO", "mediaFile": {"baseUrl": "https://u/v"}})
        client.download({"type": "PHOTO", "mediaFile": {"baseUrl": "https://u/p"}})
        self.assertEqual(seen, ["https://u/v=dv", "https://u/p=d"])


def seed_entry(root, data, name="x.jpg", created=None, tags=None):
    sha = layout.sha256_bytes(data)
    rel = layout.object_path(sha, "jpg")
    gitops.write_file(root, rel, data)
    when = datetime(2026, 10, 12, tzinfo=timezone.utc)
    idx = RepoIndex(root)
    v = layout.version_json(1, sha, len(data), "me/photos", rel, when)
    e = layout.entry_json(
        layout.new_id(), name, "image/jpeg", created, when, [v], tags=tags
    )
    idx.put(layout.day_key(created), e)
    idx.write(when)
    return e["file_id"], sha


class ExifJob(RepoCase):
    def test_reads_details_and_dates_undated_photos(self):
        from PIL import Image

        exif = Image.Exif()
        exif.get_ifd(0x8769)[0x9003] = "2019:07:04 18:30:00"
        exif[0x010F], exif[0x0110] = "Acme", "Phone 9"
        gps = exif.get_ifd(0x8825)
        gps[1], gps[2] = "S", (26.0, 12.0, 0.0)
        gps[3], gps[4] = "E", (28.0, 3.0, 0.0)
        fid, sha = seed_entry(self.root, jpeg(exif=exif))
        plain_id, _ = seed_entry(
            self.root,
            jpeg((5, 5, 5)),
            created=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        self.commit_all(self.root, "seed")
        sh(self.root, "git", "push", "-q", "origin", "HEAD:main")

        done, status = exif_job.run(self.root)
        self.assertEqual((done, status), (2, "done"))
        moved = self.remote_json("depot/index/2019/07/04.json")["entries"][fid]
        self.assertEqual(moved["created_at"], "2019-07-04T18:30:00.000Z")
        self.assertEqual(moved["tags"]["camera"], "Phone 9")
        self.assertEqual(moved["tags"]["gps"], [-26.2, 28.05])
        self.assertNotIn(fid, self.remote_json("depot/index/undated.json")["entries"])
        meta = self.remote_json(layout.meta_path(sha))
        self.assertEqual(meta["camera"]["make"], "Acme")
        plain = self.remote_json("depot/index/2024/01/01.json")["entries"][plain_id]
        self.assertTrue(plain["tags"]["meta_extracted"])
        self.assertNotIn("gps", plain["tags"])
        # a second run finds nothing to do
        self.assertEqual(exif_job.run(self.root), (0, "done"))


class FakeEngine:
    def __init__(self, faces_by_sha):
        self.faces_by_sha = faces_by_sha

    def faces(self, data):
        return self.faces_by_sha.get(layout.sha256_bytes(data), [])


class PeopleJob(RepoCase):
    def test_registry_match_and_threshold(self):
        import numpy as np

        a = np.zeros(128, dtype="float32")
        a[0] = 1
        b = np.zeros(128, dtype="float32")
        b[1] = 1
        reg = people_job.Registry(
            {
                "threshold": 0.5,
                "people": {
                    "p_anna": {
                        "name": "Anna",
                        "embeddings": [people_job.encode_embedding(a)],
                    }
                },
            }
        )
        self.assertEqual(reg.match(a * 3)[0], "p_anna")  # scale does not matter
        pid, sim = reg.match(b)
        self.assertIsNone(pid)
        self.assertEqual(sim, 0.0)
        self.assertEqual(people_job.Registry().match(a), (None, None))

    def test_tags_people_and_writes_faces(self):
        import numpy as np

        anna = np.zeros(128, dtype="float32")
        anna[0] = 1
        stranger = np.zeros(128, dtype="float32")
        stranger[5] = 1
        registry = {
            "version": 1,
            "model": "sface_2021dec",
            "threshold": 0.363,
            "people": {
                "p_anna": {
                    "name": "Anna",
                    "embeddings": [people_job.encode_embedding(anna)],
                }
            },
        }
        gitops.write_file(
            self.root, people_job.REGISTRY_PATH, layout.encode_json(registry)
        )
        fid, sha = seed_entry(
            self.root,
            jpeg((7, 7, 7)),
            created=datetime(2026, 5, 5, tzinfo=timezone.utc),
        )
        self.commit_all(self.root, "seed")
        sh(self.root, "git", "push", "-q", "origin", "HEAD:main")

        engine = FakeEngine(
            {sha: [([10, 20, 30, 40], 0.98, anna), ([50, 60, 30, 40], 0.95, stranger)]}
        )
        self.assertEqual(people_job.run(self.root, engine=engine), (1, "done"))
        entry = self.remote_json("depot/index/2026/05/05.json")["entries"][fid]
        self.assertEqual(entry["tags"]["people"], ["p_anna"])
        self.assertEqual(entry["tags"]["face_count"], 2)
        faces = self.remote_json(layout.faces_path(sha))["faces"]
        self.assertEqual([f["person_id"] for f in faces], ["p_anna", None])
        back = people_job.decode_embedding(faces[0]["embedding"])
        self.assertAlmostEqual(float(back[0]), 1.0, places=5)
        self.assertEqual(people_job.run(self.root, engine=engine), (0, "done"))

    def test_model_pins_are_full_sha256(self):
        for url, sha in people_job.MODELS.values():
            self.assertRegex(sha, r"^[0-9a-f]{64}$")
            self.assertIn("47534e27c9851bb1128ccc0102f1145e27f23f98", url)


class EnrichBudget(RepoCase):
    def test_stops_at_max_items_and_reports_remaining(self):
        for i in range(3):
            seed_entry(
                self.root,
                jpeg((i, i, i)),
                created=datetime(2026, 1, i + 1, tzinfo=timezone.utc),
            )
        self.commit_all(self.root, "seed")
        sh(self.root, "git", "push", "-q", "origin", "HEAD:main")
        done, status = exif_job.run(self.root, chunk=1, max_items=2)
        self.assertEqual((done, status), (2, "running"))
        note = self.remote_json("depot/jobs/exif.json")
        self.assertEqual((note["status"], note["remaining"]), ("running", 1))
        self.assertEqual(exif_job.run(self.root), (1, "done"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

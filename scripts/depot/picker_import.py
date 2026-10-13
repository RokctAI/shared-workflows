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

"""Import photos the user picked in Google Photos straight into this repo.

Google removed full-library read access from the Photos Library API on
2025-03-31; apps now get exactly what the user selects in the Google Photos
Picker. The app runs the picker on the phone, then dispatches this job with
the picker session id and a short-lived Google token (scope
photospicker.mediaitems.readonly, about an hour). The job downloads straight
into the repo, so nothing passes through the phone.

Chunked and resumable through the job note `depot/jobs/<job>.json`:
- one commit per page: the objects, their thumbnails, the touched index
  shards, the manifest and the note (with the NEXT page token) together, so a
  stop at any point loses at most the page in flight, and re-running it is
  harmless because objects are content-addressed;
- stops with `needs_token` when Google rejects the token, `repo_full` when
  this repo nears its size limit (the app moves on to the next shard repo
  and hands the note over), `done` at the end, or `running` when the time
  budget is spent (the next run continues).
"""

import os
import shutil
import tempfile
import time
import urllib.parse

from . import gitops, jobs, layout, media, net
from .index import RepoIndex

KIND = "picker_import"
PICKER_API = "https://photospicker.googleapis.com/v1"
MAX_OBJECT_BYTES = 95 * 1024 * 1024  # git hosting refuses files over 100 MB
MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


class TokenExpired(Exception):
    pass


class PickerNotReady(Exception):
    pass


class PickerClient:
    """Google Photos Picker API: list the picked items, download their bytes."""

    def __init__(self, token, fetch=net.request, api=PICKER_API):
        self._headers = {"Authorization": f"Bearer {token}"}
        self._fetch = fetch
        self._api = api

    def _get(self, url, timeout=120):
        try:
            return self._fetch(url, headers=self._headers, timeout=timeout)
        except net.HttpError as e:
            if e.status in (401, 403):
                raise TokenExpired() from None
            if e.status == 400 and "FAILED_PRECONDITION" in e.body:
                raise PickerNotReady() from None
            raise

    def page(self, session_id, page_token=None, page_size=10):
        q = {"sessionId": session_id, "pageSize": page_size}
        if page_token:
            q["pageToken"] = page_token
        import json

        body = json.loads(
            self._get(f"{self._api}/mediaItems?{urllib.parse.urlencode(q)}", 60)
        )
        return body.get("mediaItems", []), body.get("nextPageToken")

    def download(self, item):
        media_file = item.get("mediaFile", {})
        suffix = "=dv" if item.get("type") == "VIDEO" else "=d"
        return self._get(media_file["baseUrl"] + suffix, timeout=600)


def _message(count, when):
    noun = "item" if count == 1 else "items"
    return f"Import {count} {noun} from Google Photos — {when.day} {MONTHS[when.month - 1]} {when.year}"


class _Page:
    """One page of picked items, downloaded into a temp dir, not yet committed."""

    def __init__(self, tmp):
        self.tmp = tmp
        self.items = []
        self.skipped = 0
        self.failed = 0

    def add(self, root, item, data):
        if len(data) > MAX_OBJECT_BYTES:
            self.failed += 1
            return
        media_file = item.get("mediaFile", {})
        name = media_file.get("filename") or item.get("id", "item")
        mime = media_file.get("mimeType") or "application/octet-stream"
        sha = layout.sha256_bytes(data)
        ext = layout.extension_of(name)
        obj = layout.object_path(sha, ext)
        if any(b["sha"] == sha for b in self.items) or gitops.object_exists(root, obj):
            self.skipped += 1
            return
        blob = os.path.join(self.tmp, sha)
        with open(blob, "wb") as f:
            f.write(data)
        thumb = media.thumbnail(data, mime, ext)
        if thumb:
            with open(blob + ".jpg", "wb") as f:
                f.write(thumb)
        self.items.append(
            {
                "sha": sha,
                "size": len(data),
                "name": name,
                "mime": mime,
                "obj": obj,
                "blob": blob,
                "thumb": bool(thumb),
                "created_at": layout.parse_iso(item.get("createTime")),
            }
        )

    def cleanup(self):
        for b in self.items:
            for p in (b["blob"], b["blob"] + ".jpg"):
                if os.path.exists(p):
                    os.remove(p)

    def write_into(self, root, idx, repo, when):
        """Copies the page's objects and thumbnails into the work tree and
        adds their index entries. Returns the repo paths written."""
        written = []
        for b in self.items:
            with open(b["blob"], "rb") as f:
                gitops.write_file(root, b["obj"], f.read())
            written.append(b["obj"])
            thumb_rel = None
            if b["thumb"]:
                thumb_rel = layout.thumb_path(b["sha"])
                with open(b["blob"] + ".jpg", "rb") as f:
                    gitops.write_file(root, thumb_rel, f.read())
                written.append(thumb_rel)
            version = layout.version_json(
                1, b["sha"], b["size"], repo, b["obj"], when, thumb=thumb_rel
            )
            entry = layout.entry_json(
                layout.new_id(),
                b["name"],
                b["mime"],
                b["created_at"],
                when,
                [version],
                tags={"source": "google_photos"},
            )
            idx.put(layout.day_key(b["created_at"]), entry)
        return written


class _Import:
    def __init__(self, root, repo, session_id, client, job):
        self.root, self.repo, self.session_id, self.client = (
            root,
            repo,
            session_id,
            client,
        )
        self.job = job or f"import-{session_id}"
        note = jobs.read(root, self.job) or {}
        self.done_before = note.get("status") == "done"
        self.page_token = note.get("page_token")
        self.counts = {
            k: int(note.get(k, 0)) for k in ("imported", "skipped", "failed")
        }

    def note(self, status, next_token, message=None, counts=None):
        fields = dict(
            session_id=self.session_id, page_token=next_token, **(counts or self.counts)
        )
        if message:
            fields["message"] = message
        return jobs.write(self.root, self.job, KIND, status, **fields)

    def finish(self, status, message=None):
        gitops.commit_batch(
            self.root,
            lambda: [self.note(status, self.page_token, message)],
            f"Google Photos import: {status}",
        )
        print(f"{self.job}: {status} {self.counts}")
        return status

    def commit_page(self, page, next_token):
        when = layout.now()

        def apply():
            idx = RepoIndex(self.root)
            written = page.write_into(self.root, idx, self.repo, when)
            written += idx.write(when)
            counts = dict(
                self.counts, imported=self.counts["imported"] + len(page.items)
            )
            written.append(
                self.note(
                    "done" if not next_token else "running", next_token, counts=counts
                )
            )
            return written

        gitops.commit_batch(self.root, apply, _message(len(page.items), when))
        self.counts["imported"] += len(page.items)
        self.page_token = next_token


def run(
    root,
    *,
    repo,
    session_id,
    client,
    job=None,
    max_minutes=50,
    limit_bytes=9 * 1024**3,
    size_fn=None,
    page_size=10,
    clock=time.monotonic,
):
    """Imports page after page until done, out of time, out of token or out of
    room. Returns the final status."""
    imp = _Import(root, repo, session_id, client, job)
    if imp.done_before:
        print(f"{imp.job}: already done")
        return "done"
    added = 0
    started = clock()
    tmp = tempfile.mkdtemp(prefix="depot-import-")
    try:
        while True:
            if clock() - started > max_minutes * 60:
                return imp.finish("running")
            try:
                items, next_token = client.page(session_id, imp.page_token, page_size)
                page = _Page(tmp)
                for item in items:
                    page.add(root, item, client.download(item))
            except TokenExpired:
                # Nothing of this page is committed: it is redone with the next
                # token, and content addressing skips whatever already landed.
                return imp.finish("needs_token")
            except PickerNotReady:
                return imp.finish("failed", "picker_not_finished")
            imp.counts["skipped"] += page.skipped
            imp.counts["failed"] += page.failed
            imp.commit_page(page, next_token)
            added += sum(b["size"] for b in page.items)
            page.cleanup()
            print(f"{imp.job}: page done {imp.counts}")
            if not next_token:
                print(f"{imp.job}: done")
                return "done"
            if size_fn is not None and size_fn() + added >= limit_bytes:
                return imp.finish("repo_full")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

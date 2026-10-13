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

"""Shared loop for jobs that enrich index entries one by one (EXIF, people).

A job is idempotent: it marks each finished entry with a tag, so whatever
stops a run (time budget, Actions minutes running out) leaves the rest for
the next run. Work happens in chunks: the slow part (reading the object and
analysing it) runs outside the commit, and each chunk is applied to a freshly
read index and committed, together with the job note.
"""

import time

from . import gitops, jobs, layout
from .index import RepoIndex


def run(
    root,
    *,
    job,
    kind,
    wants,
    analyse,
    apply_result,
    message,
    chunk=25,
    max_items=2000,
    max_minutes=50,
    clock=time.monotonic,
):
    """`wants(entry)` picks entries still to do; `analyse(entry, version)`
    returns a result (or None to skip for now); `apply_result(idx, day,
    entry, result)` edits the index and returns extra repo paths written.
    Returns (done_count, status)."""
    started = clock()
    todo = [
        (day, entry["file_id"])
        for day, entry in RepoIndex(root).entries()
        if wants(entry)
    ]
    total = len(todo)
    done = 0
    status = "running"
    pos = 0
    while pos < len(todo) and done < max_items:
        if clock() - started > max_minutes * 60:
            break
        chunk_ids = todo[pos : pos + chunk]
        pos += len(chunk_ids)

        idx = RepoIndex(root)
        results = []
        for day, file_id in chunk_ids:
            entry = idx.shard(day)["entries"].get(file_id)
            version = layout.current_version(entry) if entry else None
            if not version:
                continue
            result = analyse(entry, version)
            results.append((day, file_id, result))

        def apply():
            fresh = RepoIndex(root)
            paths = []
            for day, file_id, result in results:
                entry = fresh.shard(day)["entries"].get(file_id)
                if entry is None:  # moved or deleted meanwhile; next run sees it
                    continue
                paths += apply_result(fresh, day, entry, result) or []
            paths += fresh.write()
            left = max(total - done - len(results), 0)
            paths.append(
                jobs.write(
                    root,
                    job,
                    kind,
                    "done" if left == 0 else "running",
                    processed=done + len(results),
                    remaining=left,
                )
            )
            return paths

        gitops.commit_batch(root, apply, message(len(results)))
        done += len(results)
        print(f"{job}: {done}/{total}")

    if done >= total:
        status = "done"
    return done, status


def has_image(entry):
    return (entry.get("mime") or "").startswith("image/")

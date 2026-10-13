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

"""`depot/size.json`: how big this storage repo is (depot/CONTRACT.md).

The app reads it to decide when to create the next shard repo. The figure is
GitHub's own packed size of the repository, history included, which is the
number the ~10 GB guidance is about; it is read from the API, so this job
needs no checkout of the objects at all.
"""

from . import gitops, layout

DEFAULT_LIMIT = 9 * 1024**3


def report(size_bytes, limit_bytes=DEFAULT_LIMIT, when=None):
    return {
        "bytes": size_bytes,
        "limit_bytes": limit_bytes,
        "near_limit": size_bytes >= limit_bytes,
        "measured_at": layout.iso(when or layout.now()),
        "source": "github_api",
    }


def worth_writing(old, new, max_age_days=7):
    """Skip a commit when nothing meaningful moved: under 1% change, same
    near_limit flag, and the old report is less than a week old."""
    if not old:
        return True
    if old.get("near_limit") != new["near_limit"]:
        return True
    before = old.get("bytes") or 0
    if before == 0 or abs(new["bytes"] - before) / before >= 0.01:
        return True
    then = layout.parse_iso(old.get("measured_at"))
    now = layout.parse_iso(new["measured_at"])
    return then is None or (now - then).days >= max_age_days


def run(root, size_bytes, limit_bytes=DEFAULT_LIMIT):
    import json
    import os

    path = os.path.join(root, layout.SIZE_REPORT_PATH)
    old = None
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            old = json.load(f)
    new = report(size_bytes, limit_bytes)
    if not worth_writing(old, new):
        print(f"size unchanged ({size_bytes} bytes); nothing to commit")
        return None

    def apply():
        gitops.write_file(root, layout.SIZE_REPORT_PATH, layout.encode_json(new))
        return [layout.SIZE_REPORT_PATH]

    sha = gitops.commit_batch(root, apply, "Update storage size report")
    print(f"size {size_bytes} bytes, near_limit={new['near_limit']}, commit={sha}")
    return sha

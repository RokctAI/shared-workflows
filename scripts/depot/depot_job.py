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

"""Entry point for the universal-depot-*.yml workflows.

Run as a module from scripts/:  python3 -m depot.depot_job <command> ...

  depot_job.py size   --root DIR [--limit-gb 9]
  depot_job.py import --root DIR --session ID [--job NAME] [--max-minutes 50]
                      (Google token in env DEPOT_GOOGLE_TOKEN, never an arg)
  depot_job.py exif   --root DIR [--max-items N] [--max-minutes M]
  depot_job.py people --root DIR [--max-items N] [--max-minutes M]

Exit status is 0 for every orderly stop (done, running, repo_full,
needs_token): those are states the app acts on through the job note, not
failures of the run.
"""

import argparse
import os
import sys

from . import exif_job, net, people_job, picker_import, size_report

GB = 1024**3


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("size", "import", "exif", "people"):
        s = sub.add_parser(name)
        s.add_argument("--root", default=".")
        s.add_argument("--limit-gb", type=float, default=9.0)
        s.add_argument("--max-minutes", type=float, default=50)
        s.add_argument("--max-items", type=int, default=2000)
        if name == "import":
            s.add_argument("--session", required=True)
            s.add_argument("--job")
    a = p.parse_args(argv)
    root = os.path.abspath(a.root)
    limit = int(a.limit_gb * GB)
    repo = os.environ.get("GITHUB_REPOSITORY", "")

    if a.cmd == "size":
        size_report.run(root, net.github_repo_size_bytes(), limit)
    elif a.cmd == "import":
        token = os.environ.get("DEPOT_GOOGLE_TOKEN", "").strip()
        if not token:
            print("DEPOT_GOOGLE_TOKEN is empty", file=sys.stderr)
            return 2
        status = picker_import.run(
            root,
            repo=repo,
            session_id=a.session,
            job=a.job,
            client=picker_import.PickerClient(token),
            max_minutes=a.max_minutes,
            limit_bytes=limit,
            size_fn=net.github_repo_size_bytes,
        )
        print(f"import status: {status}")
    elif a.cmd == "exif":
        exif_job.run(root, max_items=a.max_items, max_minutes=a.max_minutes)
    elif a.cmd == "people":
        people_job.run(root, max_items=a.max_items, max_minutes=a.max_minutes)
    return 0


if __name__ == "__main__":
    sys.exit(main())

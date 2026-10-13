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

"""Job notes: `depot/jobs/<job>.json` (depot/CONTRACT.md).

A repo-side job writes its progress here every chunk, so a run that stops
(time budget, token expiry, full repo, Actions minutes running out) loses
nothing and the next run, or the app, picks up from the note.

Statuses the app understands:
  running         a chunk is in progress or the next one is due
  done            nothing left to do
  repo_full       this repo is near its size limit; the app creates the next
                  shard repo and restarts the job there
  needs_token     the short-lived Google token expired; the app re-dispatches
                  the job with a fresh one the next time it is opened
  failed          see `message`
"""

import json
import os

from . import layout

STATUSES = ("running", "done", "repo_full", "needs_token", "failed")


def note_path(job):
    return f"{layout.JOBS_DIR}/{job}.json"


def read(root, job):
    path = os.path.join(root, note_path(job))
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write(root, job, kind, status, **fields):
    if status not in STATUSES:
        raise ValueError(status)
    note = read(root, job) or {"job": job, "kind": kind}
    note.update(fields)
    note["status"] = status
    note["updated_at"] = layout.iso(layout.now())
    path = os.path.join(root, note_path(job))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(layout.encode_json(note))
    return note_path(job)

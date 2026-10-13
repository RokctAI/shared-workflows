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

"""Git plumbing for depot jobs, inside the checkout of the repo they run in.

The workflows check the user's repo out sparse (index, jobs, people) and
blobless (`filter: blob:none`), so a 9 GB repo is never downloaded: objects
are fetched one at a time on demand (`read_blob`) and new ones are written
outside the sparse cone and added with `git add --sparse`.

`commit_batch` never merges. The phone commits through the GitHub API at the
same time, so a push can be rejected; the batch is then re-applied from
scratch on top of the fresh remote head (re-reading the shards it edits) and
pushed again.
"""

import os
import subprocess

BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"


class GitError(RuntimeError):
    pass


def git(root, *args, check=True, binary=False):
    proc = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=not binary,
    )
    if check and proc.returncode != 0:
        err = proc.stderr if not binary else proc.stderr.decode(errors="replace")
        raise GitError(f"git {' '.join(args)}: {err.strip()}")
    return proc


def branch(root):
    return git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


def object_exists(root, rel, ref="HEAD"):
    return git(root, "cat-file", "-e", f"{ref}:{rel}", check=False).returncode == 0


def read_blob(root, rel, ref="HEAD"):
    return git(root, "cat-file", "blob", f"{ref}:{rel}", binary=True).stdout


def write_file(root, rel, data):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def commit_batch(root, apply_fn, message, attempts=4):
    """Resets to the remote head, runs `apply_fn()` (which writes files and
    returns the repo paths it wrote), commits them and pushes. Retries from a
    fresh head when the push is rejected. Returns the commit sha, or None
    when `apply_fn` changed nothing."""
    name = branch(root)
    for attempt in range(1, attempts + 1):
        git(root, "fetch", "-q", "--depth=1", "origin", name)
        git(root, "reset", "-q", "--hard", "FETCH_HEAD")
        paths = apply_fn()
        if not paths:
            return None
        git(root, "add", "--sparse", "--", *paths)
        if git(root, "diff", "--cached", "--quiet", check=False).returncode == 0:
            return None
        git(
            root,
            "-c",
            f"user.name={BOT_NAME}",
            "-c",
            f"user.email={BOT_EMAIL}",
            "commit",
            "-q",
            "-m",
            message,
        )
        pushed = git(root, "push", "-q", "origin", f"HEAD:{name}", check=False)
        if pushed.returncode == 0:
            return git(root, "rev-parse", "HEAD").stdout.strip()
        if attempt == attempts:
            raise GitError(f"push rejected {attempts} times: {pushed.stderr.strip()}")
    return None

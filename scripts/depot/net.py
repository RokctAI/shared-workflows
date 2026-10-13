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

"""Small HTTP helpers on the standard library (no extra install on runners)."""

import json
import os
import time
import urllib.error
import urllib.request


class HttpError(RuntimeError):
    def __init__(self, status, body=""):
        super().__init__(f"HTTP {status}: {body[:300]}")
        self.status = status
        self.body = body


def request(url, headers=None, timeout=120, data=None, method=None, retries=2):
    """Returns the response bytes. Retries 429/5xx and connection errors with
    a short backoff; raises HttpError for any other non-2xx status."""
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            url, headers=headers or {}, data=data, method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                return res.read()
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(2**attempt * 2)
                continue
            raise HttpError(e.code, body) from None
        except (urllib.error.URLError, TimeoutError):
            if attempt < retries:
                time.sleep(2**attempt * 2)
                continue
            raise


def get_json(url, headers=None, timeout=60):
    return json.loads(request(url, headers=headers, timeout=timeout))


def github_repo_size_bytes(repo=None, token=None, api=None):
    """GitHub's own measure of the repo's packed size (`size`, in KB),
    including history. Needs only the run's GITHUB_TOKEN."""
    repo = repo or os.environ["GITHUB_REPOSITORY"]
    token = token or os.environ.get("GITHUB_TOKEN", "")
    api = api or os.environ.get("GITHUB_API_URL", "https://api.github.com")
    data = get_json(
        f"{api}/repos/{repo}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    return int(data.get("size", 0)) * 1024

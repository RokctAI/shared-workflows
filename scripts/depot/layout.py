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

"""Paths, ids and JSON shapes of the depot repo layout (layout_version 1).

Mirrors depot_sdk's DepotLayout and depot_models.dart byte for byte: the app
and these jobs write the same files, so a key name or path rule changed here
and not there (or the other way round) corrupts users' indexes. The contract
is depot/CONTRACT.md in RokctAI/hardware.
"""

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

LAYOUT_VERSION = 1
ROOT = "depot"
MANIFEST_PATH = f"{ROOT}/manifest.json"
SIZE_REPORT_PATH = f"{ROOT}/size.json"
JOBS_DIR = f"{ROOT}/jobs"
INDEX_DIR = f"{ROOT}/index"
PEOPLE_DIR = f"{ROOT}/people"
UNDATED = "undated"

_EXT_RE = re.compile(r"^[a-z0-9]{1,10}$")


def _fanout(sha256):
    return sha256[:2]


def object_path(sha256, ext):
    suffix = f".{ext}" if ext else ""
    return f"{ROOT}/objects/{_fanout(sha256)}/{sha256}{suffix}"


def thumb_path(sha256):
    return f"{ROOT}/thumbs/{_fanout(sha256)}/{sha256}.jpg"


def meta_path(sha256):
    return f"{ROOT}/meta/{_fanout(sha256)}/{sha256}.json"


def faces_path(sha256):
    return f"{PEOPLE_DIR}/faces/{_fanout(sha256)}/{sha256}.json"


def day_key(created_at):
    """UTC creation day `YYYY-MM-DD`, or `undated`."""
    if created_at is None:
        return UNDATED
    d = created_at.astimezone(timezone.utc)
    return f"{d.year:04d}-{d.month:02d}-{d.day:02d}"


def shard_path(day):
    if day == UNDATED:
        return f"{INDEX_DIR}/undated.json"
    y, m, d = day.split("-")
    return f"{INDEX_DIR}/{y}/{m}/{d}.json"


def extension_of(name):
    dot = name.rfind(".")
    if dot <= 0 or dot == len(name) - 1:
        return ""
    ext = name[dot + 1 :].lower()
    return ext if _EXT_RE.match(ext) else ""


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """Dart's DateTime.toUtc().toIso8601String() for millisecond values."""
    d = dt.astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def parse_iso(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
            timezone.utc
        )
    except ValueError:
        return None


def now():
    return datetime.now(timezone.utc)


def encode_json(value):
    """Dart's JsonEncoder.withIndent('  ') plus a trailing newline."""
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def version_json(
    version, sha256, size, repo, path, created_at, thumb=None, commit_sha=None
):
    return {
        "version": version,
        "sha256": sha256,
        "size": size,
        "repo": repo,
        "path": path,
        "thumb_path": thumb,
        "commit_sha": commit_sha,
        "created_at": iso(created_at),
    }


def entry_json(
    file_id,
    name,
    mime,
    created_at,
    modified_at,
    versions,
    folder_id=None,
    deleted_at=None,
    current=None,
    tags=None,
):
    return {
        "file_id": file_id,
        "name": name,
        "mime": mime,
        "folder_id": folder_id,
        "created_at": iso(created_at) if created_at else None,
        "modified_at": iso(modified_at),
        "deleted_at": iso(deleted_at) if deleted_at else None,
        "current": current if current is not None else len(versions),
        "versions": versions,
        "tags": tags or {},
    }


def current_version(entry):
    for v in entry.get("versions", []):
        if v.get("version") == entry.get("current"):
            return v
    versions = entry.get("versions") or []
    return versions[-1] if versions else None

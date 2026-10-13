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

"""Read and update the index of ONE depot repo inside a working tree.

Each shard repo keeps its own index (depot/CONTRACT.md, "the app carries
everything between repos"), so a job only ever edits the repo it runs in.
"""

import json
import os

from . import layout


class RepoIndex:
    """The manifest plus the index shards a job touched, held in memory and
    written back in one go by `write()`."""

    def __init__(self, root):
        self.root = root
        self.manifest = self._read(layout.MANIFEST_PATH)
        if self.manifest is None:
            raise FileNotFoundError(
                f"{layout.MANIFEST_PATH} missing: not a depot repo "
                "(the app writes it when the repo is connected)"
            )
        if self.manifest.get("layout_version", 1) > layout.LAYOUT_VERSION:
            raise RuntimeError("layout_too_new")
        self._shards = {}
        self._dirty = set()

    def _abs(self, rel):
        return os.path.join(self.root, rel)

    def _read(self, rel):
        path = self._abs(rel)
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def _write(self, rel, value):
        path = self._abs(rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(layout.encode_json(value))

    def days(self):
        """Every shard day the manifest lists, oldest first."""
        return sorted(self.manifest.get("shards", {}).keys())

    def shard(self, day):
        if day not in self._shards:
            doc = self._read(layout.shard_path(day))
            self._shards[day] = doc or {
                "layout_version": layout.LAYOUT_VERSION,
                "day": day,
                "entries": {},
            }
        return self._shards[day]

    def entries(self):
        """(day, entry) for every live entry, shard by shard."""
        for day in self.days():
            for entry in list(self.shard(day)["entries"].values()):
                if not entry.get("deleted_at"):
                    yield day, entry

    def put(self, day, entry):
        self.shard(day)["entries"][entry["file_id"]] = entry
        self._dirty.add(day)

    def move(self, entry, from_day, to_day):
        if from_day == to_day:
            self.put(to_day, entry)
            return
        self.shard(from_day)["entries"].pop(entry["file_id"], None)
        self._dirty.add(from_day)
        self.put(to_day, entry)

    def write(self, when=None):
        """Writes every touched shard and the manifest. Returns the paths."""
        when = when or layout.now()
        written = []
        shards = dict(self.manifest.get("shards", {}))
        for day in sorted(self._dirty):
            doc = self.shard(day)
            rel = layout.shard_path(day)
            self._write(rel, doc)
            written.append(rel)
            shards[day] = {
                "path": rel,
                "count": len(doc["entries"]),
                "updated_at": layout.iso(when),
            }
        if written:
            self.manifest["shards"] = shards
            self.manifest["updated_at"] = layout.iso(when)
            self._write(layout.MANIFEST_PATH, self.manifest)
            written.append(layout.MANIFEST_PATH)
        self._dirty.clear()
        return written

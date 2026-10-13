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

"""Photo metadata job: date taken, GPS and camera from each photo's EXIF.

Writes the full detail to `depot/meta/<aa>/<sha256>.json` and the values an
app filters on into the entry's tags (typed keys, never a blob: SDK_ECOSYSTEM
invariant 10): `gps` [lat, lon], `camera`, `meta_extracted` true. A photo
whose index entry had no date but whose EXIF does is moved from the
`undated` shard to its day.
"""

from . import enrich, gitops, layout, media

JOB = "exif"


def wants(entry):
    return enrich.has_image(entry) and not entry.get("tags", {}).get("meta_extracted")


def make_analyse(root):
    def analyse(entry, version):
        data = gitops.read_blob(root, version["path"])
        return media.exif_metadata(data)

    return analyse


def make_apply(root):
    def apply_result(idx, day, entry, meta):
        sha = layout.current_version(entry)["sha256"]
        doc = {"sha256": sha}
        for key in ("width", "height", "camera", "gps"):
            if meta.get(key) is not None:
                doc[key] = meta[key]
        if meta.get("taken_at"):
            doc["taken_at"] = layout.iso(meta["taken_at"])
        rel = layout.meta_path(sha)
        gitops.write_file(root, rel, layout.encode_json(doc))

        tags = dict(entry.get("tags") or {})
        tags["meta_extracted"] = True
        if meta.get("gps"):
            tags["gps"] = [meta["gps"]["lat"], meta["gps"]["lon"]]
        if meta.get("camera") and meta["camera"].get("model"):
            tags["camera"] = meta["camera"]["model"]
        entry["tags"] = tags

        target = day
        if entry.get("created_at") is None and meta.get("taken_at"):
            entry["created_at"] = layout.iso(meta["taken_at"])
            target = layout.day_key(meta["taken_at"])
        idx.move(entry, day, target)
        return [rel]

    return apply_result


def run(root, **kw):
    return enrich.run(
        root,
        job=JOB,
        kind="exif",
        wants=wants,
        analyse=make_analyse(root),
        apply_result=make_apply(root),
        message=lambda n: f"Read photo details for {n} photo{'s' if n != 1 else ''}",
        **kw,
    )

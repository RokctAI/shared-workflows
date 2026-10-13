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

"""Thumbnails and photo metadata (EXIF) for depot jobs.

Pillow does images; ffmpeg (preinstalled on GitHub's ubuntu runners) grabs a
poster frame for videos. Both degrade to "no thumbnail" rather than failing a
job: a missing thumbnail only costs the app a placeholder tile.
"""

import io
import os
import subprocess
import tempfile
from datetime import datetime, timezone

THUMB_MAX = 320
THUMB_QUALITY = 80


def _pillow():
    from PIL import Image, ImageOps  # imported lazily: only media jobs need it

    return Image, ImageOps


def image_thumbnail(data):
    """JPEG bytes no larger than THUMB_MAX on either side, upright per EXIF."""
    Image, ImageOps = _pillow()
    try:
        with Image.open(io.BytesIO(data)) as im:
            im = ImageOps.exif_transpose(im)
            im.thumbnail((THUMB_MAX, THUMB_MAX))
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            out = io.BytesIO()
            im.save(out, "JPEG", quality=THUMB_QUALITY, optimize=True)
            return out.getvalue()
    except Exception:
        return None


def video_thumbnail(data, ext="mp4"):
    """Poster frame one second in (or the first frame) as a JPEG."""
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, f"in.{ext or 'mp4'}")
        dst = os.path.join(tmp, "out.jpg")
        with open(src, "wb") as f:
            f.write(data)
        for seek in ("1", "0"):
            proc = subprocess.run(
                [
                    "ffmpeg",
                    "-loglevel",
                    "error",
                    "-y",
                    "-ss",
                    seek,
                    "-i",
                    src,
                    "-frames:v",
                    "1",
                    "-vf",
                    f"scale={THUMB_MAX}:-2",
                    dst,
                ],
                capture_output=True,
            )
            if proc.returncode == 0 and os.path.exists(dst):
                with open(dst, "rb") as f:
                    return f.read()
    return None


def thumbnail(data, mime, ext=""):
    if mime.startswith("image/"):
        return image_thumbnail(data)
    if mime.startswith("video/"):
        try:
            return video_thumbnail(data, ext)
        except FileNotFoundError:  # no ffmpeg
            return None
    return None


def _ratio(v):
    try:
        return float(v)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _dms(values, ref):
    try:
        d, m, s = (_ratio(x) for x in values)
        deg = d + m / 60 + s / 3600
    except (TypeError, ValueError):
        return None
    return -deg if ref in ("S", "W") else deg


def exif_metadata(data):
    """Date taken, GPS, camera and pixel size from an image, as plain JSON.
    Missing pieces are simply absent; an unreadable file gives {}."""
    Image, _ = _pillow()
    try:
        with Image.open(io.BytesIO(data)) as im:
            meta = {"width": im.width, "height": im.height}
            exif = im.getexif()
    except Exception:
        return {}
    if not exif:
        return meta
    base = dict(exif)
    sub = dict(exif.get_ifd(0x8769))  # Exif IFD: DateTimeOriginal lives here
    gps = dict(exif.get_ifd(0x8825))

    taken = sub.get(0x9003) or base.get(0x0132)  # DateTimeOriginal / DateTime
    if isinstance(taken, str):
        try:
            # EXIF carries no zone; keep the wall-clock time, marked UTC, which
            # is what the app's day buckets use for dated items too.
            meta["taken_at"] = datetime.strptime(
                taken.strip(), "%Y:%m:%d %H:%M:%S"
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    make, model = base.get(0x010F), base.get(0x0110)
    if make or model:
        meta["camera"] = {
            "make": str(make).strip() if make else None,
            "model": str(model).strip() if model else None,
        }

    if 2 in gps and 4 in gps:
        lat = _dms(gps[2], gps.get(1))
        lon = _dms(gps[4], gps.get(3))
        if lat is not None and lon is not None and (lat, lon) != (0.0, 0.0):
            meta["gps"] = {"lat": round(lat, 6), "lon": round(lon, 6)}
            if 6 in gps and _ratio(gps[6]) is not None:
                meta["gps"]["alt"] = round(_ratio(gps[6]), 1)
    return meta

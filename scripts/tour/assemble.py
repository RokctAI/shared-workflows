#!/usr/bin/env python3
# Copyright (c) 2026 RokctAI
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
"""Assemble guided-tour outputs from the resolved tour plan + captured stills.

Two independent products (so a video hiccup can never block the stills):

  --guide  (required output)  copies the captured screenshots to
           <out>/screenshots/NN-key.png and writes <out>/feature-guide.md
           embedding each still with its caption.

  --video  (best-effort)      renders <out>/tour.mp4 in the org's vertical
           house style: 1080x1920 9:16, 30fps, hook-style title card first,
           then one captioned still per step with a gentle ~6% zoom.
           Captions are burned in with Pillow (DejaVu Sans Bold); ffmpeg
           only encodes a concatenated-JPEG frame stream, so no ffmpeg
           filters or pipe protocols are needed. Codec/container are
           parametrized; CI uses libx264 + mp4 + faststart.

Branding (app name, tagline, hook) comes exclusively from the app shell's
resolved tour plan — SDK fragments stay brand-neutral.
"""

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

WIDTH, HEIGHT = 1080, 1920
ZOOM = 0.06  # gentle zoom across each still
FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
)


def log(msg):
    print(f"[tour-assemble] {msg}", flush=True)


def warn(msg):
    prefix = "::warning::" if os.environ.get("GITHUB_ACTIONS") else "[tour-assemble][warn] "
    print(f"{prefix}{msg}", flush=True)


def fail(msg):
    prefix = "::error::" if os.environ.get("GITHUB_ACTIONS") else "[tour-assemble][error] "
    print(f"{prefix}{msg}", flush=True)
    sys.exit(1)


def find_shots(shots_dir, steps):
    """Map step key -> captured PNG path, tolerating missing steps."""
    by_key = {}
    for path in glob.glob(os.path.join(shots_dir, "*.png")):
        stem = os.path.splitext(os.path.basename(path))[0]
        key = stem.split("-", 1)[1] if "-" in stem else stem
        by_key[key] = path
    found = {}
    for step in steps:
        if step["key"] in by_key:
            found[step["key"]] = by_key[step["key"]]
        else:
            warn(f"no screenshot captured for step '{step['key']}' — it is skipped")
    return found


def write_guide(resolved, shots, out_dir):
    app = resolved["app"]
    steps = resolved["steps"]
    shots_out = os.path.join(out_dir, "screenshots")
    os.makedirs(shots_out, exist_ok=True)

    # Refresh the published stills wholesale so removed steps do not linger.
    for stale in glob.glob(os.path.join(shots_out, "*.png")):
        os.remove(stale)

    lines = [f"# {app['name']} — Feature Guide", ""]
    if app.get("tagline"):
        lines += [f"_{app['tagline']}_", ""]
    lines += [
        "> This guide is generated automatically on every merge: CI builds the",
        "> app with its built-in demo dataset, walks the guided tour on an",
        "> Android emulator, and captures each screen below. Content shown is",
        "> demo data.",
        "",
    ]

    number = 0
    embedded = 0
    for step in steps:
        src = shots.get(step["key"])
        if not src:
            continue
        number += 1
        name = f"{number:02d}-{step['key']}.png"
        shutil.copyfile(src, os.path.join(shots_out, name))
        lines.append(f"## {number}. {step['title']}")
        lines.append("")
        lines.append(f"![{step['title']}](screenshots/{name})")
        lines.append("")
        if step.get("caption"):
            lines.append(step["caption"])
            lines.append("")
        embedded += 1

    if not embedded:
        fail("guide: no screenshots matched any tour step — nothing to publish")

    guide_path = os.path.join(out_dir, "feature-guide.md")
    with open(guide_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines).rstrip() + "\n")
    log(f"wrote {guide_path} ({embedded} steps)")
    return embedded


# --- video -------------------------------------------------------------------


def load_font(size, font_path=""):
    from PIL import ImageFont

    candidates = ([font_path] if font_path else []) + list(FONT_CANDIDATES)
    for path in candidates:
        if path and os.path.exists(path):
            return ImageFont.truetype(path, size)
    warn("DejaVu Sans Bold not found — falling back to Pillow default font")
    return ImageFont.load_default(size=size)


def wrap_text(draw, text, font, max_width):
    words = text.split()
    lines, current = [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def cover_resize(img):
    """Scale-to-cover + centre-crop to 1080x1920."""
    from PIL import Image

    scale = max(WIDTH / img.width, HEIGHT / img.height)
    resized = img.resize(
        (max(WIDTH, round(img.width * scale)), max(HEIGHT, round(img.height * scale))),
        Image.LANCZOS,
    )
    left = (resized.width - WIDTH) // 2
    top = (resized.height - HEIGHT) // 2
    return resized.crop((left, top, left + WIDTH, top + HEIGHT))


def caption_overlay(text, font_path=""):
    """Static bottom caption band, rendered once per step (RGBA)."""
    from PIL import Image, ImageDraw

    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    if not text:
        return overlay
    draw = ImageDraw.Draw(overlay)
    font = load_font(54, font_path)
    margin, pad = 56, 40
    max_text_width = WIDTH - 2 * (margin + pad)
    lines = wrap_text(draw, text, font, max_text_width)
    line_height = 68
    band_height = 2 * pad + line_height * len(lines)
    top = HEIGHT - 220 - band_height
    draw.rounded_rectangle(
        (margin, top, WIDTH - margin, top + band_height),
        radius=28,
        fill=(12, 14, 20, 210),
    )
    y = top + pad
    for line in lines:
        w = draw.textlength(line, font=font)
        draw.text(((WIDTH - w) / 2, y), line, font=font, fill=(255, 255, 255, 255))
        y += line_height
    return overlay


def hook_card(app, hook, font_path=""):
    from PIL import Image, ImageDraw

    card = Image.new("RGB", (WIDTH, HEIGHT), (12, 14, 20))
    draw = ImageDraw.Draw(card)
    hook_font = load_font(96, font_path)
    name_font = load_font(64, font_path)
    tag_font = load_font(42, font_path)

    lines = wrap_text(draw, hook, hook_font, WIDTH - 200)
    line_height = 118
    y = HEIGHT // 2 - (line_height * len(lines)) // 2 - 140
    for line in lines:
        w = draw.textlength(line, font=hook_font)
        draw.text(((WIDTH - w) / 2, y), line, font=hook_font, fill=(255, 255, 255))
        y += line_height

    y += 90
    name = app.get("name", "")
    w = draw.textlength(name, font=name_font)
    draw.text(((WIDTH - w) / 2, y), name, font=name_font, fill=(120, 200, 255))
    if app.get("tagline"):
        y += 96
        w = draw.textlength(app["tagline"], font=tag_font)
        draw.text(((WIDTH - w) / 2, y), app["tagline"], font=tag_font, fill=(200, 205, 215))
    return card


def zoomed_frame(base, progress):
    """base cover-sized RGB image, progress 0..1 -> zoomed 1080x1920 frame."""
    from PIL import Image

    z = 1.0 + ZOOM * progress
    crop_w, crop_h = WIDTH / z, HEIGHT / z
    left = (WIDTH - crop_w) / 2
    top = (HEIGHT - crop_h) / 2
    return base.crop(
        (round(left), round(top), round(left + crop_w), round(top + crop_h))
    ).resize((WIDTH, HEIGHT), Image.BILINEAR)


def write_video(resolved, shots, out_dir, ffmpeg, codec, container, fps, font_path):
    from PIL import Image

    app = resolved["app"]
    video_cfg = resolved.get("video", {})
    steps = [s for s in resolved["steps"] if s["key"] in shots]
    if not steps:
        fail("video: no captured screenshots to render")

    hook_seconds = 3.0
    per_step = float(video_cfg.get("seconds_per_step") or 3.0)
    # Keep total inside the 20-45s house window (min 2s per still).
    per_step = max(2.0, min(per_step, (45.0 - hook_seconds) / len(steps)))
    total = hook_seconds + per_step * len(steps)
    log(
        f"video plan: hook {hook_seconds:.0f}s + {len(steps)} stills x {per_step:.1f}s "
        f"= {total:.1f}s at {fps}fps ({codec}/{container})"
    )

    out_path = os.path.join(out_dir, f"tour.{container}")

    # All zoom + caption work happens in Pillow; ffmpeg only encodes a
    # concatenated-JPEG stream read from ONE file with the image2pipe
    # demuxer. This needs no ffmpeg filters and no pipe/fd protocols, so it
    # works identically on CI's full apt ffmpeg and on trimmed local builds
    # (Playwright's build ships only the `file` protocol and only the
    # image2pipe + matroska demuxers).
    frames_dir = tempfile.mkdtemp(prefix="tour_frames_")
    stream_path = os.path.join(frames_dir, "frames.mjpeg")
    stream = open(stream_path, "wb")
    frames_written = 0

    def push(image):
        nonlocal frames_written
        frames_written += 1
        image.save(stream, format="JPEG", quality=92)

    try:
        card = hook_card(app, video_cfg.get("hook", ""), font_path)
        for _ in range(int(round(hook_seconds * fps))):
            push(card)

        step_frames = int(round(per_step * fps))
        for step in steps:
            with Image.open(shots[step["key"]]) as raw:
                base = cover_resize(raw.convert("RGB"))
            overlay = caption_overlay(step.get("caption") or step.get("title") or "", font_path)
            for i in range(step_frames):
                progress = i / max(1, step_frames - 1)
                frame = zoomed_frame(base, progress).convert("RGBA")
                frame.alpha_composite(overlay)
                push(frame.convert("RGB"))

        stream.close()
        cmd = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "image2pipe", "-framerate", str(fps),
            # Input codec must be explicit: trimmed builds do not probe the
            # JPEG stream ("Video: none ... no decoder found for: none").
            "-c:v", "mjpeg",
            "-i", stream_path,
            "-an",
            "-r", str(fps),
            "-c:v", codec,
        ]
        if codec == "libx264":
            cmd += ["-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p"]
        elif codec in ("libvpx", "libvpx-vp9"):
            cmd += ["-b:v", "2M"]
        if container == "mp4":
            cmd += ["-movflags", "+faststart"]
        cmd.append(out_path)
        result = subprocess.run(cmd)
        if result.returncode != 0:
            fail(f"ffmpeg exited {result.returncode}")
    finally:
        if not stream.closed:
            stream.close()
        shutil.rmtree(frames_dir, ignore_errors=True)
    size = os.path.getsize(out_path)
    log(
        f"wrote {out_path}: {frames_written} frames, "
        f"{frames_written / fps:.1f}s, {size / 1_000_000:.2f} MB"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolved", default="tour.resolved.json")
    parser.add_argument("--shots", default="tour_screenshots")
    parser.add_argument("--out", default="marketing/tour")
    parser.add_argument("--guide", action="store_true")
    parser.add_argument("--video", action="store_true")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--codec", default="libx264")
    parser.add_argument("--container", default="mp4")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--font", default="")
    args = parser.parse_args()

    if not (args.guide or args.video):
        fail("nothing to do: pass --guide and/or --video")
    if not os.path.exists(args.resolved):
        fail(f"resolved tour plan not found: {args.resolved}")
    with open(args.resolved, "r", encoding="utf-8") as f:
        resolved = json.load(f)

    os.makedirs(args.out, exist_ok=True)
    shots = find_shots(args.shots, resolved["steps"])
    if not shots:
        fail(f"no captured screenshots found in {args.shots}")

    if args.guide:
        write_guide(resolved, shots, args.out)
    if args.video:
        write_video(
            resolved, shots, args.out,
            args.ffmpeg, args.codec, args.container, args.fps, args.font,
        )


if __name__ == "__main__":
    main()

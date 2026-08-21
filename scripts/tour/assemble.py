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
           house style: 1080x1920 9:16, 30fps, a ~3s hook card first (brand
           background, hook line, app name — only when the manifest supplies
           a hook), then one captioned still per step with a gentle ~6% zoom,
           then a ~3s end card (logo + app name + offer line — only when the
           manifest supplies an offer or a logo). Each caption may carry one
           key phrase highlighted in the brand accent colour. Captions are
           burned in with Pillow (DejaVu Sans Bold); ffmpeg only encodes a
           concatenated-JPEG frame stream, so no ffmpeg filters or pipe
           protocols are needed. Codec/container are parametrized; CI uses
           libx264 + mp4 + faststart.

Branding (app name, tagline, hook, colours, offer, logo) comes exclusively
from the app shell's resolved tour plan — SDK fragments stay brand-neutral.

--require-varied makes the run fail loudly when every captured screenshot
is byte-identical (a sure sign the capture regressed to placeholder
frames); without the flag that situation only warns.
"""

import argparse
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap

WIDTH, HEIGHT = 1080, 1920
ZOOM = 0.06  # gentle zoom across each still
CARD_SECONDS = 3.0  # hook card and end card each hold for ~3s
CARD_BG = (12, 14, 20)  # card background when the manifest has no brand colour
ACCENT = (120, 200, 255)  # accent when the manifest has no accent colour
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


def shots_all_identical(shots):
    """True when 2+ screenshots were captured and every one is byte-identical.

    That situation almost certainly means the capture regressed to
    placeholder frames, so the video and guide would show the same still
    over and over.
    """
    if len(shots) < 2:
        return False
    digests = set()
    for path in shots.values():
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        digests.add(h.hexdigest())
    return len(digests) == 1


def write_guide(resolved, shots, out_dir):
    app = resolved["app"]
    steps = resolved["steps"]
    shots_out = os.path.join(out_dir, "screenshots")
    os.makedirs(shots_out, exist_ok=True)

    # Refresh the published stills wholesale so removed steps do not linger.
    for stale in glob.glob(os.path.join(shots_out, "*.png")):
        os.remove(stale)

    # The fleet markdown linter enforces MD013 (80-column lines) and MD036
    # (no emphasis-only paragraphs), and the guide is committed to repos
    # that lint - everything generated here has to come out clean.
    lines = [f"# {app['name']} — Feature Guide", ""]
    if app.get("tagline"):
        lines += textwrap.wrap(str(app["tagline"]), width=80) + [""]
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
            lines += textwrap.wrap(str(step["caption"]), width=80)
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


def parse_color(value, default):
    """'#RGB' / '#RRGGBB' manifest string -> (r, g, b), or default."""
    if not value:
        return default
    hex_part = str(value).strip().lstrip("#")
    if len(hex_part) == 3:
        hex_part = "".join(c * 2 for c in hex_part)
    if len(hex_part) == 6:
        try:
            return tuple(int(hex_part[i : i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            pass
    warn(f"invalid colour {value!r} in the manifest (want #RGB or #RRGGBB) — using default")
    return default


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


def caption_overlay(text, font_path="", highlight="", accent=ACCENT):
    """Static bottom caption band, rendered once per step (RGBA).

    ``highlight`` is one key phrase of ``text`` (whitespace-normalised)
    rendered in the brand accent colour; everything else stays white.
    Captions without a highlight render exactly as before.
    """
    from PIL import Image, ImageDraw

    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    if not text:
        return overlay
    draw = ImageDraw.Draw(overlay)
    font = load_font(54, font_path)
    margin, pad = 56, 40
    max_text_width = WIDTH - 2 * (margin + pad)
    # wrap_text splits on whitespace, so wrapped lines are substrings of the
    # normalised text; highlight offsets are tracked against that string.
    normalized = " ".join(text.split())
    lines = wrap_text(draw, normalized, font, max_text_width)
    hl_start = normalized.find(" ".join(highlight.split())) if highlight else -1
    hl_end = hl_start + len(" ".join(highlight.split())) if hl_start >= 0 else -1
    line_height = 68
    band_height = 2 * pad + line_height * len(lines)
    top = HEIGHT - 220 - band_height
    draw.rounded_rectangle(
        (margin, top, WIDTH - margin, top + band_height),
        radius=28,
        fill=(12, 14, 20, 210),
    )
    white = (255, 255, 255, 255)
    accent_fill = tuple(accent) + (255,)
    y = top + pad
    offset = 0
    for line in lines:
        w = draw.textlength(line, font=font)
        x = (WIDTH - w) / 2
        if hl_start < 0 or hl_end <= offset or hl_start >= offset + len(line):
            draw.text((x, y), line, font=font, fill=white)
        else:
            seg_a = max(0, hl_start - offset)
            seg_b = min(len(line), hl_end - offset)
            pieces = ((0, seg_a, white), (seg_a, seg_b, accent_fill), (seg_b, len(line), white))
            for start, end, fill in pieces:
                if end <= start:
                    continue
                seg_x = x + draw.textlength(line[:start], font=font)
                draw.text((seg_x, y), line[start:end], font=font, fill=fill)
        offset += len(line) + 1  # +1 for the space wrap_text consumed
        y += line_height
    return overlay


def hook_card(app, hook, font_path="", bg=CARD_BG, accent=ACCENT):
    """Opening full-frame card: brand background, hook line, app name."""
    from PIL import Image, ImageDraw

    card = Image.new("RGB", (WIDTH, HEIGHT), bg)
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
    draw.text(((WIDTH - w) / 2, y), name, font=name_font, fill=accent)
    if app.get("tagline"):
        y += 96
        w = draw.textlength(app["tagline"], font=tag_font)
        draw.text(((WIDTH - w) / 2, y), app["tagline"], font=tag_font, fill=(200, 205, 215))
    return card


def end_card(app, offer, logo_path, font_path="", bg=CARD_BG, accent=ACCENT):
    """Closing full-frame card: logo (when present), app name, offer line."""
    from PIL import Image, ImageDraw

    card = Image.new("RGB", (WIDTH, HEIGHT), bg)
    draw = ImageDraw.Draw(card)
    name_font = load_font(96, font_path)
    offer_font = load_font(48, font_path)

    logo = None
    if logo_path:
        if os.path.exists(logo_path):
            try:
                with Image.open(logo_path) as raw:
                    logo = raw.convert("RGBA")
                logo.thumbnail((420, 420), Image.LANCZOS)
            except OSError as e:
                warn(f"end card: could not read logo {logo_path!r} ({e}) — rendering without it")
                logo = None
        else:
            warn(f"end card: logo {logo_path!r} not found in the checkout — rendering without it")

    offer_lines = wrap_text(draw, offer, offer_font, WIDTH - 200) if offer else []
    line_height = 62
    block = (logo.height + 96 if logo else 0) + 110
    if offer_lines:
        block += 60 + line_height * len(offer_lines)
    y = (HEIGHT - block) // 2
    if logo:
        card.paste(logo, ((WIDTH - logo.width) // 2, y), logo)
        y += logo.height + 96
    name = app.get("name", "")
    w = draw.textlength(name, font=name_font)
    draw.text(((WIDTH - w) / 2, y), name, font=name_font, fill=(255, 255, 255))
    y += 110
    if offer_lines:
        y += 60
        for line in offer_lines:
            w = draw.textlength(line, font=offer_font)
            draw.text(((WIDTH - w) / 2, y), line, font=offer_font, fill=accent)
            y += line_height
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

    brand_bg = parse_color(video_cfg.get("brand_color"), CARD_BG)
    accent = parse_color(video_cfg.get("accent_color"), ACCENT)
    hook = str(video_cfg.get("hook") or "").strip()
    offer = str(video_cfg.get("offer") or "").strip()
    logo_path = str(app.get("logo") or "").strip()
    want_end_card = bool(offer or logo_path)

    hook_seconds = CARD_SECONDS if hook else 0.0
    end_seconds = CARD_SECONDS if want_end_card else 0.0
    per_step = float(video_cfg.get("seconds_per_step") or 3.0)
    # Keep total inside the 20-45s house window (min 2s per still).
    per_step = max(2.0, min(per_step, (45.0 - hook_seconds - end_seconds) / len(steps)))
    total = hook_seconds + per_step * len(steps) + end_seconds
    log(
        f"video plan: hook {hook_seconds:.0f}s + {len(steps)} stills x {per_step:.1f}s "
        f"+ end card {end_seconds:.0f}s = {total:.1f}s at {fps}fps ({codec}/{container})"
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
        if hook:
            card = hook_card(app, hook, font_path, bg=brand_bg, accent=accent)
            for _ in range(int(round(hook_seconds * fps))):
                push(card)
        else:
            log("no video.hook in the manifest — skipping the hook card")

        step_frames = int(round(per_step * fps))
        for step in steps:
            with Image.open(shots[step["key"]]) as raw:
                base = cover_resize(raw.convert("RGB"))
            overlay = caption_overlay(
                step.get("caption") or step.get("title") or "",
                font_path,
                highlight=step.get("highlight") or "",
                accent=accent,
            )
            for i in range(step_frames):
                progress = i / max(1, step_frames - 1)
                frame = zoomed_frame(base, progress).convert("RGBA")
                frame.alpha_composite(overlay)
                push(frame.convert("RGB"))

        if want_end_card:
            card = end_card(app, offer, logo_path, font_path, bg=brand_bg, accent=accent)
            for _ in range(int(round(end_seconds * fps))):
                push(card)

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
    parser.add_argument(
        "--require-varied",
        action="store_true",
        help="fail (instead of just warning) when every captured screenshot is byte-identical",
    )
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
    if shots_all_identical(shots):
        warn(
            f"ALL {len(shots)} captured screenshots are byte-identical — the capture "
            f"almost certainly regressed to placeholder frames"
        )
        if args.require_varied:
            fail("--require-varied: refusing to assemble from identical screenshots")

    if args.guide:
        write_guide(resolved, shots, args.out)
    if args.video:
        write_video(
            resolved, shots, args.out,
            args.ffmpeg, args.codec, args.container, args.fps, args.font,
        )


if __name__ == "__main__":
    main()

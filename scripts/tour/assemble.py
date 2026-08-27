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
"""Assemble guided-tour outputs from the resolved tour plan + captured stills.

Two independent products (so a video hiccup can never block the stills):

  --guide  (required output)  copies the captured screenshots to
           <out>/screenshots/NN-key.png and writes <out>/feature-guide.md
           embedding each still with its caption.

  --video  (best-effort)      renders ONE VIDEO PER CHAPTER as
           <out>/tour-<chapter>.mp4 (a chapter = the steps one fragment
           contributed; app-shell steps join the chapter they precede) in
           the org's vertical house style: 1080x1920 9:16, 30fps, a ~3s
           opening card first — the app's real SPLASH IMAGE full-frame
           when the resolved plan carries one (app.splash, auto-derived
           at merge time from flutter_native_splash.yaml / the committed
           splash asset), else the legacy hook card (brand background,
           hook line, app name — only when the manifest supplies a
           hook) — then one store-ad style
           beat per step (~4s each): the screenshot sits in a BLACK
           rounded-bezel phone frame on the brand-primary canvas,
           anchored to the bottom canvas edge with its lower part cropped
           off-screen (WhatsApp-ad framing). Each beat opens with the
           phone SLIDING IN from fully off-canvas past its anchored edge,
           decelerating into its rest crop over the beat's first quarter;
           the bold caption lines (drawn straight on the canvas, tight
           against the phone's near edge) fade in as the slide lands —
           then a ~3s end card (logo + app name + offer line —
           only when the manifest supplies an offer or a logo).
           video.chapter_frame_anchor flips named chapters to hang
           top-cropped from the top edge instead (caption moves below the
           phone), or to the legacy fully-visible floating phone. Caption
           ink is black or white, whichever reads better on the canvas;
           each caption may carry one key phrase inside a filled rounded
           highlight chip — accent-filled when the accent stands apart
           from the canvas, filled with the black/white contrast ink when
           it does not — with the keyword ink picked black or white
           against the chip fill. The phrase never splits across a line
           wrap. Frames are drawn entirely with Pillow (DejaVu Sans
           Bold); ffmpeg only encodes a concatenated-JPEG frame stream,
           so no ffmpeg filters or pipe protocols are needed.
           Codec/container are parametrized; CI uses libx264 + mp4 +
           faststart. The video stage also exports <out>/store/NN-key.png
           — one Play-Store-ready styled still per step (the beat
           composition at rest, no cards, no drift), wholesale-refreshed
           like the raw screenshots dir — plus the Play listing's two
           LANDSCAPE assets: <out>/store/feature-graphic.png, the exact
           1024x500 feature graphic (brand canvas; logo, app name and
           tagline on the left; framed hero screenshot on the right), and
           <out>/tour-wide.<container>, ONE 1920x1080 16:9 highlight reel
           across all chapters (landscape splash opening card, caption
           column beside the framed phone per beat, landscape end card),
           kept short by selecting up to two highlighted beats per
           chapter.

--device picks the canvas/frame geometry preset: ``phone`` (the default —
everything above, byte-identical to runs that predate the flag) or
``tablet``, which renders the SAME products on the 10-inch portrait
1600x2560 canvas for the workflow's tablet emulator leg. A tablet run
writes to its own --out directory (the workflow passes
<phone-out>/tablet) and deliberately SKIPS the phone-only Play listing
assets — store/feature-graphic.png, store/icon-512.png and the
tour-wide reel exist once per listing and stay with the phone run — so
its store/ dir holds ONLY portrait tablet stills, which the Play deploy
classifies as tenInchScreenshots by directory.

Branding (app name, tagline, hook, colours, offer, logo) comes exclusively
from the app shell's resolved tour plan — SDK fragments stay brand-neutral.
Colours default to the composed app's AppStyle palette (resolved at merge
time; the canvas IS the brand primary colour); explicit video.brand_color /
video.accent_color manifest keys win.

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
BEAT_SECONDS = 4.0  # one caption beat per still (WhatsApp-status pacing)
CARD_SECONDS = 3.0  # hook card and end card each hold for ~3s
CARD_BG = (12, 14, 20)  # card background when the manifest has no brand colour
ACCENT = (120, 200, 255)  # accent when the manifest has no accent colour
# Phone frame each screenshot renders inside (all px on the 1080x1920
# canvas), styled after the WhatsApp store ads: thin BLACK bezel, large
# corner radius, screen clipped to rounded corners inside it, soft shadow.
FRAME_BEZEL = 24
FRAME_RADIUS = 96
FRAME_BLACK = (0, 0, 0, 255)
# Screenshot fit boxes inside the bezel: edge-anchored phones render big
# (their cropped edge leaves the canvas anyway); the legacy `full` anchor
# keeps the smaller box so the whole phone stays visible.
FRAME_MAX_W, FRAME_MAX_H = 780, 1500
FULL_MAX_W, FULL_MAX_H = 700, 1200
# A square/landscape splash mark (not full-screen art) fits inside this
# box, centred on the brand canvas.
SPLASH_FIT_W, SPLASH_FIT_H = 900, 900
FRAME_MARGIN = 80  # transparent margin around the card so the shadow fits
CROP_FRACTION = 0.16  # share of the phone's height cropped off-canvas at rest
CAPTION_TOP = 140  # caption block top margin (bottom-anchored beats)
CAPTION_BOTTOM = 140  # caption block bottom margin (top-anchored beats)
CAPTION_MIN_EDGE = 72  # caption never gets closer than this to a canvas edge
CAPTION_PHONE_GAP = 48  # px between the caption block and the phone's near edge
FRAME_ZONE_TOP = 500  # `full` anchor: phone floats below the caption zone
VALID_FRAME_ANCHORS = ("bottom", "top", "full")
# Chapter-beat entrance: the phone starts FULLY off-canvas past its anchored
# edge (below for bottom/full, above for top) and decelerates (cubic
# ease-out) into its rest position over the beat's first quarter, then
# holds. The caption stays hidden while the phone travels and fades in as
# the slide-in lands (~80% through the entrance).
ENTRANCE_FRACTION = 0.25  # share of the beat the slide-in takes
CAPTION_APPEAR_AT = 0.20  # beat progress when the caption starts fading in
CAPTION_FADE_FRACTION = 0.10  # share of the beat the caption fade takes
# Wide-reel phones keep the legacy gentle settle instead (the landscape
# promo reads calmer with most of the screen already in view).
DRIFT_PX = 40
FULL_DRIFT_PX = 60  # legacy `full` anchor drift (wide reel only)
INK_DARK = (17, 17, 20)
INK_LIGHT = (255, 255, 255)
MIN_ACCENT_CONTRAST = 2.5  # below this the accent cannot stand apart from the canvas
# Keyword highlight chip: a filled rounded rectangle behind the caption's
# one *key phrase*. Modest padding so the chip hugs the word without
# colliding with neighbouring words; the vertical pad keeps the chip
# inside the caption's line box so stacked lines never touch it.
CHIP_PAD_X = 20
CHIP_PAD_Y = 8
CHIP_RADIUS = 18
# --- landscape (Play listing) outputs, rendered by the same video stage ------
# The Play Store listing also wants LANDSCAPE assets: the 1024x500 feature
# graphic and ONE widescreen 16:9 promo reel across all chapters.
WIDE_W, WIDE_H = 1920, 1080
FEATURE_W, FEATURE_H = 1024, 500
FEATURE_SS = 2  # the feature graphic renders supersampled, then downscales
# Wide-reel phone boxes: the portrait phone sits in the RIGHT half of the
# landscape canvas (caption in the left half), gently edge-cropped; the
# legacy `full` anchor keeps the whole phone visible.
WIDE_FRAME_MAX_W, WIDE_FRAME_MAX_H = 620, 1150
WIDE_FULL_MAX_W, WIDE_FULL_MAX_H = 560, 920
WIDE_CROP_FRACTION = 0.10  # gentler than portrait: most of the screen stays visible
WIDE_CAPTION_MARGIN = 120
# Reel beat selection: each chapter contributes its first captured steps
# that carry a highlight phrase (up to WIDE_BEATS_PER_CHAPTER), else its
# first captured step; the whole reel caps at WIDE_MAX_BEATS beats.
WIDE_BEATS_PER_CHAPTER = 2
WIDE_MAX_BEATS = 8
FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
)
# --- device geometry presets -------------------------------------------------
# The module-level constants above ARE the phone preset (so a run without
# --device is byte-identical to runs that predate the flag). The tablet
# preset re-targets the portrait canvas to the workflow's 10-inch tablet
# leg (1600x2560, the emulator's forced `wm size` — inside Play's
# 320-3840px screenshot bounds) and scales the phone-frame fit boxes to
# keep the same canvas margins. Landscape (wide reel / feature graphic)
# constants stay untouched: the tablet run skips those phone-only assets.
DEVICE_PRESETS = {
    "phone": {},
    "tablet": {
        "WIDTH": 1600,
        "HEIGHT": 2560,
        "FRAME_MAX_W": 1150,
        "FRAME_MAX_H": 2000,
        "FULL_MAX_W": 1040,
        "FULL_MAX_H": 1600,
        "SPLASH_FIT_W": 1200,
        "SPLASH_FIT_H": 1200,
        "FRAME_ZONE_TOP": 660,
    },
}


def apply_device_preset(device):
    """Overwrite the geometry constants with the ``device`` preset's values.

    Must run before any rendering. The phone preset is empty on purpose:
    applying it changes nothing, keeping the default path byte-identical.
    """
    globals().update(DEVICE_PRESETS[device])


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
        "> app, walks the guided tour on an Android emulator, and captures",
        "> each screen below.",
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


def rel_luminance(rgb):
    """WCAG relative luminance of an (r, g, b) colour."""

    def chan(c):
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (chan(c) for c in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a, b):
    """WCAG contrast ratio between two (r, g, b) colours (1..21)."""
    la, lb = rel_luminance(a), rel_luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def ink_for(bg):
    """Near-black or white ink — whichever reads better on the background.

    The brand-primary canvas can be any colour (WhatsApp green, Supacharge
    orange, a dark navy...), so every piece of text picks its ink against
    the actual background instead of assuming white-on-dark.
    """
    dark, light = contrast_ratio(INK_DARK, bg), contrast_ratio(INK_LIGHT, bg)
    return INK_DARK if dark >= light else INK_LIGHT


def readable_accent(accent, bg, fallback):
    """The accent colour when it reads on bg, else the fallback ink.

    With colours derived from AppStyle the accent often EQUALS the canvas
    colour — accent-coloured text would vanish, so it falls back."""
    return tuple(accent) if contrast_ratio(accent, bg) >= MIN_ACCENT_CONTRAST else tuple(fallback)


def chip_colors(accent, bg):
    """(fill, keyword ink) for the highlight chip on canvas ``bg``.

    The chip fills with the accent colour when that stands apart from the
    canvas; when it cannot (with AppStyle-derived colours the accent often
    EQUALS the canvas) it fills with the black/white contrast ink for the
    canvas instead — either way the chip itself always reads. The keyword
    ink is then black or white against the CHIP fill, never the canvas.
    """
    fill = tuple(accent) if contrast_ratio(accent, bg) >= MIN_ACCENT_CONTRAST else tuple(ink_for(bg))
    return fill, tuple(ink_for(fill))


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


def phone_card(shot, max_w=None, max_h=None):
    """Screenshot -> phone mockup (RGBA), WhatsApp-store-ad style.

    Drawn programmatically with Pillow: a soft blurred drop shadow, a
    thin BLACK rounded-rect bezel with a large corner radius, and the
    screenshot clipped to rounded corners inset inside it. The returned
    image carries a transparent FRAME_MARGIN on every side so the shadow
    blur never clips. ``max_w``/``max_h`` default to the ACTIVE device
    preset's FRAME_MAX box (resolved at call time, not def time, so
    ``apply_device_preset`` takes effect).
    """
    from PIL import Image, ImageDraw, ImageFilter

    max_w = FRAME_MAX_W if max_w is None else max_w
    max_h = FRAME_MAX_H if max_h is None else max_h
    scale = min(max_w / shot.width, max_h / shot.height)
    inner_w = max(1, round(shot.width * scale))
    inner_h = max(1, round(shot.height * scale))
    inner = shot.resize((inner_w, inner_h), Image.LANCZOS)
    clip = Image.new("L", (inner_w, inner_h), 0)
    ImageDraw.Draw(clip).rounded_rectangle(
        (0, 0, inner_w - 1, inner_h - 1), radius=FRAME_RADIUS - FRAME_BEZEL, fill=255
    )
    card_w = inner_w + 2 * FRAME_BEZEL
    card_h = inner_h + 2 * FRAME_BEZEL
    card = Image.new("RGBA", (card_w + 2 * FRAME_MARGIN, card_h + 2 * FRAME_MARGIN), (0, 0, 0, 0))
    shadow = Image.new("RGBA", card.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (FRAME_MARGIN, FRAME_MARGIN + 16, FRAME_MARGIN + card_w, FRAME_MARGIN + 16 + card_h),
        radius=FRAME_RADIUS,
        fill=(0, 0, 0, 110),
    )
    card.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(30)))
    ImageDraw.Draw(card).rounded_rectangle(
        (FRAME_MARGIN, FRAME_MARGIN, FRAME_MARGIN + card_w, FRAME_MARGIN + card_h),
        radius=FRAME_RADIUS,
        fill=FRAME_BLACK,
        outline=(46, 46, 50, 255),
        width=2,
    )
    card.paste(inner, (FRAME_MARGIN + FRAME_BEZEL, FRAME_MARGIN + FRAME_BEZEL), clip)
    return card


def highlight_tokens(normalized, highlight):
    """Whitespace-normalised caption -> (word, is_highlight, glued) tokens.

    The highlight phrase (when present in the caption) becomes ONE token,
    so wrapping can treat it as unbreakable. ``glued`` marks a token that
    followed its neighbour with no space in the caption (punctuation
    around the phrase, e.g. ``... *one clean schedule*.``) so layout can
    keep it flush against the chip instead of inserting a gap.
    """
    phrase = " ".join(highlight.split()) if highlight else ""
    start = normalized.find(phrase) if phrase else -1
    if start < 0:
        return [(word, False, False) for word in normalized.split()]
    pre, post = normalized[:start], normalized[start + len(phrase) :]
    tokens = [(word, False, False) for word in pre.split()]
    tokens.append((phrase, True, bool(pre) and not pre.endswith(" ")))
    post_tokens = [(word, False, False) for word in post.split()]
    if post_tokens and not post.startswith(" "):
        post_tokens[0] = (post_tokens[0][0], False, True)
    return tokens + post_tokens


def wrap_tokens(draw, tokens, font, max_width):
    """Greedy-wrap (word, is_highlight, glued) tokens into lines of tokens.

    A highlight token measures with the chip's horizontal padding
    included and NEVER splits across lines: when the whole phrase (chip
    and all) does not fit the current line, it drops whole to the next
    row, so each caption draws exactly one chip on one line.
    """
    space_w = draw.textlength(" ", font=font)
    lines, current, current_w = [], [], 0.0
    for token in tokens:
        word, is_highlighted, glued = token
        width = draw.textlength(word, font=font) + (2 * CHIP_PAD_X if is_highlighted else 0)
        trial = current_w + (space_w if current and not glued else 0) + width
        if trial <= max_width or not current:
            current.append(token)
            current_w = trial
        else:
            lines.append(current)
            current, current_w = [token], width
    if current:
        lines.append(current)
    return lines


def draw_caption_lines(draw, lines, font, origin_x, top, line_height, ink, chip_fill, chip_ink):
    """Draw wrapped (word, is_highlight, glued) token lines with their chips.

    Shared by the portrait caption block and the wide reel's caption
    column so both render the exact same type treatment: left-aligned
    bold lines, one filled rounded highlight chip around the key phrase.
    """
    ascent, descent = font.getmetrics()
    space_w = draw.textlength(" ", font=font)
    y = top
    for line in lines:
        x = origin_x
        for index, (word, is_highlighted, glued) in enumerate(line):
            if index and not glued:
                x += space_w
            width = draw.textlength(word, font=font)
            if is_highlighted:
                chip_w = width + 2 * CHIP_PAD_X
                chip_box = (x, y - CHIP_PAD_Y, x + chip_w, y + ascent + descent + CHIP_PAD_Y)
                draw.rounded_rectangle(chip_box, radius=CHIP_RADIUS, fill=chip_fill)
                draw.text((x + CHIP_PAD_X, y), word, font=font, fill=chip_ink)
                x += chip_w
            else:
                draw.text((x, y), word, font=font, fill=ink)
                x += width
        y += line_height


def entrance_ease(progress):
    """Beat progress 0..1 -> phone slide-in progress 0..1 (cubic ease-out).

    The whole travel happens inside the beat's first ENTRANCE_FRACTION,
    decelerating into the rest position (no overshoot); the phone then
    holds at 1.0 for the remainder of the beat.
    """
    t = min(1.0, progress / ENTRANCE_FRACTION)
    return 1.0 - (1.0 - t) ** 3


def caption_alpha(progress):
    """Beat progress 0..1 -> caption opacity 0..1.

    Zero while the phone travels, ramping to full over
    CAPTION_FADE_FRACTION once the slide-in is nearly done
    (CAPTION_APPEAR_AT sits at ~80% of the entrance window).
    """
    return max(0.0, min(1.0, (progress - CAPTION_APPEAR_AT) / CAPTION_FADE_FRACTION))


def with_alpha(overlay, alpha):
    """``overlay`` (RGBA) scaled to ``alpha`` opacity (0..1); 1.0 is free."""
    if alpha >= 1.0:
        return overlay
    faded = overlay.copy()
    faded.putalpha(faded.getchannel("A").point(lambda a: round(a * alpha)))
    return faded


def beat_frames(backdrop, caption, card, x, y_at, step_frames):
    """Yield one chapter beat's RGB frames: slide-in, caption fade, hold.

    The phone slides in from fully off-canvas (``entrance_ease``) while
    the caption stays hidden, then the caption fades in as the slide
    lands (``caption_alpha``); once both settle the frame is static, so
    it renders once and repeats for the rest of the beat.
    """
    settled = None
    for i in range(step_frames):
        progress = i / max(1, step_frames - 1)
        ease = entrance_ease(progress)
        alpha = caption_alpha(progress)
        if ease >= 1.0 and alpha >= 1.0:
            if settled is None:
                rest = backdrop.copy()
                rest.alpha_composite(caption)
                rest.paste(card, (x, y_at(1.0)), card)
                settled = rest.convert("RGB")
            yield settled
            continue
        frame = backdrop.copy()
        if alpha > 0.0:
            frame.alpha_composite(with_alpha(caption, alpha))
        frame.paste(card, (x, y_at(ease)), card)
        yield frame.convert("RGB")


def caption_overlay(
    text, font_path="", highlight="", accent=ACCENT, bg=CARD_BG, position="top", phone_edge=None
):
    """Static caption block, rendered once per step (RGBA).

    WhatsApp-ad style: bold left-aligned lines drawn straight on the
    brand canvas (no band), in black or white ink — whichever reads
    better on the background. ``highlight`` is one key phrase of ``text``
    (whitespace-normalised) drawn inside a filled rounded highlight chip:
    accent-filled when the accent stands apart from the canvas, filled
    with the black/white contrast ink when it cannot (typically because
    the derived accent IS the canvas colour), with the keyword ink picked
    black or white against the chip fill (see ``chip_colors``). The
    phrase never splits across a line wrap — when it does not fit the
    current line it drops whole to the next row. ``position`` is "top"
    (above a bottom-anchored phone) or "bottom" (below a top-anchored
    one). ``phone_edge`` is the canvas y of the phone's nearest bezel
    edge at rest: when given, the block hugs it (CAPTION_PHONE_GAP away,
    clamped CAPTION_MIN_EDGE from the canvas edge) instead of hanging at
    the fixed canvas margin.
    """
    from PIL import Image, ImageDraw

    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    if not text:
        return overlay
    draw = ImageDraw.Draw(overlay)
    font = load_font(64, font_path)
    margin = 72
    max_text_width = WIDTH - 2 * margin
    normalized = " ".join(text.split())
    lines = wrap_tokens(draw, highlight_tokens(normalized, highlight), font, max_text_width)
    line_height = 84
    block_height = line_height * len(lines)
    if position == "top":
        top = CAPTION_TOP
        if phone_edge is not None:
            top = max(CAPTION_MIN_EDGE, phone_edge - CAPTION_PHONE_GAP - block_height)
    else:
        top = HEIGHT - CAPTION_BOTTOM - block_height
        if phone_edge is not None:
            top = min(HEIGHT - CAPTION_MIN_EDGE - block_height, phone_edge + CAPTION_PHONE_GAP)
    ink = tuple(ink_for(bg)) + (255,)
    chip_fill, chip_ink = chip_colors(accent, bg)
    draw_caption_lines(
        draw, lines, font, margin, top, line_height, ink, chip_fill + (255,), chip_ink + (255,)
    )
    return overlay


def caption_column(text, font_path="", highlight="", accent=ACCENT, bg=CARD_BG):
    """Left-column caption block for one wide-reel beat (RGBA, WIDE_WxWIDE_H).

    Same type treatment as the portrait beats (bold 64px lines, one
    highlight chip via ``draw_caption_lines``), wrapped to the landscape
    canvas' left half and vertically centred beside the phone.
    """
    from PIL import Image, ImageDraw

    overlay = Image.new("RGBA", (WIDE_W, WIDE_H), (0, 0, 0, 0))
    if not text:
        return overlay
    draw = ImageDraw.Draw(overlay)
    font = load_font(64, font_path)
    max_text_width = WIDE_W // 2 - WIDE_CAPTION_MARGIN - 40
    normalized = " ".join(text.split())
    lines = wrap_tokens(draw, highlight_tokens(normalized, highlight), font, max_text_width)
    line_height = 84
    top = max(WIDE_CAPTION_MARGIN, (WIDE_H - line_height * len(lines)) // 2)
    ink = tuple(ink_for(bg)) + (255,)
    chip_fill, chip_ink = chip_colors(accent, bg)
    draw_caption_lines(
        draw,
        lines,
        font,
        WIDE_CAPTION_MARGIN,
        top,
        line_height,
        ink,
        chip_fill + (255,),
        chip_ink + (255,),
    )
    return overlay


def load_splash_art(splash_path):
    """The splash asset as RGBA, or None (warned) when missing/unreadable."""
    from PIL import Image

    if not os.path.exists(splash_path):
        warn(f"splash card: {splash_path!r} not found in the checkout — using the hook card")
        return None
    try:
        with Image.open(splash_path) as raw:
            return raw.convert("RGBA")
    except OSError as e:
        warn(f"splash card: could not read {splash_path!r} ({e}) — using the hook card")
        return None


def edge_average(art):
    """Average colour of an image's outer 1px border, as (r, g, b)."""
    rgb = art.convert("RGB")
    w, h = rgb.size
    pixels = []
    for x in range(w):
        pixels.append(rgb.getpixel((x, 0)))
        pixels.append(rgb.getpixel((x, h - 1)))
    for y in range(h):
        pixels.append(rgb.getpixel((0, y)))
        pixels.append(rgb.getpixel((w - 1, y)))
    return tuple(round(sum(p[i] for p in pixels) / len(pixels)) for i in range(3))


def splash_card(splash_path, bg=CARD_BG):
    """Opening full-frame card: the app's real splash image.

    Portrait art (like Supacharge's full-screen native splash) fills the
    whole 1080x1920 frame — cover-scaled and centre-cropped, which stays
    faithful to how flutter_native_splash stretches a background_image to
    the device screen. A square or landscape asset (a splash logo mark)
    instead sits centred on the brand canvas, alpha preserved. Returns
    None when the file is missing or unreadable so the caller can fall
    back to the legacy hook card.
    """
    from PIL import Image

    art = load_splash_art(splash_path)
    if art is None:
        return None
    if art.height > art.width:  # portrait, like the canvas: full-bleed
        scale = max(WIDTH / art.width, HEIGHT / art.height)
        art = art.resize(
            (max(WIDTH, round(art.width * scale)), max(HEIGHT, round(art.height * scale))),
            Image.LANCZOS,
        )
        left = (art.width - WIDTH) // 2
        top = (art.height - HEIGHT) // 2
        return art.crop((left, top, left + WIDTH, top + HEIGHT)).convert("RGB")
    art.thumbnail((SPLASH_FIT_W, SPLASH_FIT_H), Image.LANCZOS)
    card = Image.new("RGBA", (WIDTH, HEIGHT), tuple(bg) + (255,))
    card.alpha_composite(art, ((WIDTH - art.width) // 2, (HEIGHT - art.height) // 2))
    return card.convert("RGB")


def splash_card_wide(splash_path, bg=CARD_BG):
    """Landscape opening card for the wide reel (RGB, WIDE_WxWIDE_H) or None.

    Portrait full-screen art cannot centre-crop to 16:9 without slicing
    through its own typography, so it renders CONTAINED at full canvas
    height, centred, with the side pillars filled with the art's own
    border-average colour — flat-background splash art (the common case)
    blends seamlessly. Full-bleed landscape art cover-crops to the canvas
    like the portrait card does; a small square/landscape splash mark
    sits centred on the brand canvas, alpha preserved.
    """
    from PIL import Image

    art = load_splash_art(splash_path)
    if art is None:
        return None
    if art.height > art.width:  # portrait art: contain at full height, pillar-fill
        fill = edge_average(art)
        scale = WIDE_H / art.height
        art = art.resize((max(1, round(art.width * scale)), WIDE_H), Image.LANCZOS)
        card = Image.new("RGBA", (WIDE_W, WIDE_H), tuple(fill) + (255,))
        card.alpha_composite(art, ((WIDE_W - art.width) // 2, 0))
        return card.convert("RGB")
    if art.width > SPLASH_FIT_W or art.height > SPLASH_FIT_H:  # full-bleed landscape art
        scale = max(WIDE_W / art.width, WIDE_H / art.height)
        art = art.resize(
            (max(WIDE_W, round(art.width * scale)), max(WIDE_H, round(art.height * scale))),
            Image.LANCZOS,
        )
        left = (art.width - WIDE_W) // 2
        top = (art.height - WIDE_H) // 2
        return art.crop((left, top, left + WIDE_W, top + WIDE_H)).convert("RGB")
    card = Image.new("RGBA", (WIDE_W, WIDE_H), tuple(bg) + (255,))
    card.alpha_composite(art, ((WIDE_W - art.width) // 2, (WIDE_H - art.height) // 2))
    return card.convert("RGB")


def hook_card(app, hook, font_path="", bg=CARD_BG, accent=ACCENT, size=None):
    """Legacy opening card: brand background, hook line, app name.

    Used only when no app splash image resolves (see ``splash_card``).
    All text picks black-or-white ink against the actual background; the
    app name uses the accent colour only when it reads on the canvas.
    ``size`` defaults to the active preset's portrait canvas (resolved
    at call time); the wide reel passes its landscape one.
    """
    from PIL import Image, ImageDraw

    card_w, card_h = size if size is not None else (WIDTH, HEIGHT)
    card = Image.new("RGB", (card_w, card_h), bg)
    draw = ImageDraw.Draw(card)
    hook_font = load_font(96, font_path)
    name_font = load_font(64, font_path)
    tag_font = load_font(42, font_path)
    ink = ink_for(bg)
    muted = tuple(round(0.72 * i + 0.28 * b) for i, b in zip(ink, bg))

    lines = wrap_text(draw, hook, hook_font, card_w - 200)
    line_height = 118
    y = card_h // 2 - (line_height * len(lines)) // 2 - 140
    for line in lines:
        w = draw.textlength(line, font=hook_font)
        draw.text(((card_w - w) / 2, y), line, font=hook_font, fill=ink)
        y += line_height

    y += 90
    name = app.get("name", "")
    w = draw.textlength(name, font=name_font)
    draw.text(((card_w - w) / 2, y), name, font=name_font, fill=readable_accent(accent, bg, ink))
    if app.get("tagline"):
        y += 96
        w = draw.textlength(app["tagline"], font=tag_font)
        draw.text(((card_w - w) / 2, y), app["tagline"], font=tag_font, fill=muted)
    return card


def end_card(app, offer, logo_path, font_path="", bg=CARD_BG, accent=ACCENT, size=None):
    """Closing full-frame card: logo (when present), app name, offer line.

    ``size`` defaults to the active preset's portrait canvas (resolved
    at call time); the wide reel renders the same centred stack on its
    landscape one.
    """
    from PIL import Image, ImageDraw

    card_w, card_h = size if size is not None else (WIDTH, HEIGHT)
    card = Image.new("RGB", (card_w, card_h), bg)
    draw = ImageDraw.Draw(card)
    name_font = load_font(96, font_path)
    offer_font = load_font(48, font_path)
    ink = ink_for(bg)

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

    offer_lines = wrap_text(draw, offer, offer_font, card_w - 200) if offer else []
    line_height = 62
    block = (logo.height + 96 if logo else 0) + 110
    if offer_lines:
        block += 60 + line_height * len(offer_lines)
    y = (card_h - block) // 2
    if logo:
        card.paste(logo, ((card_w - logo.width) // 2, y), logo)
        y += logo.height + 96
    name = app.get("name", "")
    w = draw.textlength(name, font=name_font)
    draw.text(((card_w - w) / 2, y), name, font=name_font, fill=ink)
    y += 110
    if offer_lines:
        y += 60
        offer_fill = readable_accent(accent, bg, ink)
        for line in offer_lines:
            w = draw.textlength(line, font=offer_font)
            draw.text(((card_w - w) / 2, y), line, font=offer_font, fill=offer_fill)
            y += line_height
    return card


def encode_stream(ffmpeg, stream_path, out_path, codec, container, fps):
    """Encode one concatenated-JPEG frame stream to out_path via ffmpeg."""
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


def encode_frames(ffmpeg, out_path, codec, container, fps, frames):
    """Encode an iterable of RGB Pillow frames to out_path; returns the count.

    All frame work stays in Pillow; ffmpeg only encodes a
    concatenated-JPEG stream read from ONE file with the image2pipe
    demuxer. This needs no ffmpeg filters and no pipe/fd protocols, so it
    works identically on CI's full apt ffmpeg and on trimmed local builds
    (Playwright's build ships only the `file` protocol and only the
    image2pipe + matroska demuxers).
    """
    frames_dir = tempfile.mkdtemp(prefix="tour_frames_")
    stream_path = os.path.join(frames_dir, "frames.mjpeg")
    count = 0
    try:
        with open(stream_path, "wb") as stream:
            for frame in frames:
                count += 1
                frame.save(stream, format="JPEG", quality=92)
        encode_stream(ffmpeg, stream_path, out_path, codec, container, fps)
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)
    return count


def build_wide_beat(step, anchor, shot_path, brand_bg, accent, font_path):
    """One wide-reel beat's static parts: (backdrop+caption, card, x, y_at).

    Landscape composition: the caption column fills the LEFT half of the
    canvas, the portrait framed phone sits centred in the RIGHT half.
    The chapter's frame anchor still applies, just gentler than portrait
    (``WIDE_CROP_FRACTION``): `bottom`/`top` phones rest lightly cropped
    against that canvas edge and ease toward it; `full` keeps the whole
    phone visible with the legacy two-way float.
    """
    from PIL import Image

    with Image.open(shot_path) as raw:
        if anchor == "full":
            card = phone_card(raw.convert("RGB"), WIDE_FULL_MAX_W, WIDE_FULL_MAX_H)
        else:
            card = phone_card(raw.convert("RGB"), WIDE_FRAME_MAX_W, WIDE_FRAME_MAX_H)
    backdrop = Image.new("RGBA", (WIDE_W, WIDE_H), tuple(brand_bg) + (255,))
    backdrop.alpha_composite(
        caption_column(
            step.get("caption") or step.get("title") or "",
            font_path,
            highlight=step.get("highlight") or "",
            accent=accent,
            bg=brand_bg,
        )
    )
    x = WIDE_W // 2 + (WIDE_W // 2 - card.width) // 2
    phone_h = card.height - 2 * FRAME_MARGIN  # the bezel rect itself
    crop = round(WIDE_CROP_FRACTION * phone_h)

    def y_at(ease):
        if anchor == "full":
            return (WIDE_H - card.height) // 2 + round(FULL_DRIFT_PX * (0.5 - ease))
        off = crop + round(DRIFT_PX * (1 - ease))
        if anchor == "top":
            return -off - FRAME_MARGIN
        return WIDE_H + off - FRAME_MARGIN - phone_h  # bottom

    return backdrop, card, x, y_at


def select_wide_beats(chapters, shots, chapter_anchor):
    """Pick the highlight reel's beats, as a list of (step, anchor).

    Selection rule: chapters keep tour order; each chapter contributes
    its first WIDE_BEATS_PER_CHAPTER captured steps that carry a
    highlight phrase (the manifest author's own emphasis is the best
    available signal for a chapter's strongest beats), or its first
    captured step when none carry one — so every chapter appears. The
    reel then caps at WIDE_MAX_BEATS beats, dropping later chapters'
    extra picks first (never a chapter's only beat), so the promo stays
    short.
    """
    picks = []
    for chapter, chapter_steps in chapters.items():
        captured = [s for s in chapter_steps if s["key"] in shots]
        if not captured:
            continue
        anchor = chapter_anchor(chapter)
        strongest = [s for s in captured if str(s.get("highlight") or "").strip()]
        chosen = strongest[:WIDE_BEATS_PER_CHAPTER] or captured[:1]
        picks.append([(s, anchor) for s in chosen])
    total = sum(len(p) for p in picks)
    while total > WIDE_MAX_BEATS:
        trimmed = False
        for chapter_picks in reversed(picks):
            if len(chapter_picks) > 1:
                chapter_picks.pop()
                total -= 1
                trimmed = True
                break
        if not trimmed:
            break
    return [beat for chapter_picks in picks for beat in chapter_picks]


def render_wide_video(
    out_dir, beats, opening_image, end_image, brand_bg, accent, font_path, shots,
    ffmpeg, codec, container, fps, per_step,
):
    """Render the single landscape highlight reel: <out>/tour-wide.<container>.

    One 1920x1080 16:9 promo across ALL chapters (the Play listing's
    widescreen video slot), sharing the chapter videos' fps, codec and
    pacing: landscape opening splash card, the selected beats (see
    ``select_wide_beats``), landscape end card.
    """
    out_path = os.path.join(out_dir, f"tour-wide.{container}")
    opening_seconds = CARD_SECONDS if opening_image is not None else 0.0
    end_seconds = CARD_SECONDS if end_image is not None else 0.0
    total = opening_seconds + per_step * len(beats) + end_seconds
    log(
        f"wide reel: opening {opening_seconds:.0f}s + {len(beats)} beats x "
        f"{per_step:.1f}s + end card {end_seconds:.0f}s = {total:.1f}s at {fps}fps "
        f"({codec}/{container}, {WIDE_W}x{WIDE_H})"
    )

    def frames():
        if opening_image is not None:
            for _ in range(int(round(opening_seconds * fps))):
                yield opening_image
        step_frames = int(round(per_step * fps))
        for step, anchor in beats:
            backdrop, card, x, y_at = build_wide_beat(
                step, anchor, shots[step["key"]], brand_bg, accent, font_path
            )
            for i in range(step_frames):
                progress = i / max(1, step_frames - 1)
                ease = progress * progress * (3 - 2 * progress)  # smoothstep
                frame = backdrop.copy()
                frame.paste(card, (x, y_at(ease)), card)
                yield frame.convert("RGB")
        if end_image is not None:
            for _ in range(int(round(end_seconds * fps))):
                yield end_image

    count = encode_frames(ffmpeg, out_path, codec, container, fps, frames())
    size = os.path.getsize(out_path)
    log(
        f"wrote {out_path}: {count} frames, "
        f"{count / fps:.1f}s, {size / 1_000_000:.2f} MB"
    )


def pick_hero_step(chapters, shots, feature_step=""):
    """The feature graphic's hero still, or None when nothing was captured.

    An explicit store.feature_step names the hero step outright
    (convention: the app's HOME step). Otherwise the first captured step
    of the SECOND chapter (the first chapter is usually
    onboarding/sign-in, whose screens sell the app least), falling back
    to the tour's first captured step.
    """
    if feature_step:
        named = next(
            (s for steps in chapters.values() for s in steps if s["key"] == feature_step),
            None,
        )
        if named is not None and named["key"] in shots:
            return named
        if named is None:
            warn(
                f"store.feature_step: no step with key '{feature_step}' "
                "— using the default hero"
            )
        else:
            warn(
                f"store.feature_step: step '{feature_step}' has no captured "
                "screenshot — using the default hero"
            )
    names = list(chapters)
    if len(names) > 1:
        for step in chapters[names[1]]:
            if step["key"] in shots:
                return step
    for chapter_steps in chapters.values():
        for step in chapter_steps:
            if step["key"] in shots:
                return step
    return None


def write_feature_graphic(out_dir, app, hero_shot_path, logo_path, brand_bg, font_path):
    """<out>/store/feature-graphic.png — the Play listing's 1024x500 banner.

    Brand-primary canvas; logo mark, app name and tagline stacked on the
    left; the hero screenshot in the house phone frame on the right,
    bottom edge cropped by the canvas. Composed to Play feature-graphic
    conventions: minimal text, nothing critical near the edges or the
    exact centre (Play crops the graphic in some placements and overlays
    a play button on it when it fronts the promo video). Rendered at
    FEATURE_SS x and downscaled so the type stays crisp.
    """
    from PIL import Image, ImageDraw

    w, h = FEATURE_W * FEATURE_SS, FEATURE_H * FEATURE_SS
    canvas = Image.new("RGBA", (w, h), tuple(brand_bg) + (255,))
    draw = ImageDraw.Draw(canvas)
    ink = ink_for(brand_bg)
    muted = tuple(round(0.72 * i + 0.28 * b) for i, b in zip(ink, brand_bg))

    # Framed hero phone on the right, rising past the bottom canvas edge.
    with Image.open(hero_shot_path) as raw:
        card = phone_card(raw.convert("RGB"), 620, 1200)
    bezel_w = card.width - 2 * FRAME_MARGIN
    canvas.alpha_composite(card, (w - 150 - bezel_w - FRAME_MARGIN, 130 - FRAME_MARGIN))

    # Left text column: logo mark, app name (shrunk to fit), tagline.
    margin, text_max = 160, 880
    name = str(app.get("name") or "")
    name_size = 150
    name_font = load_font(name_size, font_path)
    while name_size > 90 and draw.textlength(name, font=name_font) > text_max:
        name_size -= 10
        name_font = load_font(name_size, font_path)
    tag_font = load_font(60, font_path)
    tagline = str(app.get("tagline") or "")
    tag_lines = wrap_text(draw, tagline, tag_font, text_max) if tagline else []
    logo = None
    if logo_path and os.path.exists(logo_path):
        try:
            with Image.open(logo_path) as raw:
                logo = raw.convert("RGBA")
            logo.thumbnail((280, 280), Image.LANCZOS)
        except OSError as e:
            warn(f"feature graphic: could not read logo {logo_path!r} ({e}) — omitting it")
            logo = None
    name_a, name_d = name_font.getmetrics()
    tag_a, tag_d = tag_font.getmetrics()
    tag_line_h = tag_a + tag_d + 10
    block = (logo.height + 60 if logo else 0) + name_a + name_d
    if tag_lines:
        block += 28 + tag_line_h * len(tag_lines)
    y = (h - block) // 2
    if logo:
        canvas.alpha_composite(logo, (margin, y))
        y += logo.height + 60
    draw.text((margin, y), name, font=name_font, fill=ink)
    y += name_a + name_d + 28
    for line in tag_lines:
        draw.text((margin, y), line, font=tag_font, fill=muted)
        y += tag_line_h

    out_path = os.path.join(out_dir, "store", "feature-graphic.png")
    graphic = canvas.convert("RGB").resize((FEATURE_W, FEATURE_H), Image.LANCZOS)
    graphic.save(out_path, format="PNG")
    log(f"wrote {out_path} ({FEATURE_W}x{FEATURE_H})")


def write_app_icon(out_dir, logo_path, brand_bg):
    """<out>/store/icon-512.png — the Play listing's 512x512 app icon.

    The app logo centred on the brand-primary canvas with breathing
    room, exactly 512x512 (Play's icon spec: 512x512 PNG, at most 1MB —
    a flat-background PNG at this size is nowhere near the limit). The
    Play-deploy uploader classifies it by its dimensions, like the
    feature graphic. Skipped (logged) when the plan resolves no logo.
    """
    from PIL import Image

    if not logo_path or not os.path.exists(logo_path):
        log("app icon: no app logo in the resolved plan — skipping store/icon-512.png")
        return
    try:
        with Image.open(logo_path) as raw:
            logo = raw.convert("RGBA")
    except OSError as e:
        warn(f"app icon: could not read logo {logo_path!r} ({e}) — skipping it")
        return
    side = 512
    # Scale to FIT a 360px box (up or down — unlike thumbnail, small
    # committed logo rasters must still fill the icon): the logo is the
    # icon's whole content, with ~30% canvas breathing room around it.
    box = 360
    scale = box / max(logo.width, logo.height)
    logo = logo.resize(
        (max(1, round(logo.width * scale)), max(1, round(logo.height * scale))),
        Image.LANCZOS,
    )
    canvas = Image.new("RGBA", (side, side), tuple(brand_bg) + (255,))
    canvas.alpha_composite(logo, ((side - logo.width) // 2, (side - logo.height) // 2))
    out_path = os.path.join(out_dir, "store", "icon-512.png")
    canvas.convert("RGB").save(out_path, format="PNG")
    log(f"wrote {out_path} ({side}x{side}, {os.path.getsize(out_path) / 1024:.0f} KB)")


def write_video(resolved, shots, out_dir, ffmpeg, codec, container, fps, font_path, device="phone"):
    """Render one video per chapter: <out>/tour-<chapter>.<container>.

    A chapter is the run of steps one fragment contributed (app-shell steps
    were folded into the chapter they precede at merge time). Every chapter
    video carries the same opening card (the app's splash image when the
    plan resolves one, else the manifest hook card) and logo/offer end
    card, with the chapter's phone-framed caption beats in between.

    video.chapter_frame_anchor (chapter -> bottom|top|full) controls how
    each chapter's phone meets the canvas edge; unlisted chapters anchor
    bottom-cropped, WhatsApp-ad style. Also exports <out>/store/NN-key.png
    — one Play-Store-ready styled still per step, the beat composition at
    rest (no hook/end cards, no drift) — refreshed wholesale, plus the
    landscape Play-listing assets: <out>/store/feature-graphic.png
    (1024x500, see ``write_feature_graphic``), the 512x512
    <out>/store/icon-512.png (see ``write_app_icon``) and the single
    16:9 highlight reel <out>/tour-wide.<container> across all chapters
    (see ``select_wide_beats`` / ``render_wide_video``).

    ``device`` "tablet" (the workflow's tablet leg, rendering into its
    own out dir) keeps the chapter videos and store stills but SKIPS the
    phone-only Play listing assets — feature graphic, icon and the wide
    reel exist once per listing and belong to the phone run — so the
    tablet store/ dir holds only portrait stills for tenInchScreenshots.
    """
    from PIL import Image

    app = resolved["app"]
    video_cfg = resolved.get("video", {})
    if not any(s["key"] in shots for s in resolved["steps"]):
        fail("video: no captured screenshots to render")

    # Refresh the published videos wholesale (like the guide's stills) so
    # the legacy single tour.<container> and removed chapters never linger
    # in the committed outputs.
    for stale in glob.glob(os.path.join(out_dir, f"tour.{container}")) + glob.glob(
        os.path.join(out_dir, f"tour-*.{container}")
    ):
        os.remove(stale)

    brand_bg = parse_color(video_cfg.get("brand_color"), CARD_BG)
    accent = parse_color(video_cfg.get("accent_color"), ACCENT)
    hook = str(video_cfg.get("hook") or "").strip()
    offer = str(video_cfg.get("offer") or "").strip()
    logo_path = str(app.get("logo") or "").strip()
    splash_path = str(app.get("splash") or "").strip()
    want_end_card = bool(offer or logo_path)

    # Opening card: the app's real splash image when the plan resolves
    # one; the legacy hook card when it does not but the manifest has a
    # hook; nothing otherwise (the video starts on the first beat).
    opening_image = splash_card(splash_path, bg=brand_bg) if splash_path else None
    if opening_image is not None:
        log(f"opening card: app splash image {splash_path}")
    elif hook:
        opening_image = hook_card(app, hook, font_path, bg=brand_bg, accent=accent)
        log("opening card: hook card (no app splash image resolved)")
    else:
        log("no app splash or video.hook — chapter videos start on the first beat")

    opening_seconds = CARD_SECONDS if opening_image is not None else 0.0
    end_seconds = CARD_SECONDS if want_end_card else 0.0
    # Fixed beat per still — the total is however long the chapter needs
    # (status-ad pacing), never crammed into a fixed window.
    per_step = max(2.0, min(float(video_cfg.get("beat_seconds") or BEAT_SECONDS), 10.0))
    end_image = (
        end_card(app, offer, logo_path, font_path, bg=brand_bg, accent=accent)
        if want_end_card
        else None
    )

    anchors_cfg = video_cfg.get("chapter_frame_anchor") or {}
    if not isinstance(anchors_cfg, dict):
        warn("video.chapter_frame_anchor is not a map of chapter -> anchor — ignored")
        anchors_cfg = {}

    def chapter_anchor(chapter):
        anchor = str(anchors_cfg.get(chapter) or "bottom").strip().lower()
        if anchor not in VALID_FRAME_ANCHORS:
            warn(
                f"chapter '{chapter}': unknown frame anchor {anchor!r} "
                f"(want one of {'/'.join(VALID_FRAME_ANCHORS)}) — using bottom"
            )
            anchor = "bottom"
        return anchor

    def build_beat(step, anchor):
        """One beat's static parts: (backdrop, caption, phone card, x, y_at).

        y_at(ease) is the card paste position for an entrance progress in
        0..1: at 0 the phone sits FULLY off-canvas past its anchored edge
        (below the canvas for bottom/full, above it for top), at 1 it
        rests at its final crop. The caption overlay is returned
        separately (not baked into the backdrop) so the render loop can
        fade it in once the slide-in lands; it hugs the phone's resting
        edge (see ``caption_overlay``'s ``phone_edge``).
        """
        with Image.open(shots[step["key"]]) as raw:
            if anchor == "full":
                card = phone_card(raw.convert("RGB"), FULL_MAX_W, FULL_MAX_H)
            else:
                card = phone_card(raw.convert("RGB"))
        backdrop = Image.new("RGBA", (WIDTH, HEIGHT), tuple(brand_bg) + (255,))
        x = (WIDTH - card.width) // 2
        phone_h = card.height - 2 * FRAME_MARGIN  # the bezel rect itself
        crop = round(CROP_FRACTION * phone_h)

        if anchor == "full":
            y_rest = FRAME_ZONE_TOP + (HEIGHT - 40 - FRAME_ZONE_TOP - card.height) // 2
            y_start = HEIGHT  # fully below the canvas, shadow and all
        elif anchor == "top":
            y_rest = -crop - FRAME_MARGIN
            y_start = -card.height  # fully above the canvas
        else:  # bottom
            y_rest = HEIGHT + crop - FRAME_MARGIN - phone_h
            y_start = HEIGHT  # fully below the canvas, shadow and all

        def y_at(ease):
            return round(y_rest + (y_start - y_rest) * (1.0 - ease))

        if anchor == "top":
            phone_edge = y_rest + FRAME_MARGIN + phone_h  # bezel bottom at rest
        else:
            phone_edge = y_rest + FRAME_MARGIN  # bezel top at rest
        caption = caption_overlay(
            step.get("caption") or step.get("title") or "",
            font_path,
            highlight=step.get("highlight") or "",
            accent=accent,
            bg=brand_bg,
            position="bottom" if anchor == "top" else "top",
            phone_edge=phone_edge,
        )
        return backdrop, caption, card, x, y_at

    def write_store_stills(chapters):
        """<out>/store/NN-key.png — the beat composition at rest, per step.

        Play-Store listing stills on the same portrait canvas as the
        video (the active device preset's WIDTHxHEIGHT — 1080x1920 for
        phone, 1600x2560 for tablet); numbering matches the guide's
        screenshots. Wholesale-refreshed so removed or renamed steps
        never linger. The wipe only ever touches THIS run's out dir, so
        the tablet refresh never clears the phone store dir or vice
        versa.
        """
        store_dir = os.path.join(out_dir, "store")
        os.makedirs(store_dir, exist_ok=True)
        for stale in glob.glob(os.path.join(store_dir, "*.png")):
            os.remove(stale)
        number = 0
        for chapter, chapter_steps in chapters.items():
            anchor = chapter_anchor(chapter)
            for step in chapter_steps:
                if step["key"] not in shots:
                    continue
                number += 1
                backdrop, caption, card, x, y_at = build_beat(step, anchor)
                still = backdrop.copy()
                still.alpha_composite(caption)
                still.paste(card, (x, y_at(1.0)), card)
                still.convert("RGB").save(
                    os.path.join(store_dir, f"{number:02d}-{step['key']}.png"), format="PNG"
                )
        log(f"wrote {number} styled store stills to {store_dir}")

    def render_chapter(chapter, steps, anchor):
        out_path = os.path.join(out_dir, f"tour-{chapter}.{container}")
        total = opening_seconds + per_step * len(steps) + end_seconds
        log(
            f"chapter '{chapter}': opening {opening_seconds:.0f}s + {len(steps)} beats x "
            f"{per_step:.1f}s + end card {end_seconds:.0f}s = {total:.1f}s at {fps}fps "
            f"({codec}/{container}, frame anchor: {anchor})"
        )

        def frames():
            if opening_image is not None:
                for _ in range(int(round(opening_seconds * fps))):
                    yield opening_image
            step_frames = int(round(per_step * fps))
            for step in steps:
                backdrop, caption, card, x, y_at = build_beat(step, anchor)
                yield from beat_frames(backdrop, caption, card, x, y_at, step_frames)
            if end_image is not None:
                for _ in range(int(round(end_seconds * fps))):
                    yield end_image

        frames_written = encode_frames(ffmpeg, out_path, codec, container, fps, frames())
        size = os.path.getsize(out_path)
        log(
            f"wrote {out_path}: {frames_written} frames, "
            f"{frames_written / fps:.1f}s, {size / 1_000_000:.2f} MB"
        )

    # Group the plan's steps into chapters, preserving tour order. Steps
    # from resolved plans that predate chapters all land in 'app'.
    chapters = {}
    for step in resolved["steps"]:
        chapters.setdefault(str(step.get("chapter") or "app"), []).append(step)
    write_store_stills(chapters)
    if device == "phone":
        store_cfg = resolved.get("store") or {}
        if not isinstance(store_cfg, dict):
            warn("store: is not a mapping in the resolved plan — ignored")
            store_cfg = {}
        hero = pick_hero_step(chapters, shots, str(store_cfg.get("feature_step") or "").strip())
        if hero is not None:
            # store.logo overrides the feature graphic's logo mark: absent
            # (None) keeps app.logo, a path uses that path, "" draws none.
            feature_logo = logo_path
            if store_cfg.get("logo") is not None:
                feature_logo = str(store_cfg["logo"]).strip()
                if not feature_logo:
                    log("feature graphic: store.logo is empty — no logo mark")
            write_feature_graphic(
                out_dir, app, shots[hero["key"]], feature_logo, brand_bg, font_path
            )
        write_app_icon(out_dir, logo_path, brand_bg)
    else:
        log(
            f"device '{device}': skipping feature graphic, icon and wide reel "
            "— those Play listing assets exist once and stay with the phone run"
        )
    for chapter, chapter_steps in chapters.items():
        captured = [s for s in chapter_steps if s["key"] in shots]
        if not captured:
            log(f"chapter '{chapter}': no captured screenshots — skipping its video")
            continue
        if chapter == "wide":
            warn(
                "chapter 'wide' shares the landscape reel's output name "
                f"tour-wide.{container} — the reel overwrites it; rename the fragment"
            )
        render_chapter(chapter, captured, chapter_anchor(chapter))

    # The single landscape highlight reel across ALL chapters (the Play
    # listing's widescreen promo-video slot) — phone run only.
    beats = select_wide_beats(chapters, shots, chapter_anchor) if device == "phone" else []
    if beats:
        wide_opening = splash_card_wide(splash_path, bg=brand_bg) if splash_path else None
        if wide_opening is None and hook:
            wide_opening = hook_card(
                app, hook, font_path, bg=brand_bg, accent=accent, size=(WIDE_W, WIDE_H)
            )
        wide_end = (
            end_card(
                app, offer, logo_path, font_path,
                bg=brand_bg, accent=accent, size=(WIDE_W, WIDE_H),
            )
            if want_end_card
            else None
        )
        render_wide_video(
            out_dir, beats, wide_opening, wide_end, brand_bg, accent, font_path, shots,
            ffmpeg, codec, container, fps, per_step,
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
        "--device",
        choices=sorted(DEVICE_PRESETS),
        default="phone",
        help="canvas/frame geometry preset (default: phone, byte-identical to "
        "runs without the flag); 'tablet' renders the 10-inch 1600x2560 "
        "portrait geometry and skips the phone-only Play assets (feature "
        "graphic, icon, wide reel) — point --out at a tablet-specific dir",
    )
    parser.add_argument(
        "--require-varied",
        action="store_true",
        help="fail (instead of just warning) when every captured screenshot is byte-identical",
    )
    args = parser.parse_args()
    apply_device_preset(args.device)

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
            device=args.device,
        )


if __name__ == "__main__":
    main()

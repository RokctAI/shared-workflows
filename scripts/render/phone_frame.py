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
"""Put a REAL screen render (PNG from the Flutter harness) inside a phone or
tablet frame drawn in code. Never hand-draw the screen itself.

  python3 phone_frame.py screen.png out.png [--device phone|tablet]
        [--bg "#0E1726"] [--frame "#111418"] [--scale 1.0] [--no-shadow]
"""
import argparse
from PIL import Image, ImageDraw, ImageFilter

DEVICES = {  # bezel px, outer corner radius, screen corner radius (at screen width 1170)
    "phone": dict(bezel=34, r_out=170, r_in=140, island=True),
    "tablet": dict(bezel=46, r_out=110, r_in=70, island=False),
}


def _rounded_mask(size, r):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], r, fill=255)
    return m


def frame(screen: Image.Image, device="phone", frame_color="#111418",
          bg=None, shadow=True, pad=None) -> Image.Image:
    d = DEVICES[device]
    k = screen.width / 1170 if device == "phone" else screen.width / 2048
    bez, r_out, r_in = (max(6, int(v * k)) for v in (d["bezel"], d["r_out"], d["r_in"]))
    w, h = screen.width + 2 * bez, screen.height + 2 * bez
    pad = pad if pad is not None else int(w * 0.12)
    canvas = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), bg or (0, 0, 0, 0))
    if shadow:
        sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle(
            [pad, pad + int(h * 0.025), pad + w, pad + h + int(h * 0.025)], r_out, fill=(0, 0, 0, 110))
        canvas.alpha_composite(sh.filter(ImageFilter.GaussianBlur(int(w * 0.04))))
    body = Image.new("RGBA", (w, h), frame_color)
    canvas.paste(body, (pad, pad), _rounded_mask((w, h), r_out))
    # thin edge highlight so the frame reads on dark backgrounds
    ImageDraw.Draw(canvas).rounded_rectangle(
        [pad, pad, pad + w - 1, pad + h - 1], r_out, outline=(255, 255, 255, 40), width=max(2, int(3 * k)))
    canvas.paste(screen.convert("RGBA"), (pad + bez, pad + bez), _rounded_mask(screen.size, r_in))
    if d["island"]:
        iw, ih = int(screen.width * 0.30), int(screen.width * 0.085)
        x0, y0 = pad + (w - iw) // 2, pad + bez + int(screen.width * 0.03)
        ImageDraw.Draw(canvas).rounded_rectangle([x0, y0, x0 + iw, y0 + ih], ih // 2, fill="#000000")
    return canvas


def tag(img: Image.Image, text="PROPOSAL", color="#FF6600") -> Image.Image:
    """Stamp a pill label above the device so a mock is never mistaken for a built screen."""
    from PIL import ImageFont
    size = max(14, img.width // 22)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", size)
    except OSError:
        font = ImageFont.load_default()
    d = ImageDraw.Draw(img)
    w = d.textlength(text, font=font)
    x, y, px = (img.width - w) / 2, size * 0.6, size * 0.7
    d.rounded_rectangle([x - px, y - px / 2, x + w + px, y + size + px / 2], size, fill=color)
    d.text((x, y), text, font=font, fill="#FFFFFF")
    return img


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("screen"); ap.add_argument("out")
    ap.add_argument("--device", default="phone", choices=DEVICES)
    ap.add_argument("--bg"); ap.add_argument("--frame", default="#111418")
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--no-shadow", action="store_true")
    ap.add_argument("--proposal", action="store_true", help="stamp PROPOSAL above the device")
    a = ap.parse_args()
    img = frame(Image.open(a.screen), a.device, a.frame, a.bg, not a.no_shadow)
    if a.proposal:
        img = tag(img)
    if a.scale != 1.0:
        img = img.resize((int(img.width * a.scale), int(img.height * a.scale)), Image.LANCZOS)
    img.save(a.out)
    print(a.out, img.size)

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
"""One command for the shared render pipeline.

  python3 scripts/render/render.py frame SCREEN.png OUT.png [--device phone|tablet] [--bg ...]
  python3 scripts/render/render.py deck SPEC.json OUT.pptx
  python3 scripts/render/render.py preview DECK.pptx            # slide PNGs (needs LibreOffice)
  python3 scripts/render/render.py screen                         # how to render a real Flutter screen
Needs: pip install pillow python-pptx lxml
"""
import subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__); return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "frame":
        return subprocess.call([sys.executable, str(HERE / "phone_frame.py"), *rest])
    if cmd == "deck":
        return subprocess.call([sys.executable, str(HERE / "deck.py"), *rest])
    if cmd == "preview":
        pptx = Path(rest[0]).resolve()
        rc = subprocess.call(["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(pptx.parent), str(pptx)])
        if rc: return rc
        return subprocess.call(["pdftoppm", "-png", "-r", "80", str(pptx.with_suffix(".pdf")), str(pptx.with_suffix("")) + "-slide"])
    if cmd == "screen":
        print("Real screens: templates/render-harness/ + run_strip.sh, see scripts/render/README.md"); return 0
    print(f"unknown command {cmd}\n{__doc__}"); return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

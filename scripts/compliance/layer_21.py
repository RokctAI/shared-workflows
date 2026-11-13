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

import re
from compliance.base import register_file_checker

# Ray, 2026-11-13: "No spinner, use shimmers". Loading states in apps show a
# shimmer (base_sdk `Loading()`, `LoadingList`, `LoadingGrid`, `AppShimmer`),
# never a spinner. Renders and screenshots show neither (capture after load).
SPINNER_RE = re.compile(r"\b(CircularProgressIndicator|CupertinoActivityIndicator|RefreshProgressIndicator)\s*[.(]")
NEXT_SPINNER_RE = re.compile(r"\banimate-spin\b|<Spinner\b|\bLoader2\b")


@register_file_checker
def check_layer21_no_spinners(filepath):
    errors = []
    p = filepath.replace("\\", "/").lower()
    if "/test/" in p or "/.rokct/cache/" in p or p.endswith("_test.dart"):
        return errors
    if filepath.endswith(".dart"):
        rx = SPINNER_RE
    elif filepath.endswith((".tsx", ".jsx")):
        rx = NEXT_SPINNER_RE
    else:
        return errors
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except Exception as e:
        return [{"line": 1, "type": "Parse Error", "message": str(e)}]
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if s.startswith("//") or s.startswith("*"):
            continue
        m = rx.search(line)
        if m:
            errors.append({
                "line": i,
                "type": "Layer 21 (UI Loading States)",
                "message": f"Spinner '{m.group(0).rstrip('.(').strip()}' found: use a shimmer (base_sdk Loading/AppShimmer, or a skeleton on the web) instead.",
            })
    return errors

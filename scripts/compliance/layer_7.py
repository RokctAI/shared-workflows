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

import os
from compliance.base import register_file_checker

@register_file_checker
def check_layer7_caching_and_cdn(filepath):
    errors = []
    base = os.path.basename(filepath).lower()
    if "next.config" in base:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            if "headers" not in content and "cache-control" not in content.lower():
                errors.append({
                    "line": 1,
                    "type": "Layer 7 (Caching & CDN)",
                    "message": f"Next.js config file '{os.path.basename(filepath)}' lacks active CDN caching headers or 'headers()' configuration overrides."
                })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    elif (filepath.endswith(".conf") or "nginx" in filepath.lower()) and not filepath.endswith(".md"):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            if "expires " not in content and "cache-control" not in content.lower():
                errors.append({
                    "line": 1,
                    "type": "Layer 7 (Caching & CDN)",
                    "message": f"Nginx config '{os.path.basename(filepath)}' does not configure static asset expiration rules or Cache-Control headers."
                })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    elif "route.ts" in base or "route.js" in base:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            if "revalidate" not in content and "cache-control" not in content.lower() and "next:" not in content:
                errors.append({
                    "line": 1,
                    "type": "Layer 7 (Caching & CDN - Next.js)",
                    "message": f"API Route handler '{os.path.basename(filepath)}' lacks caching directives ('revalidate' parameter or Cache-Control headers) for CDN edge acceleration."
                })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

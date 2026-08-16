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

import os
from compliance.base import register_file_checker

@register_file_checker
def check_layer6_rate_limiting(filepath):
    errors = []
    if "nginx" in filepath.lower() or filepath.endswith(".conf"):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            # If the file defines an Nginx server or location block, verify it implements limit_req
            if "server {" in content or "location " in content:
                if "limit_req " not in content and "limit_req_zone" not in content:
                    errors.append({
                        "line": 1,
                        "type": "Layer 6 (Rate Limiting)",
                        "message": f"Nginx server/location block config exposed in '{os.path.basename(filepath)}' without active 'limit_req' zone throttles."
                    })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

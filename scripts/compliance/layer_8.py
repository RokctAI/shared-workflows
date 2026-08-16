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
def check_layer8_load_balancing_and_scaling(filepath):
    errors = []
    base = os.path.basename(filepath).lower()
    if ("docker-compose" in base or "compose" in base) and (base.endswith(".yml") or base.endswith(".yaml")):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            if "mem_limit" not in content and "limits:" not in content and "memory:" not in content:
                errors.append({
                    "line": 1,
                    "type": "Layer 8 (Load Balancing & Scaling)",
                    "message": f"Docker Compose config '{os.path.basename(filepath)}' fails to specify container memory limits (mem_limit or deploy.resources.limits.memory) for resource isolation."
                })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

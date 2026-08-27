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
def check_layer16_tenant_isolation(filepath):
    errors = []
    base = os.path.basename(filepath).lower()
    path_lower = filepath.lower()
    if filepath.endswith(".py"):
        if not any(x in path_lower for x in ["rcore", "paas", "rpanel", "control/control", "betassist"]):
            return errors

        if "test" in path_lower:
            return errors
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            
            # 1. Tenant DB Query Isolation Check
            if any(q in content for q in ["frappe.db.get_list", "frappe.db.get_all", "frappe.get_all", "frappe.get_list", "frappe.get_doc"]):
                if "tenant" not in content.lower() and "session.user" not in content.lower():
                    errors.append({
                        "line": 1,
                        "type": "Layer 16 (Multi-Tenant Isolation Gate)",
                        "message": f"Tenant database queries detected in '{os.path.basename(filepath)}' but no tenant context filters (tenant_id, tenant, or session.user) are active. Restrict queries to ensure complete data isolation."
                    })
            
            # 2. Free-Tier Quota Gate
            if "chat" in base or "completions" in base or "llm_service" in base:
                if "free_rok_msg_count" not in content and "quota" not in content.lower() and "limit" not in content.lower():
                    errors.append({
                        "line": 1,
                        "type": "Layer 16 (Quota Isolation Gate)",
                        "message": f"AI completion service '{os.path.basename(filepath)}' is missing active usage quota limit checks (e.g. checking 'free_rok_msg_count' Redis usage counters)."
                    })
            
            # 3. Remote VPS / Request Host Flaw Check
            if "request.host" in content:
                if "x-rokct-tenant" not in content.lower():
                    errors.append({
                        "line": 1,
                        "type": "Layer 16 (Multi-Tenant Isolation Gate)",
                        "message": f"Raw request.host domain resolution detected in '{os.path.basename(filepath)}' without resolving via the remote X-Rokct-Tenant header first. This will break remote VPS/Docker communication."
                    })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors


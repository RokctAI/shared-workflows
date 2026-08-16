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

import ast
import os
import re

from compliance.base import register_file_checker

# ---------------------------------------------------------------------------
# Layer 11 — Auth & Token Lifecycle
#
# Checks across all stacks:
#   Python/Frappe  — hardcoded token literals, tokens outside frappe.conf/env,
#                    missing expiry when issuing tokens/sessions
#   Next.js/TS     — tokens stored in localStorage, missing refresh logic
#   Flutter/Dart   — tokens in SharedPreferences, missing secure storage /
#                    expiry handling
# ---------------------------------------------------------------------------

_HARDCODED_TOKEN_KEYS = re.compile(
    r'\b(token|api_key|api_secret|secret|password|bearer|auth_token|access_token|refresh_token)\s*=\s*["\'](?!frappe\.|os\.|{|<)[^"\']{4,}["\']',
    re.IGNORECASE,
)

_FRAPPE_CONF_PATTERNS = [
    "frappe.conf.get",
    "frappe.conf[",
    "os.environ",
    "os.getenv",
]

_EXPIRY_PATTERNS = [
    "expires", "expiry", "exp", "ttl", "max_age", "expire_at", "expires_at",
    "valid_for", "lifetime",
]

_FLUTTER_SECURE_IMPORT = "flutter_secure_storage"
_FLUTTER_SHARED_PREFS  = "SharedPreferences"
_FLUTTER_TOKEN_KEYS    = re.compile(
    r'setString\s*\(\s*["\'](?:token|api_key|access_token|refresh_token|auth)["\']',
    re.IGNORECASE,
)

_TS_LOCALSTORAGE_TOKEN = re.compile(
    r'localStorage\.setItem\s*\(\s*["\'](?:token|access_token|refresh_token|api_key|auth)["\']',
    re.IGNORECASE,
)

_TS_REFRESH_INDICATORS = [
    "refreshToken", "refresh_token", "getNewToken", "renewToken",
    "tokenRefresh", "useRefreshToken", "rotateToken",
]


# ── Python / Frappe ──────────────────────────────────────────────────────────

@register_file_checker
def check_layer11_python_token_hygiene(filepath):
    errors = []
    if not filepath.endswith(".py"):
        return errors
    # Skip test / migration files
    fp_lower = filepath.lower()
    if any(x in fp_lower for x in ["test_", "_test.py", "migration", "fixture", "compliance"]):
        return errors
    try:
        content = open(filepath, encoding="utf-8").read()
    except Exception:
        return errors

    lines = content.splitlines()

    # 1. Hardcoded token literals
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if _HARDCODED_TOKEN_KEYS.search(line):
            # Check if it's actually reading from a safe source
            if not any(p in line for p in _FRAPPE_CONF_PATTERNS):
                errors.append({
                    "line": i,
                    "type": "Layer 11 (Auth - Hardcoded Token)",
                    "message": (
                        f"Possible hardcoded credential in '{os.path.basename(filepath)}' "
                        f"line {i}. Tokens must be read from frappe.conf / os.environ, "
                        f"never stored as string literals."
                    ),
                })

    # 2. Token/session issuance without expiry
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return errors

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # Look for generate_auth_token / set_cookie / create_token etc.
        call_str = ""
        if isinstance(node.func, ast.Attribute):
            call_str = node.func.attr.lower()
        elif isinstance(node.func, ast.Name):
            call_str = node.func.id.lower()

        if any(k in call_str for k in ["generate_token", "create_token", "set_cookie",
                                        "issue_token", "generate_key", "make_token"]):
            # Check if any expiry kwarg is present
            has_expiry = any(
                (isinstance(kw.arg, str) and any(e in kw.arg.lower() for e in _EXPIRY_PATTERNS))
                for kw in node.keywords
            )
            if not has_expiry:
                # Also check if expiry appears in surrounding lines (±3)
                start = max(0, node.lineno - 3)
                end   = min(len(lines), node.lineno + 3)
                window = " ".join(lines[start:end]).lower()
                if not any(e in window for e in _EXPIRY_PATTERNS):
                    errors.append({
                        "line": node.lineno,
                        "type": "Layer 11 (Auth - Missing Token Expiry)",
                        "message": (
                            f"Token/session issued in '{os.path.basename(filepath)}' "
                            f"via '{call_str}()' with no expiry/TTL argument. "
                            f"All issued tokens must have a bounded lifetime."
                        ),
                    })

    return errors


# ── Next.js / TypeScript ─────────────────────────────────────────────────────

@register_file_checker
def check_layer11_nextjs_token_hygiene(filepath):
    errors = []
    if not (filepath.endswith(".ts") or filepath.endswith(".tsx")):
        return errors
    fp_lower = filepath.lower()
    if any(x in fp_lower for x in ["test", "spec", ".d.ts", "compliance"]):
        return errors
    try:
        content = open(filepath, encoding="utf-8").read()
    except Exception:
        return errors

    lines = content.splitlines()

    # 1. Tokens stored in localStorage
    for i, line in enumerate(lines, 1):
        if _TS_LOCALSTORAGE_TOKEN.search(line):
            errors.append({
                "line": i,
                "type": "Layer 11 (Auth - Insecure Token Storage)",
                "message": (
                    f"Auth token stored in localStorage in '{os.path.basename(filepath)}' "
                    f"line {i}. Use httpOnly cookies or server-side session storage to "
                    f"prevent XSS token theft."
                ),
            })

    # 2. Files that use tokens but have no refresh logic
    uses_token = bool(re.search(r'\b(access_?token|bearer|Authorization)\b', content, re.IGNORECASE))
    has_refresh = any(indicator in content for indicator in _TS_REFRESH_INDICATORS)
    # Only flag auth-centric files (e.g. api clients, auth hooks)
    is_auth_file = any(k in fp_lower for k in ["auth", "token", "api", "client", "session"])
    if uses_token and not has_refresh and is_auth_file:
        errors.append({
            "line": 1,
            "type": "Layer 11 (Auth - Missing Token Rotation)",
            "message": (
                f"'{os.path.basename(filepath)}' uses auth tokens but has no token "
                f"refresh/rotation logic. Implement token renewal before expiry "
                f"(e.g. refreshToken, useRefreshToken)."
            ),
        })

    return errors


# ── Flutter / Dart ───────────────────────────────────────────────────────────

@register_file_checker
def check_layer11_flutter_token_hygiene(filepath):
    errors = []
    if not filepath.endswith(".dart"):
        return errors
    fp_lower = filepath.lower()
    if any(x in fp_lower for x in ["test", "generated", ".g.dart", "compliance"]):
        return errors
    try:
        content = open(filepath, encoding="utf-8").read()
    except Exception:
        return errors

    lines = content.splitlines()

    # 1. Token written to SharedPreferences instead of secure storage
    uses_shared_prefs = _FLUTTER_SHARED_PREFS in content
    has_secure_storage = _FLUTTER_SECURE_IMPORT in content
    stores_token = bool(_FLUTTER_TOKEN_KEYS.search(content))

    if uses_shared_prefs and stores_token and not has_secure_storage:
        for i, line in enumerate(lines, 1):
            if _FLUTTER_TOKEN_KEYS.search(line):
                errors.append({
                    "line": i,
                    "type": "Layer 11 (Auth - Insecure Token Storage)",
                    "message": (
                        f"Auth token written to SharedPreferences in "
                        f"'{os.path.basename(filepath)}' line {i}. "
                        f"Use flutter_secure_storage for all token/credential storage."
                    ),
                })

    # 2. Token usage without expiry check
    uses_token = bool(re.search(r'\b(accessToken|refreshToken|apiToken|bearerToken|authToken)\b', content))
    has_expiry = any(e in content.lower() for e in _EXPIRY_PATTERNS)
    is_auth_file = any(k in fp_lower for k in ["auth", "token", "api", "session", "service"])
    if uses_token and not has_expiry and is_auth_file:
        errors.append({
            "line": 1,
            "type": "Layer 11 (Auth - Missing Token Expiry Check)",
            "message": (
                f"'{os.path.basename(filepath)}' handles auth tokens but contains no "
                f"expiry/TTL check. Validate token lifetime before use and implement "
                f"refresh logic."
            ),
        })

    return errors

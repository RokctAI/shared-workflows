import ast
import os
from compliance.base import register_ast_assign, register_file_checker

@register_ast_assign
def check_layer4_5_secrets(visitor, node):
    for target in node.targets:
        if isinstance(target, ast.Name):
            var_name = target.id.lower()
            # Check for critical variable names
            if any(x in var_name for x in ["key", "token", "secret", "password"]):
                # Ignore standard utility variables or loop parameters
                if var_name in ["key", "keys", "token_usage", "cache_key", "secret_key_exists"]:
                    continue
                # Check if value is a hardcoded string literal
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    val = node.value.value
                    # Ignore standard placeholder strings or safe empty variables
                    if val.strip() and val not in ["***", "placeholder", "default", "none", "", "travis"]:
                        visitor.errors.append({
                            "line": node.lineno,
                            "type": "Layer 4 & 5 (Security)",
                            "message": f"Hardcoded security parameter '{target.id}' assigned static value '{val[:15]}...'. Load credentials dynamically via os.environ or frappe.conf instead."
                        })

@register_file_checker
def check_layer4_5_file_safety(filepath):
    errors = []
    base = os.path.basename(filepath).lower()
    
    # 1. Next.js credentials check
    if filepath.endswith(".ts") or filepath.endswith(".tsx"):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()
            for idx, line in enumerate(lines, 1):
                line_lower = line.lower()
                if any(k in line_lower for k in ["key", "secret", "token", "password"]):
                    if ('"' in line or "'" in line) and not any(p in line_lower for p in ["process.env", "config", "placeholder", "import", "from"]):
                        parts = line.split("=")
                        if len(parts) > 1:
                            val = parts[1].strip()
                            if (val.startswith('"') or val.startswith("'")) and len(val) > 15:
                                errors.append({
                                    "line": idx,
                                    "type": "Layer 4 & 5 (Security - Next.js)",
                                    "message": f"Hardcoded credential parameter detected in '{os.path.basename(filepath)}'. Use dynamic server env variables instead of static front-end strings."
                                })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})

    # 2. Flutter credentials check
    elif filepath.endswith(".dart"):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            import re
            # Regex targeting hardcoded API tokens or Client secrets in Dart
            if re.search(r"\b(api[kK]ey|clientSecret|stripeKey|paystackKey)\s*=\s*['\"][a-zA-Z0-9_\-]{10,}['\"]", content):
                errors.append({
                    "line": 1,
                    "type": "Layer 4 & 5 (Security - Flutter)",
                    "message": f"Hardcoded API key or Gateway client secret detected in Dart source code inside '{os.path.basename(filepath)}'. Load credentials dynamically via dart-define env values."
                })
            
            lines = content.splitlines()
            for idx, line in enumerate(lines, 1):
                line_lower = line.lower()
                if any(k in line_lower for k in ["key", "secret", "token", "password"]):
                    # Skip: storage lookups, interceptor headers, comments, and safe patterns
                    if any(p in line_lower for p in [
                        "dotenv", "environment", "placeholder", "key:",
                        "read(key", "write(key", "storage", "headers[",
                        "//", "///", "*", "interceptor"
                    ]):
                        continue
                    if ('"' in line or "'" in line):
                        parts = line.split("=")
                        if len(parts) > 1:
                            val = parts[1].strip()
                            if (val.startswith('"') or val.startswith("'")) and len(val) > 15:
                                errors.append({
                                    "line": idx,
                                    "type": "Layer 4 & 5 (Security - Flutter)",
                                    "message": f"Hardcoded constant credential detected in '{os.path.basename(filepath)}'. Inject variables dynamically via environment build arguments."
                                })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})

    # 3. Nginx headers check
    elif (filepath.endswith(".conf") or "nginx" in filepath.lower()) and not filepath.endswith(".md"):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            if "x-frame-options" not in content.lower():
                errors.append({
                    "line": 1,
                    "type": "Layer 5 (Security - Secure Headers)",
                    "message": f"Nginx config '{os.path.basename(filepath)}' lacks native 'X-Frame-Options' header injection to prevent Clickjacking attacks."
                })
            if "x-content-type-options" not in content.lower():
                errors.append({
                    "line": 1,
                    "type": "Layer 5 (Security - Secure Headers)",
                    "message": f"Nginx config '{os.path.basename(filepath)}' lacks native 'X-Content-Type-Options' sniff protection header."
                })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})

    return errors

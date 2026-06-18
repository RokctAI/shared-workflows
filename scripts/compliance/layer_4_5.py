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
                
                # 1. Sensitive Parameter Check (Existing Logic)
                if any(k in line_lower for k in ["key", "secret", "token", "password"]):
                    # Force translation for UI strings and security parameters
                    if ('"' in line or "'" in line) and not any(p in line_lower for p in ["process.env", "config", "placeholder", "import", "from", "t(", "i18n.t("]):
                        parts = line.split("=")
                        if len(parts) > 1:
                            val = parts[1].strip()
                            if (val.startswith('"') or val.startswith("'")) and len(val) > 15:
                                errors.append({
                                    "line": idx,
                                    "type": "Layer 4 & 5 (Security - Next.js)",
                                    "message": f"Hardcoded security parameter or UI label detected in '{os.path.basename(filepath)}'. Use translation keys (e.g., t('key')) or dynamic server env variables instead of static front-end strings."
                                })
                        elif any(tag in line_lower for tag in ["<label", "<h1>", "<h2>", "<h3>", "<h4>", "<h5>", "<h6>", "<span>", "<div>", "placeholder="]):
                            errors.append({
                                "line": idx,
                                "type": "Layer 4 & 5 (Security - Next.js)",
                                "message": f"Hardcoded UI string with sensitive keyword detected in '{os.path.basename(filepath)}'. Force translation via t('key') to ensure compliance and localization."
                            })
                
                # 2. General Translation Enforcement (Force i18n)
                # Flag any non-trivial string literal inside JSX tags that isn't wrapped in t()
                if (('"' in line or "'" in line) and 
                    not any(p in line_lower for p in ["t(", "i18n.t(", "process.env", "config", "import", "from", "className=", "id=", "key=", "name=", "htmlfor=", "value="])):
                    
                    if any(tag in line_lower for tag in ["<", ">", "placeholder=", "label="]):
                        import re
                        strings = re.findall(r"['\"](.*?)['\"]", line)
                        for s in strings:
                            if len(s) <= 3:
                                continue
                            
                            # HEURISTIC: Ignore strings that look like CSS/Tailwind classes
                            # 1. Contains common Tailwind prefixes
                            tailwind_prefixes = ("flex", "grid", "text-", "bg-", "p-", "m-", "w-", "h-", "items-", "justify-", "border-", "rounded-", "font-", "opacity-", "max-", "min-", "shadow-", "top-", "bottom-", "left-", "right-", "absolute-", "relative-", "fixed-", "sticky-", "z-", "gap-", "space-", "col-", "row-", "inset-", "truncate", "hidden", "block", "inline-", "whitespace-", "scale-", "origin-", "animate-", "cursor-", "divide-")
                            if s.lower().startswith(tailwind_prefixes) or any(f" {p}" in s.lower() for p in tailwind_prefixes):
                                continue
                            
                            # 2. Looks like a class list (multiple words with hyphens, no uppercase letters unless it's a specific token)
                            if "-" in s and not any(c.isupper() for c in s):
                                continue
                        
                            # HEURISTIC: Ignore technical paths or identifiers
                            if s.startswith("/") or (not " " in s and (s.isidentifier() or s.startswith("http"))):
                                continue
                            
                            # HEURISTIC: Ignore template variables
                            if "{{" in s and "}}" in s:
                                continue
                        
                            # HEURISTIC: Ignore CSS-like strings or SVG paths
                            if any(css in s.lower() for css in ["px", "em", "rem", "rgb(", "rgba(", "hsl(", "vh", "vw", "border-", "margin-", "padding-"]) or (s.startswith("#") and len(s) <= 7) or (s.startswith("M") and any(char.isdigit() for char in s) and " " not in s.split(',')[0]):
                                continue
                            
                            # Now, only flag strings that actually look like user-facing text
                            # (Contains spaces, or starts with uppercase, or is a phrase)
                            if " " in s or s[0].isupper():
                                errors.append({
                                    "line": idx,
                                    "type": "Layer 4 & 5 (Localization - Next.js)",
                                    "message": f"Hardcoded UI string '{s[:15]}...' detected in '{os.path.basename(filepath)}'. All user-facing text must be wrapped in t('key') for translation compliance."
                                })
                                break
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

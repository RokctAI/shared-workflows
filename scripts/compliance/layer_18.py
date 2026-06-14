import os
from compliance.base import register_file_checker

@register_file_checker
def check_layer18_ztna_mtls(filepath):
    errors = []
    base = os.path.basename(filepath).lower()
    path_lower = filepath.lower()
    if "test" in path_lower:
        return errors
    if filepath.endswith(".py"):
        if any(x in base for x in ["auth", "login", "gateway", "api"]):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                # Enforce zero trust checks like headers, certs, token verification, mTLS
                if not any(x in content.lower() for x in ["cert", "mtls", "tls", "token", "jwt", "verify", "permission", "authorized"]):
                    errors.append({
                        "line": 1,
                        "type": "Layer 18 (ZTNA & mTLS)",
                        "message": f"Auth/API module '{os.path.basename(filepath)}' fails to enforce Zero Trust authorization policies or mTLS certificate checks."
                    })
            except Exception as e:
                errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

@register_file_checker
def check_layer18_path_traversal(filepath):
    errors = []
    if filepath.endswith(".py"):
        base = os.path.basename(filepath).lower()
        if "test" in base:
            return errors
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            # If path joining is done, check for containment validation checks like is_safe_path
            if "os.path.join" in content and not any(x in content for x in ["is_safe_path", "abspath", "startswith"]):
                errors.append({
                    "line": 1,
                    "type": "Layer 18 (ZTNA & path containment checks)",
                    "message": f"Module '{os.path.basename(filepath)}' uses path join/manipulation without validating containment boundaries (e.g. verifying paths start with expected base directory)."
                })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

@register_file_checker
def check_layer18_command_injection(filepath):
    errors = []
    if filepath.endswith(".py"):
        base = os.path.basename(filepath).lower()
        if "test" in base:
            return errors
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            # Enforce that shell=True is avoided when running commands
            if "subprocess.run" in content and "shell=True" in content:
                errors.append({
                    "line": 1,
                    "type": "Layer 18 (Process execution security hardening)",
                    "message": f"Module '{os.path.basename(filepath)}' uses subprocess.run with shell=True which exposes the system to shell metacharacter command injection."
                })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

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
        if "test" in base or "compliance" in filepath.replace("\\", "/").lower():
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

@register_file_checker
def check_layer18_thread_safety(filepath):
    errors = []
    if filepath.endswith(".py"):
        base = os.path.basename(filepath).lower()
        if "test" in base:
            return errors
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            # If mutable global objects exist like dictionaries and threading/fastapi is imported, check that a lock is used
            if ("fastapi" in content or "threading" in content) and any(x in content for x in ["ACTIVE_TOKENS", "PR_COMMENTS", "PR_NUMBERS_TO_BRANCHES"]):
                if "Lock()" not in content or "with " not in content:
                    errors.append({
                        "line": 1,
                        "type": "Layer 18 (Thread Concurrency Safety)",
                        "message": f"Module '{os.path.basename(filepath)}' modifies critical global state dictionaries without acquiring a threading lock. Implement and use a Lock context manager."
                    })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

@register_file_checker
def check_layer18_background_task_logging(filepath):
    errors = []
    if filepath.endswith(".py"):
        base = os.path.basename(filepath).lower()
        if "test" in base:
            return errors
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            # Verify background thread targets use structured stderr/logging context to handle unexpected exceptions
            if "Thread(" in content and "target=" in content:
                if "sys.stderr.write" not in content and "logger.error" not in content and "except Exception" not in content:
                    errors.append({
                        "line": 1,
                        "type": "Layer 18 (Background Thread Exception Safety)",
                        "message": f"Module '{os.path.basename(filepath)}' launches background threads without structured catch-all logging blocks to capture failures on sys.stderr."
                    })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

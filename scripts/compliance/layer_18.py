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

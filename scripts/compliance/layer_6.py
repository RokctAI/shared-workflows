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

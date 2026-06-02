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

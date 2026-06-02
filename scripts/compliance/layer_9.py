import os
from compliance.base import register_file_checker

@register_file_checker
def check_layer9_dockerfile_compliance(filepath):
    errors = []
    if "dockerfile" in os.path.basename(filepath).lower():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            if "FROM " in content:
                from_counts = content.count("FROM ")
                if from_counts < 2 and " AS " not in content:
                    errors.append({
                        "line": 1,
                        "type": "Layer 9 (Containers)",
                        "message": f"Dockerfile '{os.path.basename(filepath)}' should utilize multi-stage builds ('FROM ... AS ...') to minimize final footprint."
                    })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

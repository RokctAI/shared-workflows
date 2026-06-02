import os
from compliance.base import register_file_checker

@register_file_checker
def check_layer17_edge_iot(filepath):
    errors = []
    base = os.path.basename(filepath).lower()
    path_lower = filepath.lower()
    if "test" in path_lower:
        return errors
    if "iot" in base or "iot" in path_lower:
        if filepath.endswith(".py") or filepath.endswith(".ts") or filepath.endswith(".tsx"):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                # Enforce MQTT, CoAP, edge buffers, or offline sync check
                if not any(x in content.lower() for x in ["mqtt", "coap", "edge", "buffer", "offline", "sync"]):
                    errors.append({
                        "line": 1,
                        "type": "Layer 17 (Edge IoT)",
                        "message": f"IoT edge module '{os.path.basename(filepath)}' lacks robust offline buffering, sync protocol (MQTT/CoAP) or local queues."
                    })
            except Exception as e:
                errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

import os
from compliance.base import register_file_checker

@register_file_checker
def check_layer19_event_driven(filepath):
    errors = []
    base = os.path.basename(filepath).lower()
    path_lower = filepath.lower()
    if "test" in path_lower:
        return errors
    if filepath.endswith(".py"):
        if any(x in base for x in ["event", "webhook", "publish", "subscribe", "kafka", "redis", "rabbitmq", "broker"]):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                # Enforce publishing/subscribing or event broker checks
                if not any(x in content.lower() for x in ["publish", "subscribe", "emit", "enqueue", "redis", "kafka", "rabbitmq", "event", "broker"]):
                    errors.append({
                        "line": 1,
                        "type": "Layer 19 (Event-Driven Architecture)",
                        "message": f"Event module '{os.path.basename(filepath)}' must use a structured event payload publisher, consumer, or queue broker."
                    })
            except Exception as e:
                errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

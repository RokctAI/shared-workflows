import os
from compliance.base import register_file_checker

@register_file_checker
def check_layer14_agentic_llm_orchestration(filepath):
    errors = []
    base = os.path.basename(filepath).lower()
    if filepath.endswith(".py"):
        if any(x in base for x in ["chat", "engram", "prompt", "completion", "llm_service"]):
            if "test" in base:
                return errors
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                # 1. Prompt template checks
                if not any(x in content.lower() for x in ["template", "system_prompt", "system_message", "format_prompt", "role"]):
                    errors.append({
                        "line": 1,
                        "type": "Layer 14 (Agentic & LLM Orchestration)",
                        "message": f"LLM/Agentic service '{os.path.basename(filepath)}' lacks structured prompt templates or role context separation."
                    })
                # 2. Token / context limits checks
                if not any(x in content.lower() for x in ["token", "budget", "max_tokens", "context_window", "count_tokens"]):
                    errors.append({
                        "line": 1,
                        "type": "Layer 14 (Agentic & LLM Orchestration)",
                        "message": f"LLM/Agentic service '{os.path.basename(filepath)}' fails to implement active token limits or context window budget controls."
                    })
                # 3. Fallback checks
                if not any(x in content.lower() for x in ["fallback", "alt_model", "retry", "except", "failover"]):
                    errors.append({
                        "line": 1,
                        "type": "Layer 14 (Agentic & LLM Orchestration)",
                        "message": f"LLM/Agentic service '{os.path.basename(filepath)}' lacks resilient model fallback, failover models, or try-except exception handling strategies."
                    })
            except Exception as e:
                errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

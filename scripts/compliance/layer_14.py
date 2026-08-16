# Copyright (c) 2026 RokctAI
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

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

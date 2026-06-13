import ast
import os
from compliance.base import register_ast_call, register_file_checker

@register_ast_call
def check_layer15_http_timeout(visitor, node):
    path_parts = visitor.filename.replace("\\", "/").split("/")
    if "test" in visitor.filename.lower() or "compliance" in visitor.filename.lower() or ".rokct" in path_parts:
        return

    is_http_call = False
    func_name = "urlopen"
    if isinstance(node.func, ast.Attribute):
        if isinstance(node.func.value, ast.Name) and node.func.value.id == "requests":
            if node.func.attr in ["get", "post", "put", "delete", "patch", "request"]:
                is_http_call = True
                func_name = f"requests.{node.func.attr}"
        elif isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "request":
            if isinstance(node.func.value.value, ast.Name) and node.func.value.value.id == "urllib":
                if node.func.attr == "urlopen":
                    is_http_call = True
                    func_name = "urllib.request.urlopen"
    elif isinstance(node.func, ast.Name) and node.func.id == "urlopen":
        is_http_call = True
        func_name = "urlopen"
    
    if is_http_call:
        has_timeout = False
        for kw in node.keywords:
            if kw.arg == "timeout":
                has_timeout = True
                break
        if not has_timeout:
            visitor.errors.append({
                "line": node.lineno,
                "type": "Layer 15 (Webhook & Integration Federation)",
                "message": f"Outgoing HTTP request '{func_name}()' lacks a mandatory 'timeout' parameter to prevent hanging threads."
            })

@register_file_checker
def check_layer15_webhook_federation(filepath):
    errors = []
    base = os.path.basename(filepath).lower()
    path_lower = filepath.lower()
    if "webhook" in base or "webhook" in path_lower:
        if any(x in base for x in ["test", "fixture", "json", "yaml", "yml", "md", "txt"]):
            return errors
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            required_sigs = ["signature", "hmac", "sha256", "verification", "x-hub-signature", "x-signature", "verify_signature", "verify"]
            if not any(sig in content.lower() for sig in required_sigs):
                errors.append({
                    "line": 1,
                    "type": "Layer 15 (Webhook Federation)",
                    "message": f"Webhook handler file '{os.path.basename(filepath)}' does not implement payload signature, HMAC verification, or secret verification hashes to prevent unauthorized spoofing."
                })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

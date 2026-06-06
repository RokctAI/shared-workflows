import ast
import os
from compliance.base import register_ast_function_def, register_file_checker

@register_ast_function_def
def check_layer2_function_def(visitor, node):
    is_whitelisted = False
    for dec in node.decorator_list:
        if isinstance(dec, ast.Name) and dec.id == "whitelist":
            is_whitelisted = True
        elif isinstance(dec, ast.Attribute) and dec.attr == "whitelist":
            is_whitelisted = True
        elif isinstance(dec, ast.Call):
            func = dec.func
            if isinstance(func, ast.Name) and func.id == "whitelist":
                is_whitelisted = True
            elif isinstance(func, ast.Attribute) and func.attr == "whitelist":
                is_whitelisted = True
    
    if is_whitelisted:
        path_normalized = visitor.filename.replace("\\", "/").lower()
        known_api_paths = [
            "/api/auth/",
            "/api/brain/",
            "/api/plan_builder/",
            "/api/setup/",
            "/betassist/api",     # BetAssist REST API
        ]
        if not any(x in path_normalized for x in known_api_paths):
            # FIX: Do NOT silently pass. Warn that this whitelisted function
            # is in an unrecognised path and has not been layer-2 verified.
            visitor.errors.append({
                "line": node.lineno,
                "type": "Layer 2 (Unknown API Path)",
                "message": (
                    f"@frappe.whitelist function '{node.name}()' is defined outside all known "
                    f"API paths {known_api_paths}. Layer 2 type-safety checks were skipped. "
                    f"Move this function into a registered API path or add its path to layer_2.py."
                )
            })
            is_whitelisted = False
    
    if is_whitelisted:
        # Type-safety & Documentation (Layer 2)
        docstring = ast.get_docstring(node)
        if not docstring or not docstring.strip():
            visitor.errors.append({
                "line": node.lineno,
                "type": "Layer 2 (API/Documentation)",
                "message": f"whitelisted function '{node.name}()' must have a non-empty descriptive docstring."
            })

        # Verify parameter annotations
        for arg in node.args.args:
            if arg.arg in ["self", "cls"]:
                continue
            if not arg.annotation:
                visitor.errors.append({
                    "line": node.lineno,
                    "type": "Layer 2 (API/Type Safety)",
                    "message": f"whitelisted parameter '{arg.arg}' in '{node.name}()' lacks a type-hint annotation."
                })

        # Verify return annotation
        if not node.returns:
            visitor.errors.append({
                "line": node.lineno,
                "type": "Layer 2 (API/Type Safety)",
                "message": f"whitelisted function '{node.name}()' lacks a return type-hint annotation (e.g. -> dict)."
            })

@register_file_checker
def check_layer2_flutter_dynamic(filepath):
    errors = []
    if filepath.endswith(".dart"):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()
                
            for idx, line in enumerate(lines, 1):
                if " dynamic " in line or "dynamic>" in line:
                    if not line.strip().startswith("//") and not line.strip().startswith("*") and not line.strip().startswith("///"):
                        errors.append({
                            "line": idx,
                            "type": "Layer 2 (Type Safety - Flutter)",
                            "message": f"Avoid using raw 'dynamic' types in Flutter '{os.path.basename(filepath)}'. Define concrete Dart models or strong types."
                        })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

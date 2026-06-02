import ast
import os
from compliance.base import register_ast_function_def, register_ast_call, register_file_checker

@register_ast_function_def
def check_layer12_observability(visitor, node):
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
        if not any(x in path_normalized for x in ["/api/auth/", "/api/brain/", "/api/plan_builder/", "/api/setup/"]):
            is_whitelisted = False
            
    if is_whitelisted:
        has_trace_id = False
        has_stderr = False

        for subnode in ast.walk(node):
            if isinstance(subnode, ast.Name) and subnode.id == "trace_id":
                has_trace_id = True
            if isinstance(subnode, ast.Constant) and isinstance(subnode.value, str):
                val_lower = subnode.value.lower()
                if "x-trace-id" in val_lower or "x-request-id" in val_lower or "trace_id" in val_lower:
                    has_trace_id = True
            if isinstance(subnode, ast.Attribute) and subnode.attr == "stderr":
                has_stderr = True
            if isinstance(subnode, ast.Name) and subnode.id == "stderr":
                has_stderr = True

        if not has_trace_id or not has_stderr:
            missing = []
            if not has_trace_id:
                missing.append("Layer 12: Trace ID propagation")
            if not has_stderr:
                missing.append("Layer 12: sys.stderr structured logging")
            visitor.errors.append({
                "line": node.lineno,
                "type": "Layer 12 (Observability)",
                "message": f"whitelisted function '{node.name}()' lacks: {', '.join(missing)}"
            })

@register_ast_call
def check_layer12_db_tracing(visitor, node):
    is_frappe_db_call = False
    if isinstance(node.func, ast.Attribute):
        if isinstance(node.func.value, ast.Name) and node.func.value.id == "frappe":
            if node.func.attr in ["get_doc", "get_all", "get_list", "get_last_doc", "get_value", "set_value"]:
                is_frappe_db_call = True
        elif isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "db":
            if isinstance(node.func.value.value, ast.Name) and node.func.value.value.id == "frappe":
                if node.func.attr in ["get_list", "get_all", "get_value", "set_value", "exists", "count"]:
                    is_frappe_db_call = True

    if is_frappe_db_call and len(node.args) > 0:
        path_lower = visitor.filename.lower()
        if "test" in path_lower:
            pass
        else:
            first_arg = node.args[0]
            if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                doctype_val = first_arg.value
                if doctype_val in ["User", "Company", "Employee", "Customer"]:
                    has_trace = False
                    if visitor.current_function:
                        # Check docstring for override comment or trace references
                        docstring = ast.get_docstring(visitor.current_function)
                        if docstring and any(x in docstring.lower() for x in ["trace", "tenant", "bypass", "compliance", "hook", "event", "cron", "setup"]):
                            has_trace = True
                        else:
                            for subnode in ast.walk(visitor.current_function):
                                if isinstance(subnode, ast.Name) and subnode.id in ["trace_id", "trace"]:
                                    has_trace = True
                                if isinstance(subnode, ast.Constant) and isinstance(subnode.value, str):
                                    val_lower = subnode.value.lower()
                                    if any(x in val_lower for x in ["trace_id", "trace-id", "x-trace-id"]):
                                        has_trace = True
                    
                    if not has_trace:
                        visitor.errors.append({
                            "line": node.lineno,
                            "type": "Layer 12 (Observability - DB Tracing)",
                            "message": f"Database query to standard DocType '{doctype_val}' in function '{visitor.current_function.name if visitor.current_function else 'global'}' lacks Trace ID propagation context."
                        })

@register_file_checker
def check_layer12_flutter_observability(filepath):
    errors = []
    if filepath.endswith(".dart"):
        if "api" in filepath.lower() or "service" in filepath.lower():
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                if "x-trace-id" not in content.lower() and "trace" not in content.lower() and "requestid" not in content.lower():
                    errors.append({
                        "line": 1,
                        "type": "Layer 12 (Observability - Flutter)",
                        "message": f"Flutter API/Service layer '{os.path.basename(filepath)}' fails to propagate structured Trace/Request IDs in outgoing network header maps."
                    })
            except Exception as e:
                errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

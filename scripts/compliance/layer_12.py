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
        known_api_paths = [
            "/api/auth/",
            "/api/brain/",
            "/api/plan_builder/",
            "/api/setup/",
            "/betassist/api",     # BetAssist REST API
        ]
        if not any(x in path_normalized for x in known_api_paths):
            # FIX: Do NOT silently pass. Warn that this whitelisted function
            # is in an unrecognised path and has not been layer-12 verified.
            visitor.errors.append({
                "line": node.lineno,
                "type": "Layer 12 (Unknown API Path - Observability Skipped)",
                "message": (
                    f"@frappe.whitelist function '{node.name}()' is outside all known API paths "
                    f"{known_api_paths}. Layer 12 observability checks were skipped. "
                    f"Move this function into a registered API path or add its path to layer_12.py."
                )
            })
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
        # Old check: only triggered on files named *api* or *service* — too narrow.
        # Fixed: trigger on ANY Dart file that makes outgoing HTTP calls.
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            makes_http_calls = any(pkg in content for pkg in [
                "package:http/", "package:dio/", "HttpClient", "Uri.https", "Uri.http"
            ])
            is_api_or_service = any(x in filepath.lower() for x in ["api", "service", "repository", "remote"])
            if makes_http_calls or is_api_or_service:
                if "x-trace-id" not in content.lower() and "trace" not in content.lower() and "requestid" not in content.lower():
                    errors.append({
                        "line": 1,
                        "type": "Layer 12 (Observability - Flutter Trace ID)",
                        "message": f"Flutter file '{os.path.basename(filepath)}' makes outgoing HTTP calls but fails to propagate a structured Trace/Request ID in outgoing network headers."
                    })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors
@register_file_checker
def check_layer12_flutter_crash_reporting(filepath):
    """Enforce crash/error reporting SDK integration in Flutter app entrypoints."""
    errors = []
    if filepath.endswith(".dart") and os.path.basename(filepath) == "main.dart":
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            has_crash_reporting = any(x in content.lower() for x in [
                "firebase_crashlytics", "sentry", "crashlytics", "fluttererror",
                "platformdispatcher", "recorderror", "captureerception"
            ])
            if not has_crash_reporting:
                errors.append({
                    "line": 1,
                    "type": "Layer 12 (Observability - Crash Reporting)",
                    "message": f"Flutter entrypoint '{os.path.basename(filepath)}' lacks crash/error reporting integration. Integrate Firebase Crashlytics or Sentry to capture unhandled exceptions in production."
                })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

@register_file_checker
def check_layer12_flutter_analytics(filepath):
    """Enforce analytics event tracking in Flutter screens and key user action handlers."""
    errors = []
    if filepath.endswith(".dart") and os.path.basename(filepath) == "main.dart":
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            has_analytics = any(x in content.lower() for x in [
                "firebase_analytics", "analytics", "logevent", "log_event",
                "amplitude", "mixpanel", "posthog", "segment"
            ])
            if not has_analytics:
                errors.append({
                    "line": 1,
                    "type": "Layer 12 (Observability - Analytics)",
                    "message": f"Flutter entrypoint '{os.path.basename(filepath)}' lacks analytics event tracking. Integrate Firebase Analytics or equivalent to track key user actions (bet placed, AR launched, onboarding completed)."
                })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

@register_file_checker
def check_layer12_python_observability(filepath):
    """Enforce Trace ID propagation on Python outgoing HTTP requests."""
    errors = []
    if filepath.endswith(".py"):
        path_parts = filepath.replace("\\", "/").split("/")
        if "test" in filepath.lower() or "compliance" in filepath.lower() or ".rokct" in path_parts:
            return errors
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            makes_http = any(x in content for x in ["urllib.request", "requests.get", "requests.post", "requests.put", "requests.delete", "requests.request"])
            if makes_http:
                if "x-trace-id" not in content.lower() and "trace-id" not in content.lower() and "trace_id" not in content.lower() and "traceid" not in content.lower():
                    errors.append({
                        "line": 1,
                        "type": "Layer 12 (Observability - Python Trace ID)",
                        "message": f"Python file '{os.path.basename(filepath)}' makes outgoing HTTP calls but fails to propagate a structured Trace/Request ID in outgoing network headers."
                    })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

@register_file_checker
def check_layer15_flutter_http_timeout(filepath):
    """Enforce timeout configuration on Dart/Flutter HTTP clients."""
    errors = []
    if filepath.endswith(".dart"):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            # Skip interceptor files – they import Dio but don't configure the client.
            # Timeouts must be set on the Dio BaseOptions in HttpService, not here.
            if "interceptor" in os.path.basename(filepath).lower():
                return errors
            uses_http = any(pkg in content for pkg in ["package:http/", "package:dio/", "HttpClient("])
            if uses_http:
                has_timeout = any(x in content.lower() for x in [
                    "timeout", "connectiontimeout", "receivetimeout", "sendtimeout"
                ])
                if not has_timeout:
                    errors.append({
                        "line": 1,
                        "type": "Layer 15 (Webhook & Integration - Flutter HTTP Timeout)",
                        "message": f"Flutter file '{os.path.basename(filepath)}' uses an HTTP client (http/dio) but configures no timeout. Set connectTimeout and receiveTimeout to prevent hanging requests."
                    })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

@register_file_checker
def check_gravity_error_reporting(filepath):
    """Enforce that Gravity workspace mutation actions report errors to Control."""
    errors = []
    normalized_path = filepath.replace("\\", "/").lower()
    if normalized_path.endswith(".py") and "/gravity/" in normalized_path:
        # Exclude setup, test files, configs
        if any(x in normalized_path for x in ["test", "setup", "config.py", "git_ops.py", "cli.py"]):
            return errors
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            # If the file defines push/write handlers, it must call send_error_to_control on exception
            if "push_workspace" in content or "write_workspace_file" in content:
                if "send_error_to_control" not in content:
                    errors.append({
                        "line": 1,
                        "type": "Layer 12 (Observability - Gravity Error Reporting)",
                        "message": f"Gravity source file '{os.path.basename(filepath)}' processes workspace mutations but lacks central error telemetry to Control. Integrate send_error_to_control() inside try/except blocks."
                    })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors



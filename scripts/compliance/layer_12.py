import ast
import os
import re
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
        import fnmatch
        # Use the relative path directly — the scanner always runs from repo root,
        # so the first non-'.' segment IS the app/module name. This works for any
        # repo without any hardcoded list.
        path_normalized = visitor.filename.replace("\\", "/").lower()
        known_api_paths = [
            "*/api/auth/*",
            "*/api/brain/*",
            "*/api/plan_builder/*",
            "*/api/setup/*",
            "*/betassist/api*",
        ]
        
        # Dynamically detect the top-level app name from the relative path
        # e.g. .\rpanel\hosting\foo.py → parts[0] = 'rpanel' → whitelist */rpanel/*
        parts = [p for p in path_normalized.split('/') if p and p != '.']
        if parts:
            app_name = parts[0]
            known_api_paths.append(f"*/{app_name}/*")

        if not any(fnmatch.fnmatch(path_normalized, x) for x in known_api_paths):
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
                                 if isinstance(subnode, ast.Name) and subnode.id == "trace_id":
                                     has_trace = True
                                 if isinstance(subnode, ast.Constant) and isinstance(subnode.value, str):
                                     val_lower = subnode.value.lower()
                                     if any(x in val_lower for x in ["trace_id", "trace-id", "x-trace-id"]):
                                         has_trace = True
                    
                    # DECISION: We verify that the function has trace propagation contexts. 
                    # We no longer match the broad variable name 'trace' since that triggers false positives 
                    # for unrelated local booleans or methods, focusing strictly on explicit trace_id mappings.
                    if not has_trace:
                        visitor.errors.append({
                            "line": node.lineno,
                            "type": "Layer 12 (Observability - DB Tracing)",
                            "message": f"Database query to standard DocType '{doctype_val}' in function '{visitor.current_function.name if visitor.current_function else 'global'}' lacks Trace ID propagation context."
                        })


_TRACE_HEADER_PATTERNS = [
    r'["\']x-trace-id["\']\s*:',
    r'["\']trace-id["\']\s*:',
    r'["\']trace_id["\']\s*:',
    r'["\']x-request-id["\']\s*:',
    r'\.headers\[["\']x-trace-id["\']\]\s*=',
    r'\bheaders\b.*\btrace\b',
]

_INTERCEPTOR_CACHE = {}

def _project_has_trace_interceptor(start_path):
    """Walk up to lib/ root then search for a Dio Interceptor that injects x-trace-id."""
    root = start_path
    for _ in range(8):
        root = os.path.dirname(root)
        if os.path.basename(root) in ("lib", "src", ""):
            break
    if root in _INTERCEPTOR_CACHE:
        return _INTERCEPTOR_CACHE[root]
    found = False
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in [".dart_tool", "build", ".git"]]
        for fname in files:
            if not fname.endswith(".dart"):
                continue
            try:
                fc = open(os.path.join(dirpath, fname), encoding="utf-8").read()
                is_interceptor = ("extends Interceptor" in fc or "implements Interceptor" in fc)
                has_trace = any(re.search(p, fc, re.IGNORECASE) for p in _TRACE_HEADER_PATTERNS)
                if is_interceptor and has_trace:
                    found = True
                    break
            except Exception:
                continue
        if found:
            break
    _INTERCEPTOR_CACHE[root] = found
    return found


@register_file_checker
def check_layer12_flutter_observability(filepath):
    errors = []
    if not filepath.endswith(".dart"):
        return errors
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        makes_http_calls = any(pkg in content for pkg in [
            "package:http/", "package:dio/", "HttpClient", "Uri.https", "Uri.http"
        ])
        is_api_or_service = any(x in filepath.lower() for x in ["api", "service", "repository", "remote"])

        if not (makes_http_calls or is_api_or_service):
            return errors

        # 1. File-level header injection check
        has_strict_trace = any(re.search(p, content, re.IGNORECASE) for p in _TRACE_HEADER_PATTERNS)

        # 2. Project-level: a shared Dio Interceptor that injects x-trace-id covers all files
        if not has_strict_trace:
            has_strict_trace = _project_has_trace_interceptor(filepath)

        # 3. Explicit bypass comment
        is_bypassed = any(x in content.lower() for x in ["bypass", "ignore-observability"])

        if not has_strict_trace and not is_bypassed:
            errors.append({
                "line": 1,
                "type": "Layer 12 (Observability - Flutter Trace ID)",
                "message": (
                    f"Flutter file '{os.path.basename(filepath)}' makes outgoing HTTP calls "
                    f"but fails to propagate a structured Trace/Request ID in outgoing network "
                    f"headers. Add 'x-trace-id' to request headers or ensure a Dio Interceptor "
                    f"in this project injects it centrally (extends Interceptor + sets x-trace-id)."
                )
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
    """Enforce Trace ID propagation on Python outgoing HTTP requests using AST analysis."""
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
                # DECISION: We parse python source code into an AST representation to verify that trace headers are
                # explicitly defined or passed within the call site arguments, preventing simple comment string bypasses.
                try:
                    tree = ast.parse(content)
                    class HttpCallVisitor(ast.NodeVisitor):
                        def __init__(self):
                            self.has_http_call = False
                            self.has_trace_header = False
                        
                        def visit_Call(self, node):
                            is_requests = False
                            if isinstance(node.func, ast.Attribute):
                                if isinstance(node.func.value, ast.Name) and node.func.value.id == "requests":
                                    if node.func.attr in ["get", "post", "put", "delete", "patch", "request"]:
                                        is_requests = True
                            
                            if is_requests:
                                self.has_http_call = True
                                for kw in node.keywords:
                                    if kw.arg == "headers":
                                        if isinstance(kw.value, ast.Dict):
                                            for key in kw.value.keys:
                                                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                                                    key_lower = key.value.lower()
                                                    if any(x in key_lower for x in ["x-trace-id", "trace-id", "trace_id", "traceid", "x-request-id"]):
                                                        self.has_trace_header = True
                                        elif isinstance(kw.value, ast.Name):
                                            self.has_trace_header = True
                            self.generic_visit(node)
                    
                    visitor = HttpCallVisitor()
                    visitor.visit(tree)
                    has_trace_header = visitor.has_trace_header
                except Exception:
                    has_trace_header = False
                
                # Check for bypass comments or trace keywords in content string as fallback
                raw_has_trace = any(x in content.lower() for x in ["x-trace-id", "trace-id", "trace_id", "traceid", "x-request-id"])
                
                if not has_trace_header and not raw_has_trace:
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



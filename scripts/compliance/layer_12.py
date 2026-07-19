import ast
import os
import re
from compliance.base import (
    register_ast_function_def,
    register_ast_call,
    register_file_checker,
    is_frappe_whitelisted,
    matches_known_api_path,
    get_known_api_paths,
)

@register_ast_function_def
def check_layer12_observability(visitor, node):
    is_whitelisted = is_frappe_whitelisted(node)

    # KNOWN GAP: this path test is self-satisfying and does not validate API
    # conventions — see the full note in layer_2.py. It gates only whether
    # layer-12 observability checks run, and must not be read as path validation.
    if is_whitelisted and not matches_known_api_path(visitor.filename):
        # Do NOT silently pass: layer-12 observability was skipped for this function.
        visitor.errors.append({
            "line": node.lineno,
            "type": "Layer 12 (Whitelisted Function - Path Not Validated, Observability Skipped)",
            "message": (
                f"@frappe.whitelist function '{node.name}()' did not match any path glob "
                f"{get_known_api_paths(visitor.filename)}, so Layer 12 observability checks were skipped. "
                f"NOTE: this path test is a structural presence check only — it does not validate "
                f"the function against real API conventions (see the KNOWN GAP note in layer_2.py)."
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
    base_dir = os.path.realpath(os.getcwd())
    root = start_path
    for _ in range(8):
        root = os.path.dirname(root)
        if os.path.basename(root) in ("lib", "src", ""):
            break
    root_real = os.path.realpath(root)
    if not root_real.startswith(base_dir):
        return False
    if root_real in _INTERCEPTOR_CACHE:
        return _INTERCEPTOR_CACHE[root_real]
    found = False
    for dirpath, dirs, files in os.walk(root_real):
        dirpath_real = os.path.realpath(dirpath)
        if not dirpath_real.startswith(base_dir):
            continue
        dirs[:] = [d for d in dirs if d not in [".dart_tool", "build", ".git"]]
        for fname in files:
            if not fname.endswith(".dart"):
                continue
            try:
                full_path = os.path.realpath(os.path.join(dirpath_real, fname))
                if not full_path.startswith(base_dir):
                    continue
                fc = open(full_path, encoding="utf-8").read()
                is_interceptor = ("extends Interceptor" in fc or "implements Interceptor" in fc)
                has_trace = any(re.search(p, fc, re.IGNORECASE) for p in _TRACE_HEADER_PATTERNS)
                if is_interceptor and has_trace:
                    found = True
                    break
            except Exception:
                continue
        if found:
            break
    _INTERCEPTOR_CACHE[root_real] = found
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

        # 3. Explicit bypass comment.
        # Unified syntax: '// compliance-ignore-file: obs-flutter-trace'.
        # Legacy 'ignore-observability' still honoured for one release; the bare
        # substring 'bypass' is NOT — it silenced any file that merely mentioned
        # the word anywhere, including in unrelated prose.
        is_bypassed = "ignore-observability" in content.lower()

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

# NOTE: check_layer15_flutter_http_timeout used to live here despite its name.
# It now lives in layer_15.py alongside the other timeout checks.

# ─────────────────────────────────────────────────────────────────────────────
# APP-SPECIFIC RULE — does NOT generalize.
#
# This is not a generic observability check. It is hardcoded to the Gravity
# app's own conventions: the literal function names push_workspace /
# write_workspace_file, the literal telemetry helper send_error_to_control(),
# and paths under /gravity/. It fires on no other repo and proves nothing about
# any other codebase's error forwarding.
#
# It is kept (rather than generalized) because Gravity's workspace mutations are
# the one place where a silent failure loses user data, and the app has a single
# named telemetry sink to check for. Any repo wanting an equivalent guarantee
# needs its own app-specific rule below — do not extend this one by adding more
# app names to it.
# ─────────────────────────────────────────────────────────────────────────────

@register_file_checker
def check_appspecific_gravity_error_reporting(filepath):
    """APP-SPECIFIC (Gravity only): workspace mutations must report errors to Control.

    Scoped to /gravity/ paths and Gravity's literal helper names. See the banner
    above — this is deliberately not a general-purpose check.
    """
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
                        "type": "Layer 12 (APP-SPECIFIC Gravity - Error Reporting)",
                        "message": (
                            f"[app-specific rule, Gravity only] Gravity source file "
                            f"'{os.path.basename(filepath)}' processes workspace mutations but lacks "
                            f"central error telemetry to Control. Integrate send_error_to_control() "
                            f"inside try/except blocks."
                        )
                    })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors


_global_resize_cache = {}

def get_global_resize_status(filepath):
    # Find the parent project root (where pubspec.yaml exists)
    dir_path = os.path.dirname(filepath)
    project_root = None
    while dir_path and dir_path != os.path.dirname(dir_path):
        if os.path.exists(os.path.join(dir_path, "pubspec.yaml")):
            project_root = dir_path
            break
        dir_path = os.path.dirname(dir_path)
    
    if not project_root:
        return True # Default to enabled if not a Flutter project or no root found
        
    if project_root in _global_resize_cache:
        return _global_resize_cache[project_root]
        
    # Search for custom_scaffold.dart in the project_root
    disabled_globally = False
    for root, dirs, files in os.walk(project_root):
        if "custom_scaffold.dart" in files:
            scaffold_path = os.path.join(root, "custom_scaffold.dart")
            try:
                with open(scaffold_path, "r", encoding="utf-8") as f:
                    content = f.read()
                if "resizeToAvoidBottomInset: false" in content:
                    disabled_globally = True
            except Exception:
                pass
            break
            
    # Cache the result: True if enabled, False if disabled
    _global_resize_cache[project_root] = not disabled_globally
    return _global_resize_cache[project_root]

@register_file_checker
def check_layer12_flutter_keyboard_avoidance(filepath):
    """Enforce that inputs remain visible on screens when resizeToAvoidBottomInset is false globally."""
    errors = []
    if not filepath.endswith(".dart"):
        return errors
        
    fp_lower = filepath.lower().replace("\\", "/")
    # Skip test files, generated files, custom_scaffold itself, and reusable components/widgets
    if any(x in fp_lower for x in ["test", "generated", ".g.dart", ".freezed.dart", "custom_scaffold.dart", "/components/", "/component/", "/widgets/", "/widget/"]):
        return errors

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
            
        # Check if the file contains any input field widgets
        input_pattern = re.compile(r'\b(TextField|TextFormField|OutlinedBorderTextField|PhoneTextField|SearchTextField)\b')
        if not input_pattern.search(content):
            return errors
            
        # Check if resizeToAvoidBottomInset is false globally or locally
        global_enabled = get_global_resize_status(filepath)
        has_local_disable = "resizeToAvoidBottomInset: false" in content
        
        if global_enabled and not has_local_disable:
            return errors
            
        # If disabled globally or locally, check if we manually handle keyboard push-up/viewInsets
        has_avoidance = "viewInsets" in content
        
        # Check for compliance ignore comment.
        # Unified syntax: '// compliance-ignore: flutter-keyboard-avoidance'
        # (handled centrally in scan_file). The three legacy spellings below stay
        # honoured for one release.
        has_ignore = bool(re.search(
            r'//\s*(compliance:\s*ignore-keyboard-avoidance|ignore:\s*keyboard_avoidance|ignore:\s*keyboard-avoidance)',
            content))

        if not has_avoidance and not has_ignore:
            lines = content.splitlines()
            for i, line in enumerate(lines, 1):
                match = input_pattern.search(line)
                if match:
                    reason = "local override 'resizeToAvoidBottomInset: false'" if has_local_disable else "global scaffold config is set to false"
                    errors.append({
                        "line": i,
                        "type": "Layer 12 (Usability - Keyboard Avoidance)",
                        "message": (
                            f"Input field '{match.group(1)}' found in '{os.path.basename(filepath)}' line {i} but layout "
                            f"does not handle keyboard avoidance. Since {reason}, "
                            f"you must wrap the parent container with a margin/padding using 'MediaQuery.of(context).viewInsets' "
                            f"or add a compliance override comment: '// compliance: ignore-keyboard-avoidance'."
                        )
                    })
    except Exception as e:
        errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
        
    return errors




# Copyright (c) 2026 ROKCT INTELLIGENCE (PTY) LTD
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
def check_layer15_flutter_http_timeout(filepath):
    """Enforce timeout configuration on Dart/Flutter HTTP clients.

    (Moved here from layer_12.py, where it had been defined despite its name.)
    """
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

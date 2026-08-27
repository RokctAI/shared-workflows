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
from compliance.base import (
    register_ast_function_def,
    register_file_checker,
    is_frappe_whitelisted,
    matches_known_api_path,
    get_known_api_paths,
)

# ─────────────────────────────────────────────────────────────────────────────
# KNOWN GAP — this path test does NOT validate API conventions.
#
# matches_known_api_path() appends a glob derived from the file's OWN first path
# segment (*/<parts[0]>/*), which therefore always matches its own file whenever
# the path has two or more segments. The test is self-satisfying: it passes for
# any nested file, including ones in no module and no api/ directory at all.
# In practice it only fires for a whitelisted function in a file at the repo root.
#
# Measured: all 39 whitelisted files in the agent/ repo pass this test, and zero
# of them match KNOWN_API_PATHS — every one passes on the derived glob alone.
#
# The leniency is deliberate for now. Gating on real endpoint conventions is a
# fleet-wide policy decision pending review, not a scanner fix. Until then this
# is labelled as a structural presence check so it cannot be read as "this
# function's API path was verified" — because it was not.
# ─────────────────────────────────────────────────────────────────────────────

@register_ast_function_def
def check_layer2_function_def(visitor, node):
    is_whitelisted = is_frappe_whitelisted(node)

    if is_whitelisted and not matches_known_api_path(visitor.filename):
        # Do NOT silently pass: layer-2 type safety was skipped for this function.
        visitor.errors.append({
            "line": node.lineno,
            "type": "Layer 2 (Whitelisted Function - Path Not Validated)",
            "message": (
                f"@frappe.whitelist function '{node.name}()' did not match any path glob "
                f"{get_known_api_paths(visitor.filename)}, so Layer 2 type-safety checks were skipped. "
                f"NOTE: this path test is a structural presence check only — it does not validate "
                f"the function against real API conventions (see the KNOWN GAP note in layer_2.py). "
                f"A passing path test does NOT mean the endpoint lives somewhere appropriate."
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

@register_file_checker
def check_layer2_no_python_in_special_dirs(filepath):
    errors = []
    if filepath.endswith(".py"):
        # Unified syntax: '# compliance-ignore-file: structural-special-dirs'
        # (handled centrally in scan_file). Legacy '# compliance-silent' — which
        # silenced this check only — stays honoured for one release.
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                if "# compliance-silent" in f.read():
                    return []
        except Exception:
            pass
        normalized = filepath.replace("\\", "/")
        for forbidden in [".github/", ".rokct/"]:
            if forbidden in normalized:
                errors.append({
                    "line": 1,
                    "type": "Layer 2 (Structural)",
                    "message": f"Python files are forbidden under {forbidden}. Move scripts to allowed directories."
                })
                break
    return errors

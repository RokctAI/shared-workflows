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

import ast
import os
import sys
import subprocess
from compliance.base import register_ast_call

@register_ast_call
def check_layer3_sql_injection(visitor, node):
    is_db_sql = False
    if isinstance(node.func, ast.Attribute):
        if node.func.attr == "sql":
            if isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "db":
                if isinstance(node.func.value.value, ast.Name) and node.func.value.value.id == "frappe":
                    is_db_sql = True
    
    if is_db_sql:
        # Unified syntax: '# compliance-ignore: sql-injection' (handled centrally
        # in scan_file). The legacy docstring keywords below stay honoured for one
        # release.
        bypassed = False
        if visitor.current_function:
            docstring = ast.get_docstring(visitor.current_function)
            if docstring and any(x in docstring.lower() for x in ["bypass_sql", "raw_sql", "complex_query"]):
                bypassed = True

        if not bypassed:
            visitor.errors.append({
                "line": node.lineno,
                "type": "Layer 3 (Database / ORM Enforcement)",
                "message": "Raw SQL query `frappe.db.sql()` detected. Use Frappe ORM (`frappe.get_all()`, `frappe.get_list()`, etc.) instead to ensure database compatibility (MariaDB/PostgreSQL/SQLite) and automatic SQL injection safety. If raw SQL is strictly required, suppress with '# compliance-ignore: sql-injection'."
            })

def check_database_migrations(changed_files):
    """
    LAYER 3: Verify that structural DocType changes are accompanied by DB migration patch files.
    """
    errors = []
    actual_changed = []
    if len(sys.argv) == 1:
        cwd_dir = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        # DECISION: We explicitly validate that cwd_dir is a trusted repository root containing a .git folder.
        # Fall back to current directory only if it also contains a valid .git folder, otherwise abort command execution.
        # This prevents command injection vulnerabilities in shared environments where working directories could be manipulated.
        is_trusted = os.path.isdir(cwd_dir) and os.path.exists(os.path.join(cwd_dir, ".git"))
        if not is_trusted:
            cwd_dir = os.path.abspath(".")
            if not os.path.exists(os.path.join(cwd_dir, ".git")):
                return errors  # Safe abort: do not run git commands in untrusted directories
        try:
            # DECISION: Pass -c core.hooksPath=/dev/null to git subprocesses to disable custom hook execution and prevent arbitrary code injection.
            out = subprocess.check_output(["git", "-c", "core.hooksPath=/dev/null", "status", "--porcelain"], cwd=cwd_dir, stderr=subprocess.DEVNULL).decode("utf-8")
            for line in out.splitlines():
                if len(line) > 3:
                    file_path = line[3:].strip()
                    actual_changed.append(file_path)
            # Check latest commit diff (e.g. for CI runs where changes are committed)
            out_diff = subprocess.check_output(["git", "-c", "core.hooksPath=/dev/null", "diff", "--name-only", "HEAD~1"], cwd=cwd_dir, stderr=subprocess.DEVNULL).decode("utf-8")
            for line in out_diff.splitlines():
                actual_changed.append(line.strip())
        except Exception:
            pass
    else:
        actual_changed = changed_files

    if not actual_changed:
        return errors

    doctype_changed = False
    patch_changed = False

    for file in actual_changed:
        if "doctype" in file and file.endswith(".json"):
            doctype_changed = True
        if "patches" in file or "migrations" in file or "patch" in file.lower():
            patch_changed = True

    if doctype_changed and not patch_changed:
        errors.append({
            "line": 1,
            "type": "Layer 3 (Database Integrity)",
            "message": "DocType schema JSON metadata files were modified, but no database migration scripts (under patches/ or migrations/) were found to handle state migration."
        })
    return errors

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
    
    if is_db_sql and len(node.args) > 0:
        sql_arg = node.args[0]
        is_unsafe = False
        # Check for f-strings: ast.JoinedStr
        if isinstance(sql_arg, ast.JoinedStr):
            is_unsafe = True
        # Check for % formatting
        elif isinstance(sql_arg, ast.BinOp) and isinstance(sql_arg.op, ast.Mod):
            is_unsafe = True
        # Check for .format() calls
        elif isinstance(sql_arg, ast.Call) and isinstance(sql_arg.func, ast.Attribute) and sql_arg.func.attr == "format":
            is_unsafe = True
        
        if is_unsafe:
            visitor.errors.append({
                "line": node.lineno,
                "type": "Layer 3 (Database / SQL Injection)",
                "message": "Unsafe raw SQL query detected. Avoid using f-strings, %, or .format() in frappe.db.sql(). Use parameterized inputs instead (e.g., frappe.db.sql('SELECT * FROM tabUser WHERE name = %s', user))."
            })

def check_database_migrations(changed_files):
    """
    LAYER 3: Verify that structural DocType changes are accompanied by DB migration patch files.
    """
    errors = []
    actual_changed = []
    if len(sys.argv) == 1:
        try:
            # Check uncommitted status changes
            out = subprocess.check_output(["git", "status", "--porcelain"], stderr=subprocess.DEVNULL).decode("utf-8")
            for line in out.splitlines():
                if len(line) > 3:
                    file_path = line[3:].strip()
                    actual_changed.append(file_path)
            # Check latest commit diff (e.g. for CI runs where changes are committed)
            out_diff = subprocess.check_output(["git", "diff", "--name-only", "HEAD~1"], stderr=subprocess.DEVNULL).decode("utf-8")
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

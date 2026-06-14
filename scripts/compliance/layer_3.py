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
        bypassed = False
        if visitor.current_function:
            docstring = ast.get_docstring(visitor.current_function)
            if docstring and any(x in docstring.lower() for x in ["bypass_sql", "raw_sql", "complex_query"]):
                bypassed = True

        if not bypassed:
            visitor.errors.append({
                "line": node.lineno,
                "type": "Layer 3 (Database / ORM Enforcement)",
                "message": "Raw SQL query `frappe.db.sql()` detected. Use Frappe ORM (`frappe.get_all()`, `frappe.get_list()`, etc.) instead to ensure database compatibility (MariaDB/PostgreSQL/SQLite) and automatic SQL injection safety. If raw SQL is strictly required, document it in the docstring with 'raw_sql' or 'bypass_sql'."
            })

def check_database_migrations(changed_files):
    """
    LAYER 3: Verify that structural DocType changes are accompanied by DB migration patch files.
    """
    errors = []
    actual_changed = []
    if len(sys.argv) == 1:
        # DECISION: We explicitly resolve the repository root to use as the secure `cwd` 
        # working directory context for Git subprocess operations. This prevents arbitrary execution 
        # vulnerabilities if scripts are invoked from a workspace containing untrusted custom configurations.
        cwd_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if not os.path.exists(os.path.join(cwd_dir, ".git")):
            cwd_dir = "."
        try:
            # Check uncommitted status changes
            out = subprocess.check_output(["git", "status", "--porcelain"], cwd=cwd_dir, stderr=subprocess.DEVNULL).decode("utf-8")
            for line in out.splitlines():
                if len(line) > 3:
                    file_path = line[3:].strip()
                    actual_changed.append(file_path)
            # Check latest commit diff (e.g. for CI runs where changes are committed)
            out_diff = subprocess.check_output(["git", "diff", "--name-only", "HEAD~1"], cwd=cwd_dir, stderr=subprocess.DEVNULL).decode("utf-8")
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

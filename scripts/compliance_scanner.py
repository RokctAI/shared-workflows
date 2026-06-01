#!/usr/bin/env python3
# Copyright 2026 RokctAI
# Compliance Scanner: Programmatically enforces production-grade quality across 5 layers:
# Layer 2 (API/Type Safety), Layer 3 (DB Migrations), Layer 4 & 5 (Security/Secrets Gate),
# Layer 6 (Rate Limiting), and Layer 12 (Observability).

import ast
import sys
import os
import subprocess

class PlatformComplianceVisitor(ast.NodeVisitor):
    def __init__(self, filename):
        self.filename = filename
        self.errors = []

    def visit_FunctionDef(self, node):
        # ==========================================
        # LAYER 12 & LAYER 2: WHITELISTED API ENDPOINTS
        # ==========================================
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
            # 1. Observability (Layer 12)
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
                self.errors.append({
                    "line": node.lineno,
                    "type": "Layer 12 (Observability)",
                    "message": f"whitelisted function '{node.name}()' lacks: {', '.join(missing)}"
                })

            # 2. Type-safety & Documentation (Layer 2)
            docstring = ast.get_docstring(node)
            if not docstring or not docstring.strip():
                self.errors.append({
                    "line": node.lineno,
                    "type": "Layer 2 (API/Documentation)",
                    "message": f"whitelisted function '{node.name}()' must have a non-empty descriptive docstring."
                })

            # Verify parameter annotations
            for arg in node.args.args:
                if arg.arg in ["self", "cls"]:
                    continue
                if not arg.annotation:
                    self.errors.append({
                        "line": node.lineno,
                        "type": "Layer 2 (API/Type Safety)",
                        "message": f"whitelisted parameter '{arg.arg}' in '{node.name}()' lacks a type-hint annotation."
                    })

            # Verify return annotation
            if not node.returns:
                self.errors.append({
                    "line": node.lineno,
                    "type": "Layer 2 (API/Type Safety)",
                    "message": f"whitelisted function '{node.name}()' lacks a return type-hint annotation (e.g. -> dict)."
                })

        # Continue traversing child nodes
        self.generic_visit(node)

    def visit_Call(self, node):
        # ==========================================
        # LAYER 3: DATABASE - SQL INJECTION PREVENTION
        # ==========================================
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
                self.errors.append({
                    "line": node.lineno,
                    "type": "Layer 3 (Database / SQL Injection)",
                    "message": "Unsafe raw SQL query detected. Avoid using f-strings, %, or .format() in frappe.db.sql(). Use parameterized inputs instead (e.g., frappe.db.sql('SELECT * FROM tabUser WHERE name = %s', user))."
                })

        self.generic_visit(node)

    def visit_Assign(self, node):
        # ==========================================
        # LAYER 4 & 5: SECURITY - SECRET GATES
        # ==========================================
        for target in node.targets:
            if isinstance(target, ast.Name):
                var_name = target.id.lower()
                # Check for critical variable names
                if any(x in var_name for x in ["key", "token", "secret", "password"]):
                    # Ignore standard utility variables or loop parameters
                    if var_name in ["key", "keys", "token_usage", "cache_key", "secret_key_exists"]:
                        continue
                    # Check if value is a hardcoded string literal
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        val = node.value.value
                        # Ignore standard placeholder strings or safe empty variables
                        if val.strip() and val not in ["***", "placeholder", "default", "none", "", "travis"]:
                            self.errors.append({
                                "line": node.lineno,
                                "type": "Layer 4 & 5 (Security)",
                                "message": f"Hardcoded security parameter '{target.id}' assigned static value '{val[:15]}...'. Load credentials dynamically via os.environ or frappe.conf instead."
                            })

        self.generic_visit(node)

def check_nginx_rate_limiting(filepath):
    """
    LAYER 6: Rate Limiting validation for Nginx configurations or template managers.
    """
    errors = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        
        # If the file defines an Nginx server or location block, verify it implements limit_req
        if "server {" in content or "location " in content:
            if "limit_req " not in content and "limit_req_zone" not in content:
                errors.append({
                    "line": 1,
                    "type": "Layer 6 (Rate Limiting)",
                    "message": f"Nginx server/location block config exposed in '{os.path.basename(filepath)}' without active 'limit_req' zone throttles."
                })
    except Exception as e:
        errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

def check_dockerfile_compliance(filepath):
    """
    LAYER 9: Enforces multi-stage builds inside Dockerfiles to guarantee optimized images.
    """
    errors = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        if "FROM " in content:
            from_counts = content.count("FROM ")
            if from_counts < 2 and " AS " not in content:
                errors.append({
                    "line": 1,
                    "type": "Layer 9 (Containers)",
                    "message": f"Dockerfile '{os.path.basename(filepath)}' should utilize multi-stage builds ('FROM ... AS ...') to minimize final footprint."
                })
    except Exception as e:
        errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

def check_caching_and_cdn(filepath):
    """
    LAYER 7: Caching & CDN checks. Enforces caching headers or Next.js caching rules.
    """
    errors = []
    base = os.path.basename(filepath).lower()
    if "next.config" in base:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            if "headers" not in content and "cache-control" not in content.lower():
                errors.append({
                    "line": 1,
                    "type": "Layer 7 (Caching & CDN)",
                    "message": f"Next.js config file '{os.path.basename(filepath)}' lacks active CDN caching headers or 'headers()' configuration overrides."
                })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    elif filepath.endswith(".conf") or "nginx" in filepath.lower():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            if "expires " not in content and "cache-control" not in content.lower():
                errors.append({
                    "line": 1,
                    "type": "Layer 7 (Caching & CDN)",
                    "message": f"Nginx config '{os.path.basename(filepath)}' does not configure static asset expiration rules or Cache-Control headers."
                })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

def check_load_balancing_and_scaling(filepath):
    """
    LAYER 8: Compose memory limits/scaling checks.
    """
    errors = []
    base = os.path.basename(filepath).lower()
    if ("docker-compose" in base or "compose" in base) and (base.endswith(".yml") or base.endswith(".yaml")):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            if "mem_limit" not in content and "limits:" not in content and "memory:" not in content:
                errors.append({
                    "line": 1,
                    "type": "Layer 8 (Load Balancing & Scaling)",
                    "message": f"Docker Compose config '{os.path.basename(filepath)}' fails to specify container memory limits (mem_limit or deploy.resources.limits.memory) for resource isolation."
                })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

def check_availability_and_recovery(filepath):
    """
    LAYER 13: Availability & Backup test coverage.
    """
    errors = []
    base = os.path.basename(filepath).lower()
    if any(x in base for x in ["backup", "restore", "recovery"]) and any(filepath.endswith(ext) for ext in [".py", ".sh", ".ps1", ".bash"]):
        if "test" in base:
            return errors
        dir_name = os.path.dirname(filepath)
        test_filename_1 = "test_" + os.path.basename(filepath)
        test_filename_2 = os.path.basename(filepath).replace(".py", "_test.py").replace(".sh", "_test.sh").replace(".ps1", "_test.ps1").replace(".bash", "_test.bash")
        
        test_exists = False
        possible_dirs = [dir_name, os.path.join(dir_name, "tests"), os.path.join(dir_name, "test")]
        for d in possible_dirs:
            if os.path.exists(os.path.join(d, test_filename_1)) or os.path.exists(os.path.join(d, test_filename_2)):
                test_exists = True
                break
                
        if not test_exists:
            errors.append({
                "line": 1,
                "type": "Layer 13 (Availability & Backup)",
                "message": f"Backup/Recovery script '{os.path.basename(filepath)}' lacks a corresponding unit test file (e.g. '{test_filename_1}') in the codebase."
            })
    return errors

def scan_file(filepath):
    errors = []
    if filepath.endswith(".py"):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                source = f.read()
            tree = ast.parse(source, filepath)
            visitor = PlatformComplianceVisitor(filepath)
            visitor.visit(tree)
            errors.extend(visitor.errors)
        except Exception as e:
            errors.append({"line": 1, "type": "Syntax Error", "message": str(e)})

    # Run Nginx rate-limiting validations
    if "nginx" in filepath.lower() or filepath.endswith(".conf"):
        nginx_errs = check_nginx_rate_limiting(filepath)
        errors.extend(nginx_errs)

    # Run Dockerfile validations
    if "dockerfile" in filepath.lower():
        dockerfile_errs = check_dockerfile_compliance(filepath)
        errors.extend(dockerfile_errs)

    # Run Caching & CDN checks
    cdn_errs = check_caching_and_cdn(filepath)
    errors.extend(cdn_errs)

    # Run Load Balancing checks
    scaling_errs = check_load_balancing_and_scaling(filepath)
    errors.extend(scaling_errs)

    # Run Backup checks
    backup_errs = check_availability_and_recovery(filepath)
    errors.extend(backup_errs)

    return errors

def check_database_migrations(changed_files):
    """
    LAYER 3: Verify that structural DocType changes are accompanied by DB migration patch files.
    """
    errors = []
    doctype_changed = False
    patch_changed = False

    for file in changed_files:
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

def main():
    print("=" * 80)
    print("ROKCT PLATFORM ECOSYSTEM - ARCHITECTURAL COMPLIANCE GATEWAY")
    print("=" * 80)

    # 1. Resolve files to scan: either passed directly or changed in git diff
    files_to_scan = []
    changed_files_list = []
    
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if os.path.isfile(arg):
                files_to_scan.append(arg)
                changed_files_list.append(arg)
            elif os.path.isdir(arg):
                for root, _, files in os.walk(arg):
                    for file in files:
                        fp = os.path.join(root, file)
                        files_to_scan.append(fp)
                        changed_files_list.append(fp)
    else:
        # Default fallback: get changed files via git diff if in a git repo
        try:
            cmd = ["git", "diff", "--name-only", "origin/main...HEAD"]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    line = line.strip()
                    if os.path.exists(line):
                        changed_files_list.append(line)
                        if line.endswith(".py") or "nginx" in line.lower() or line.endswith(".conf") or line.endswith(".yml") or line.endswith(".yaml") or "dockerfile" in line.lower():
                            files_to_scan.append(line)
        except Exception:
            pass

        # If still empty, scan recursively from current directory
        if not files_to_scan:
            print("No git diff files resolved. Scanning all python/config files in current workspace...")
            for root, _, files in os.walk("."):
                if any(x in root for x in [".git", "env", "node_modules", "__pycache__", ".shared-workflows"]):
                    continue
                for file in files:
                    fp = os.path.join(root, file)
                    if file.endswith(".py") or "nginx" in file.lower() or file.endswith(".conf") or file.endswith(".yml") or file.endswith(".yaml") or "dockerfile" in file.lower():
                        files_to_scan.append(fp)
                    if file.endswith(".json") and "doctype" in fp:
                        changed_files_list.append(fp)

    if not files_to_scan and not changed_files_list:
        print("SUCCESS: No source files resolved for scan. Exiting.")
        sys.exit(0)

    print(f"Auditing {len(files_to_scan)} source files...")
    total_violations = 0

    # 2. Run AST File Scanning
    for filepath in files_to_scan:
        errors = scan_file(filepath)
        if errors:
            print(f"\nCOMPLIANCE VIOLATION in: {filepath}")
            for err in errors:
                print(f"  [Line {err['line']}] [{err['type']}] -> {err['message']}")
                total_violations += 1

    # 3. Run Layer 3 Schema Compliance Checks
    migration_errors = check_database_migrations(changed_files_list)
    if migration_errors:
        print("\nCOMPLIANCE VIOLATION in: Git Schema Diff")
        for err in migration_errors:
            print(f"  [Line {err['line']}] [{err['type']}] -> {err['message']}")
            total_violations += 1

    print("\n" + "=" * 80)
    if total_violations > 0:
        print(f"ARCHITECTURAL COMPLIANCE FAILED: {total_violations} violations found.")
        print("All changes must adhere to ROKCT production-grade standards before merging.")
        print("=" * 80)
        sys.exit(1)
    else:
        print("ARCHITECTURAL COMPLIANCE SUCCESS: All systems pass production standards.")
        print("=" * 80)
        sys.exit(0)

if __name__ == "__main__":
    main()

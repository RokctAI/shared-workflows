#!/usr/bin/env python3
# Copyright 2026 RokctAI
# Compliance Scanner: Enforces Trace ID propagation and structured stderr logging on all @frappe.whitelist() endpoints.

import ast
import sys
import os
import subprocess

class ObservabilityVisitor(ast.NodeVisitor):
    def __init__(self, filename):
        self.filename = filename
        self.errors = []

    def visit_FunctionDef(self, node):
        # 1. Detect if the function has a @frappe.whitelist decorator
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
        
        if not is_whitelisted:
            return

        # 2. Inspect function body to ensure it implements Trace ID and structured stderr logging
        has_trace_id = False
        has_stderr = False

        for subnode in ast.walk(node):
            # Check for trace_id variable reference/assignment
            if isinstance(subnode, ast.Name) and subnode.id == "trace_id":
                has_trace_id = True
            
            # Check for literal headers string check
            if isinstance(subnode, ast.Constant) and isinstance(subnode.value, str):
                val_lower = subnode.value.lower()
                if "x-trace-id" in val_lower or "x-request-id" in val_lower or "trace_id" in val_lower:
                    has_trace_id = True

            # Check for stderr reference (sys.stderr or stderr.write)
            if isinstance(subnode, ast.Attribute) and subnode.attr == "stderr":
                has_stderr = True
            if isinstance(subnode, ast.Name) and subnode.id == "stderr":
                has_stderr = True

        if not has_trace_id or not has_stderr:
            self.errors.append({
                "function": node.name,
                "line": node.lineno,
                "has_trace_id": has_trace_id,
                "has_stderr": has_stderr
            })

def scan_file(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filepath)
        visitor = ObservabilityVisitor(filepath)
        visitor.visit(tree)
        return visitor.errors
    except Exception as e:
        return [{"function": "<syntax_error>", "line": 1, "error": str(e)}]

def main():
    print("=" * 80)
    print("ROKCT PLATFORM ECOSYSTEM - OBSERVABILITY COMPLIANCE GATE")
    print("=" * 80)

    # Resolve files to scan: either passed directly or changed in git diff
    files_to_scan = []
    if len(sys.argv) > 1:
        # Support running on specific directories or list of files
        for arg in sys.argv[1:]:
            if os.path.isfile(arg) and arg.endswith(".py"):
                files_to_scan.append(arg)
            elif os.path.isdir(arg):
                for root, _, files in os.walk(arg):
                    for file in files:
                        if file.endswith(".py"):
                            files_to_scan.append(os.path.join(root, file))
    else:
        # Default fallback: get changed python files via git diff if in a git repo
        try:
            # Check against main/master branch diffs
            cmd = ["git", "diff", "--name-only", "origin/main...HEAD"]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    line = line.strip()
                    if line.endswith(".py") and os.path.exists(line):
                        files_to_scan.append(line)
        except Exception:
            pass

        # If still empty, scan all python files in the current working directory recursively
        if not files_to_scan:
            print("No explicit git diff files resolved. Scanning all python files in current directory...")
            for root, _, files in os.walk("."):
                # Skip virtual environments or standard hidden folders
                if any(x in root for x in [".git", "env", "node_modules", "__pycache__"]):
                    continue
                for file in files:
                    if file.endswith(".py"):
                        files_to_scan.append(os.path.join(root, file))

    if not files_to_scan:
        print("SUCCESS: No Python source files resolved for scan. Exiting.")
        sys.exit(0)

    print(f"Auditing {len(files_to_scan)} Python source files...")
    total_violations = 0

    for filepath in files_to_scan:
        errors = scan_file(filepath)
        if errors:
            print(f"\nERROR: Observability Violations detected in: {filepath}")
            for err in errors:
                if "error" in err:
                    print(f"  [Line {err['line']}] Parse Error: {err['error']}")
                    total_violations += 1
                else:
                    missing = []
                    if not err["has_trace_id"]:
                        missing.append("X-Trace-Id resolution")
                    if not err["has_stderr"]:
                        missing.append("sys.stderr structured log emission")
                    print(f"  [Line {err['line']}] whitelisted function '{err['function']}()' lacks: {', '.join(missing)}")
                    total_violations += 1

    print("\n" + "=" * 80)
    if total_violations > 0:
        print(f"COMPLIANCE FAILED: {total_violations} observability violations found.")
        print("Every @frappe.whitelist() endpoint MUST resolve a Trace ID and write structured log events to stderr.")
        print("=" * 80)
        sys.exit(1)
    else:
        print("COMPLIANCE SUCCESS: All whitelisted endpoints pass observability standards.")
        print("=" * 80)
        sys.exit(0)

if __name__ == "__main__":
    main()

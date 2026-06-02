#!/usr/bin/env python3
# Copyright 2026 RokctAI
# Automated Docstring & Spec Synchronization Utility

import os
import sys
import ast
import argparse
import difflib
from pathlib import Path

def is_whitelisted(node):
    """Check if the function has a @frappe.whitelist or @whitelist decorator."""
    for decorator in node.decorator_list:
        # Match @whitelist or @frappe.whitelist
        if isinstance(decorator, ast.Name) and decorator.id == 'whitelist':
            return True
        elif isinstance(decorator, ast.Attribute) and decorator.attr == 'whitelist':
            return True
        elif isinstance(decorator, ast.Call):
            func = decorator.func
            if isinstance(func, ast.Name) and func.id == 'whitelist':
                return True
            elif isinstance(func, ast.Attribute) and func.attr == 'whitelist':
                return True
    return False

def get_args_string(node):
    """Format function arguments to a readable string."""
    args = []
    # Positional/keyword arguments
    defaults_offset = len(node.args.args) - len(node.args.defaults)
    for idx, arg in enumerate(node.args.args):
        arg_name = arg.arg
        if idx >= defaults_offset:
            default_val = node.args.defaults[idx - defaults_offset]
            # Try to get string representation of default value
            if isinstance(default_val, ast.Constant):
                val_repr = repr(default_val.value)
            elif isinstance(default_val, ast.Name):
                val_repr = default_val.id
            else:
                val_repr = "..."
            args.append(f"{arg_name}={val_repr}")
        else:
            args.append(arg_name)
            
    # *args
    if node.args.vararg:
        args.append(f"*{node.args.vararg.arg}")
        
    # Keyword-only arguments
    for idx, arg in enumerate(node.args.kwonlyargs):
        arg_name = arg.arg
        default_val = node.args.kw_defaults[idx]
        if default_val is not None:
            if isinstance(default_val, ast.Constant):
                val_repr = repr(default_val.value)
            else:
                val_repr = "..."
            args.append(f"{arg_name}={val_repr}")
        else:
            args.append(arg_name)
            
    # **kwargs
    if node.args.kwarg:
        args.append(f"**{node.args.kwarg.arg}")
        
    return ", ".join(args)

def parse_python_file(filepath):
    """Parse python file and extract documentation information."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)
    except Exception as e:
        return None

    module_doc = ast.get_docstring(tree)
    classes = []
    functions = []

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            class_doc = ast.get_docstring(node)
            methods = []
            for child in node.body:
                if isinstance(child, ast.FunctionDef):
                    method_doc = ast.get_docstring(child)
                    methods.append({
                        "name": child.name,
                        "args": get_args_string(child),
                        "docstring": method_doc,
                        "whitelisted": is_whitelisted(child)
                    })
            classes.append({
                "name": node.name,
                "docstring": class_doc,
                "methods": methods
            })
        elif isinstance(node, ast.FunctionDef):
            func_doc = ast.get_docstring(node)
            functions.append({
                "name": node.name,
                "args": get_args_string(node),
                "docstring": func_doc,
                "whitelisted": is_whitelisted(node)
            })

    # Return structure if we found any API/documentation elements
    if module_doc or classes or functions:
        return {
            "module_doc": module_doc,
            "classes": classes,
            "functions": functions
        }
    return None

def generate_markdown(filepath, rel_path, spec):
    """Generate Markdown representation of the Python specification."""
    lines = []
    basename = os.path.basename(filepath)
    module_name = os.path.splitext(basename)[0]
    
    lines.append(f"# API Reference: {module_name}")
    lines.append("")
    lines.append(f"Source file: `{rel_path.replace(os.sep, '/')}`")
    lines.append("")
    
    if spec["module_doc"]:
        lines.append("## Module Description")
        lines.append(spec["module_doc"].strip())
        lines.append("")
        
    if spec["classes"]:
        lines.append("## Classes")
        lines.append("")
        for cls in spec["classes"]:
            lines.append(f"### class `{cls['name']}`")
            if cls["docstring"]:
                lines.append(cls["docstring"].strip())
            lines.append("")
            
            whitelisted_methods = [m for m in cls["methods"] if m["whitelisted"]]
            other_methods = [m for m in cls["methods"] if not m["whitelisted"] and m["docstring"]]
            
            if whitelisted_methods:
                lines.append("#### Whitelisted API Methods")
                for method in whitelisted_methods:
                    lines.append(f"##### `{method['name']}({method['args']})`")
                    if method["docstring"]:
                        lines.append(method["docstring"].strip())
                    lines.append("")
                    
            if other_methods:
                lines.append("#### Documented Internal Methods")
                for method in other_methods:
                    lines.append(f"##### `{method['name']}({method['args']})`")
                    if method["docstring"]:
                        lines.append(method["docstring"].strip())
                    lines.append("")
                    
    if spec["functions"]:
        whitelisted_funcs = [f for f in spec["functions"] if f["whitelisted"]]
        other_funcs = [f for f in spec["functions"] if not f["whitelisted"] and f["docstring"]]
        
        if whitelisted_funcs:
            lines.append("## Whitelisted API Endpoints")
            lines.append("")
            for func in whitelisted_funcs:
                lines.append(f"### `def {func['name']}({func['args']})`")
                if func["docstring"]:
                    lines.append(func["docstring"].strip())
                lines.append("")
                
        if other_funcs:
            lines.append("## Documented Module Functions")
            lines.append("")
            for func in other_funcs:
                lines.append(f"### `def {func['name']}({func['args']})`")
                if func["docstring"]:
                    lines.append(func["docstring"].strip())
                lines.append("")

    # Add spacing and trailing newline
    content = "\n".join(lines).strip() + "\n"
    return content

def scan_and_sync(target_dir, check_only=False):
    """Scan directory and sync docs to target_dir/docs/api/."""
    target_dir = os.path.abspath(target_dir)
    docs_api_dir = os.path.join(target_dir, "docs", "api")
    
    out_of_sync = []
    
    for root, dirs, files in os.walk(target_dir):
        # Skip dependency/build folders
        dirs[:] = [d for d in dirs if d not in [".git", "env", "node_modules", "__pycache__", ".next", "dist", ".dart_tool", "build", "docs", ".rokct", "Compliance"]]
        for file in files:
            if file.endswith(".py"):
                filepath = os.path.join(root, file)
                spec = parse_python_file(filepath)
                if spec:
                    rel_path = os.path.relpath(filepath, target_dir)
                    md_content = generate_markdown(filepath, rel_path, spec)
                    
                    # Compute output markdown file name preserving directory structure under docs/api/
                    rel_dir = os.path.relpath(root, target_dir)
                    if rel_dir == ".":
                        out_md_name = f"{os.path.splitext(file)[0]}.md"
                    else:
                        out_md_name = f"{rel_dir.replace(os.sep, '_')}_{os.path.splitext(file)[0]}.md"
                        
                    out_md_path = os.path.join(docs_api_dir, out_md_name)
                    
                    existing_content = ""
                    if os.path.exists(out_md_path):
                        with open(out_md_path, "r", encoding="utf-8") as f:
                            existing_content = f.read()
                            
                    if existing_content != md_content:
                        out_of_sync.append((out_md_path, md_content, existing_content, rel_path))
                        if not check_only:
                            os.makedirs(docs_api_dir, exist_ok=True)
                            with open(out_md_path, "w", encoding="utf-8") as f:
                                f.write(md_content)
                            print(f"Synced: {os.path.relpath(out_md_path, target_dir)} <- {rel_path}")

    return out_of_sync

def main():
    parser = argparse.ArgumentParser(description="Synchronize codebase API docstrings to Markdown documentation.")
    parser.add_argument("target_dir", help="App directory to scan (e.g. rcore, rpanel, paas)")
    parser.add_argument("--check", action="store_true", help="Only check for documentation drift without writing updates")
    args = parser.parse_args()
    
    if not os.path.isdir(args.target_dir):
        print(f"Error: Target directory '{args.target_dir}' does not exist.")
        sys.exit(1)
        
    out_of_sync = scan_and_sync(args.target_dir, check_only=args.check)
    
    if args.check and out_of_sync:
        print("DOCUMENTATION DRIFT DETECTED!")
        print("The following API reference documentation files are out-of-sync with Python docstrings:")
        for path, expected, actual, src in out_of_sync:
            print(f"\n  - {os.path.basename(path)} (source: {src})")
            if actual:
                # Show differences
                diff = difflib.unified_diff(
                    actual.splitlines(keepends=True),
                    expected.splitlines(keepends=True),
                    fromfile="Current Doc",
                    tofile="Expected Doc (AST)",
                    n=2
                )
                sys.stdout.writelines(diff)
            else:
                print("    (File does not exist yet. Run in write mode to generate it.)")
        print("\nFix this by running the updater script on the target directory:")
        print(f"  python3 {sys.argv[0]} {args.target_dir}")
        sys.exit(1)
    elif args.check:
        print("All API documentation files are perfectly in sync with codebase docstrings.")
        sys.exit(0)
    else:
        if out_of_sync:
            print(f"Successfully synchronized {len(out_of_sync)} API reference documentation files.")
        else:
            print("No synchronization needed. All documentation files are already up-to-date.")
        sys.exit(0)

if __name__ == "__main__":
    main()

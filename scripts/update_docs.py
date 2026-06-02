#!/usr/bin/env python3
# Copyright 2026 RokctAI
# Automated Docstring & Spec Synchronization Utility

import os
import sys
import ast
import argparse
import difflib
import hashlib
import json
import urllib.request
import urllib.error
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

def get_node_source_hash(source, node):
    try:
        node_source = ast.get_source_segment(source, node)
        if not node_source:
            node_source = ast.unparse(node)
        return hashlib.sha256(node_source.encode("utf-8")).hexdigest()
    except Exception:
        return ""

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
                        "whitelisted": is_whitelisted(child),
                        "hash": get_node_source_hash(source, child),
                        "source": ast.get_source_segment(source, child) or ast.unparse(child)
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
                "whitelisted": is_whitelisted(node),
                "hash": get_node_source_hash(source, node),
                "source": ast.get_source_segment(source, node) or ast.unparse(node)
            })

    # Return structure if we found any API/documentation elements
    if module_doc or classes or functions:
        return {
            "module_doc": module_doc,
            "classes": classes,
            "functions": functions
        }
    return None

def generate_ai_doc(func_source, func_name, args_string):
    """Use Groq API to generate a natural language description for a Python function."""
    groq_api_key = os.environ.get("GROQ_API_KEY") or os.environ.get("GROQ_API")
    if not groq_api_key:
        return None

    prompt = (
        f"Write a short, professional description for the following Python function. "
        f"Explain its purpose and what its parameters mean. "
        f"Do not include any markdown code blocks, just output the raw text.\n\n"
        f"Function Name: {func_name}\n"
        f"Arguments: {args_string}\n"
        f"Source Code:\n{func_source}"
    )

    data = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": "You are a senior technical writer documenting a Python codebase. Produce concise, readable documentation."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2
    }

    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(data).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {groq_api_key}",
            "Content-Type": "application/json"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            return content.strip() if content else None
    except Exception as e:
        print(f"⚠️ Warning: Failed to generate AI documentation for {func_name}: {e}")
        return None

def extract_cached_ai_docs(md_content):
    """Parse existing markdown and return a mapping of function name -> (hash, doc)."""
    cache = {}
    lines = md_content.splitlines()
    current_func = None
    current_hash = None
    doc_lines = []

    in_doc_block = False

    for line in lines:
        if line.startswith("### `def ") or line.startswith("##### `"):
            # New function block
            if current_func and current_hash and doc_lines:
                cache[current_func] = (current_hash, "\n".join(doc_lines).strip())

            # Reset state
            doc_lines = []
            current_hash = None
            in_doc_block = False

            # Extract function name. e.g. "### `def get_assetlinks()`" -> "get_assetlinks"
            # e.g. "##### `my_method(...)`" -> "my_method"
            name_part = line.split("`")[1]
            if name_part.startswith("def "):
                name_part = name_part[4:]
            current_func = name_part.split("(")[0]

        elif current_func and line.startswith("<!-- #AIDOC "):
            # We found the AI marker
            # format: <!-- #AIDOC HASH -->
            parts = line.replace("<!--", "").replace("-->", "").strip().split()
            if len(parts) >= 2 and parts[0] == "#AIDOC":
                current_hash = parts[1]
                in_doc_block = True
        elif in_doc_block:
            # We are reading the doc block until the next header
            if line.startswith("#"):
                # Hit next section, close the block early
                if current_func and current_hash and doc_lines:
                    cache[current_func] = (current_hash, "\n".join(doc_lines).strip())
                in_doc_block = False
                current_func = None
            else:
                doc_lines.append(line)

    # End of file
    if current_func and current_hash and doc_lines:
        cache[current_func] = (current_hash, "\n".join(doc_lines).strip())

    return cache

def generate_markdown(filepath, rel_path, spec, existing_md_content="", check_only=False):
    """Generate Markdown representation of the Python specification."""
    lines = []
    basename = os.path.basename(filepath)
    module_name = os.path.splitext(basename)[0]
    
    ai_cache = extract_cached_ai_docs(existing_md_content) if existing_md_content else {}

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
                    else:
                        cached_hash, cached_doc = ai_cache.get(method["name"], (None, None))
                        if cached_hash == method["hash"]:
                            lines.append(f"<!-- #AIDOC {method['hash']} -->")
                            lines.append(cached_doc)
                        elif not check_only:
                            ai_doc = generate_ai_doc(method["source"], method["name"], method["args"])
                            if ai_doc:
                                lines.append(f"<!-- #AIDOC {method['hash']} -->")
                                lines.append(ai_doc)
                            else:
                                lines.append("*No documentation provided.*")
                        else:
                            # In check_only mode with a mismatch/missing cache, emit the new hash to trigger drift detection
                            if cached_hash and cached_doc:
                                lines.append(f"<!-- #AIDOC {method['hash']} -->")
                                lines.append(cached_doc)
                            else:
                                lines.append(f"<!-- #AIDOC {method['hash']} -->")
                                lines.append("*No documentation provided.*")
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
                else:
                    cached_hash, cached_doc = ai_cache.get(func["name"], (None, None))
                    if cached_hash == func["hash"]:
                        lines.append(f"<!-- #AIDOC {func['hash']} -->")
                        lines.append(cached_doc)
                    elif not check_only:
                        print(f"Generating AI documentation for {func['name']}...")
                        ai_doc = generate_ai_doc(func["source"], func["name"], func["args"])
                        if ai_doc:
                            lines.append(f"<!-- #AIDOC {func['hash']} -->")
                            lines.append(ai_doc)
                        else:
                            lines.append("*No documentation provided.*")
                    else:
                        # In check_only mode with a mismatch/missing cache, emit the new hash to trigger drift detection
                        if cached_hash and cached_doc:
                            lines.append(f"<!-- #AIDOC {func['hash']} -->")
                            lines.append(cached_doc)
                        else:
                            lines.append(f"<!-- #AIDOC {func['hash']} -->")
                            lines.append("*No documentation provided.*")
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
                    
                    # Compute output markdown file name preserving directory structure under docs/api/
                    rel_dir = os.path.relpath(root, target_dir)
                    if rel_dir == ".":
                        out_md_name = f"{os.path.splitext(file)[0]}.md"
                    else:
                        out_md_name = f"{rel_dir.replace(os.sep, '_')}_{os.path.splitext(file)[0]}.md"
                        
                    out_md_path = os.path.join(docs_api_dir, out_md_name)
                    
                    if not os.path.exists(out_md_path):
                        # File doesn't exist, auto-create it even in check_only mode
                        md_content = generate_markdown(filepath, rel_path, spec, existing_md_content="", check_only=False)
                        os.makedirs(docs_api_dir, exist_ok=True)
                        with open(out_md_path, "w", encoding="utf-8") as f:
                            f.write(md_content)
                        print(f"Auto-created missing doc: {os.path.relpath(out_md_path, target_dir)} <- {rel_path}")
                    else:
                        with open(out_md_path, "r", encoding="utf-8") as f:
                            existing_content = f.read()
                            
                        md_content = generate_markdown(filepath, rel_path, spec, existing_md_content=existing_content, check_only=check_only)

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

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
import logging
import re
from pathlib import Path

def setup_logger(target_dir):
    """Set up file logging into .rokct/agent/logs/"""
    log_dir = os.path.join(target_dir, ".rokct", "agent", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "update_docs.log")

    logger = logging.getLogger("update_docs")
    logger.setLevel(logging.DEBUG)

    if logger.hasHandlers():
        logger.handlers.clear()

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setLevel(logging.INFO)
    sh.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(sh)

    return logger

LOGGER = None
FILE_CONTENTS_CACHE = {}

def get_other_files_contents(defining_filepath, target_dir):
    """Load and cache contents of all files in target_dir except defining_filepath."""
    key = (defining_filepath, target_dir)
    if key in FILE_CONTENTS_CACHE:
        return FILE_CONTENTS_CACHE[key]
        
    contents = []
    for root, dirs, files in os.walk(target_dir):
        dirs[:] = [d for d in dirs if d not in [".git", "env", "node_modules", "__pycache__", ".next", "dist", ".dart_tool", "build", "docs", ".rokct", "Compliance"]]
        for file in files:
            fp = os.path.join(root, file)
            if fp != defining_filepath:
                if file.endswith((".py", ".ts", ".tsx", ".dart", ".js", ".jsx", ".json", ".html")):
                    try:
                        with open(fp, "r", encoding="utf-8") as f:
                            contents.append(f.read())
                    except Exception:
                        pass
    FILE_CONTENTS_CACHE[key] = contents
    return contents

def is_function_used(func_name, defining_filepath, target_dir):
    """Check if the function name is referenced in any other file in the target directory."""
    if func_name in ["main", "login", "register", "setup", "run"]:
        return True
        
    contents = get_other_files_contents(defining_filepath, target_dir)
    pattern = re.compile(rf'\b{re.escape(func_name)}\b')
    for text in contents:
        if pattern.search(text):
            return True
    return False

def detect_project_type(target_dir):
    """Detect the dominant project type (flutter, typescript, or python)."""
    has_dart = False
    has_ts = False
    has_py = False
    
    for root, dirs, files in os.walk(target_dir):
        dirs[:] = [d for d in dirs if d not in [".git", "env", "node_modules", "__pycache__", ".next", "dist", ".dart_tool", "build", "docs", ".rokct", "Compliance"]]
        for file in files:
            if file.endswith(".dart"):
                has_dart = True
            elif file.endswith(".ts") or file.endswith(".tsx"):
                has_ts = True
            elif file.endswith(".py"):
                has_py = True
                
    if has_dart:
        return "flutter"
    elif has_ts:
        return "typescript"
    elif has_py:
        return "python"
    return "unknown"

def is_whitelisted(node):
    """Check if the function has a @frappe.whitelist or @whitelist decorator."""
    for decorator in node.decorator_list:
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
    defaults_offset = len(node.args.args) - len(node.args.defaults)
    for idx, arg in enumerate(node.args.args):
        arg_name = arg.arg
        if idx >= defaults_offset:
            default_val = node.args.defaults[idx - defaults_offset]
            if isinstance(default_val, ast.Constant):
                val_repr = repr(default_val.value)
            elif isinstance(default_val, ast.Name):
                val_repr = default_val.id
            else:
                val_repr = "..."
            args.append(f"{arg_name}={val_repr}")
        else:
            args.append(arg_name)
            
    if node.args.vararg:
        args.append(f"*{node.args.vararg.arg}")
        
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

def strip_comments_except_docs(content, is_ts=True):
    """Strip standard comments (commented-out code) while preserving docs (JSDoc or DartDoc)."""
    if is_ts:
        pattern = re.compile(
            r'("(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`)|'
            r'(/\*\*.*?\*/)|'
            r'(/\*.*?\*/|//.*?$)',
            re.DOTALL | re.MULTILINE
        )
    else:  # Dart
        pattern = re.compile(
            r'("(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\')|'
            r'(///.*?$)|'
            r'(/\*.*?\*/|//.*?$)',
            re.DOTALL | re.MULTILINE
        )
    
    def replace(match):
        if match.group(1):
            return match.group(1)
        elif match.group(2):
            return match.group(2)
        else:
            return ""
            
    return pattern.sub(replace, content)

def clean_jsdoc(jsdoc):
    """Remove /**, */, and leading asterisks from JSDoc lines."""
    lines = []
    for line in jsdoc.splitlines():
        line = line.strip()
        if line.startswith("/**") or line.endswith("*/"):
            continue
        if line.startswith("*"):
            line = line[1:].strip()
        if line:
            lines.append(line)
    return "\n".join(lines).strip()

def clean_dartdoc(dartdoc):
    """Remove /// and leading spaces from DartDoc lines."""
    lines = []
    for line in dartdoc.splitlines():
        line = line.strip()
        if line.startswith("///"):
            line = line[3:].strip()
        if line:
            lines.append(line)
    return "\n".join(lines).strip()

def clean_args_string(args_str):
    """Clean newlines and excessive whitespace from arguments string."""
    if not args_str:
        return ""
    cleaned = re.sub(r'\s+', ' ', args_str).strip()
    return cleaned

def parse_python_file(filepath):
    """Parse python file and extract documentation information."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)
    except Exception:
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

    if module_doc or classes or functions:
        return {
            "module_doc": module_doc,
            "classes": classes,
            "functions": functions
        }
    return None

def parse_ts_file(filepath):
    """Parse TypeScript/TSX file and extract documentation information."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return None
        
    stripped = strip_comments_except_docs(content, is_ts=True)
    
    # Matches JSDoc followed by exported/default function or arrow function declarations
    pattern = re.compile(
        r'(/\*\*.*?\*/)?\s*'
        r'(export\s+)?(default\s+)?'
        r'(?:'
        r'(?:class\s+([A-Za-z0-9_]+))|'
        r'(?:function\s+([A-Za-z0-9_]+)\s*\((.*?)\))|'
        r'(?:(?:const|let|var)\s+([A-Za-z0-9_]+)\s*=\s*\((.*?)\)\s*=>)'
        r')',
        re.DOTALL
    )
    
    classes = []
    functions = []
    
    for match in pattern.finditer(stripped):
        jsdoc = match.group(1)
        docstring = clean_jsdoc(jsdoc) if jsdoc else ""
        
        class_name = match.group(4)
        func_name = match.group(5) or match.group(7)
        func_args = match.group(6) or match.group(8)
        
        if class_name:
            classes.append({
                "name": class_name,
                "docstring": docstring,
                "methods": []
            })
        elif func_name:
            functions.append({
                "name": func_name,
                "args": clean_args_string(func_args),
                "docstring": docstring,
                "whitelisted": True,
                "hash": hashlib.sha256(match.group(0).encode("utf-8")).hexdigest(),
                "source": match.group(0)
            })
            
    if classes or functions:
        return {
            "module_doc": "",
            "classes": classes,
            "functions": functions
        }
    return None

def parse_dart_file(filepath):
    """Parse Dart file and extract documentation information."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return None
        
    stripped = strip_comments_except_docs(content, is_ts=False)
    
    # Matches DartDoc annotations followed by class or function declarations
    pattern = re.compile(
        r'((?:///.*?$(?:\r?\n)?)+)?\s*'
        r'(?:'
        r'(?:class\s+([a-zA-Z0-9_]+))|'
        r'(?:([a-zA-Z0-9_<>]+)\s+([a-zA-Z0-9_]+)\s*\((.*?)\)\s*\{)'
        r')',
        re.DOTALL | re.MULTILINE
    )
    
    classes = []
    functions = []
    
    for match in pattern.finditer(stripped):
        dartdoc = match.group(1)
        docstring = clean_dartdoc(dartdoc) if dartdoc else ""
        
        class_name = match.group(2)
        func_name = match.group(4)
        func_args = match.group(5)
        
        if class_name:
            if class_name.startswith("_"):
                continue
            classes.append({
                "name": class_name,
                "docstring": docstring,
                "methods": []
            })
        elif func_name:
            if func_name.startswith("_") or func_name in ["if", "for", "while", "switch", "catch"]:
                continue
            functions.append({
                "name": func_name,
                "args": clean_args_string(func_args),
                "docstring": docstring,
                "whitelisted": True,
                "hash": hashlib.sha256(match.group(0).encode("utf-8")).hexdigest(),
                "source": match.group(0)
            })
            
    if classes or functions:
        return {
            "module_doc": "",
            "classes": classes,
            "functions": functions
        }
    return None

def call_groq_api(model, prompt, groq_api_key, func_name):
    """Helper to make the API call to Groq with specific model and error handling."""
    data = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a senior technical writer documenting a Python, TypeScript, and Dart codebase. Produce concise, readable documentation."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2
    }

    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(data).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {groq_api_key}",
            "Content-Type": "application/json",
            "User-Agent": "curl/7.81.0"
        },
        method="POST"
    )

    if LOGGER:
        LOGGER.debug(f"Sending Groq {model} request for {func_name} (Payload: {len(prompt)} bytes)")

    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            result = json.loads(response.read().decode("utf-8"))
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            if content:
                content = content.strip()
                if LOGGER:
                    LOGGER.info(f"✅ Successfully generated AI doc for {func_name} using {model}.")
                return content
            else:
                if LOGGER:
                    LOGGER.warning(f"⚠️ Groq {model} returned empty content for {func_name}.")
                return None
    except urllib.error.HTTPError as e:
        try:
            err_msg = e.read().decode("utf-8")
        except Exception:
            err_msg = ""
        if LOGGER:
            LOGGER.error(f"❌ HTTP Error generating AI doc for {func_name} using {model}: {e.code} - {err_msg}")
        return None
    except Exception as e:
        if LOGGER:
            LOGGER.error(f"❌ Exception generating AI doc for {func_name} using {model}: {str(e)}")
        return None

def generate_ai_doc(func_source, func_name, args_string):
    """Use Groq API to generate a natural language description for a Python, TS, or Dart function."""
    if LOGGER:
        LOGGER.debug(f"Attempting to generate AI doc for function: {func_name}")

    groq_api_key = os.environ.get("GROQ_API_KEY") or os.environ.get("GROQ_API")
    if not groq_api_key:
        if LOGGER:
            LOGGER.warning(f"Skipping AI doc for {func_name} - GROQ_API key is missing from environment.")
        return None

    prompt = (
        f"Write a short, professional description for the following function. "
        f"Explain its purpose and what its parameters mean. "
        f"Do not include any markdown code blocks, just output the raw text.\n\n"
        f"Function Name: {func_name}\n"
        f"Arguments: {args_string}\n"
        f"Source Code:\n{func_source}"
    )

    content = call_groq_api("groq/compound", prompt, groq_api_key, func_name)

    if not content:
        if LOGGER:
            LOGGER.info(f"🔄 Falling back to llama-3.3-70b-versatile for {func_name}...")
        content = call_groq_api("llama-3.3-70b-versatile", prompt, groq_api_key, func_name)

    return content

def extract_cached_ai_docs(md_content):
    """Parse existing markdown and return a mapping of function name -> (hash, doc)."""
    cache = {}
    lines = md_content.splitlines()
    current_func = None
    current_hash = None
    doc_lines = []

    in_doc_block = False

    for line in lines:
        if line.startswith("### `def ") or line.startswith("### `function ") or line.startswith("### `") or line.startswith("##### `"):
            if current_func and current_hash and doc_lines:
                cache[current_func] = (current_hash, "\n".join(doc_lines).strip())

            doc_lines = []
            current_hash = None
            in_doc_block = False

            name_part = line.split("`")[1]
            if name_part.startswith("def "):
                name_part = name_part[4:]
            elif name_part.startswith("function "):
                name_part = name_part[9:]
            current_func = name_part.split("(")[0]

        elif current_func and line.startswith("<!-- ") and line.endswith(" -->"):
            comment_content = line[5:-4].strip()
            if len(comment_content) == 64:
                current_hash = comment_content
                in_doc_block = True
        elif in_doc_block:
            if line.startswith("#"):
                if current_func and current_hash and doc_lines:
                    cache[current_func] = (current_hash, "\n".join(doc_lines).strip())
                in_doc_block = False
                current_func = None
            else:
                doc_lines.append(line)

    if current_func and current_hash and doc_lines:
        cache[current_func] = (current_hash, "\n".join(doc_lines).strip())

    return cache

def get_fn_prefix(filepath):
    ext = os.path.splitext(filepath)[1]
    if ext == ".py":
        return "def "
    elif ext in [".ts", ".tsx"]:
        return "function "
    return ""

def generate_markdown(filepath, rel_path, spec, existing_md_content="", check_only=False, target_dir="."):
    """Generate Markdown representation of the Python, TS, or Dart specification."""
    lines = []
    basename = os.path.basename(filepath)
    module_name = os.path.splitext(basename)[0]
    fn_prefix = get_fn_prefix(filepath)
    
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
            
            # Filter unused class methods
            whitelisted_methods = [m for m in whitelisted_methods if is_function_used(m["name"], filepath, target_dir)]
            other_methods = [m for m in other_methods if is_function_used(m["name"], filepath, target_dir)]
            
            if whitelisted_methods:
                lines.append("#### Whitelisted API Methods")
                for method in whitelisted_methods:
                    lines.append(f"##### `{method['name']}({method['args']})`")
                    if method["docstring"]:
                        lines.append(method["docstring"].strip())
                    else:
                        cached_hash, cached_doc = ai_cache.get(method["name"], (None, None))
                        if cached_hash == method["hash"]:
                            lines.append(f"<!-- {method['hash']} -->")
                            lines.append(cached_doc)
                        elif not check_only:
                            ai_doc = generate_ai_doc(method["source"], method["name"], method["args"])
                            if ai_doc:
                                lines.append(f"<!-- {method['hash']} -->")
                                lines.append(ai_doc)
                            else:
                                lines.append("*No documentation provided (generation failed).*")
                        else:
                            if cached_hash and cached_doc:
                                lines.append(f"<!-- {method['hash']} -->")
                                lines.append(cached_doc)
                            else:
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
        
        # Filter out unused functions/endpoints
        whitelisted_funcs = [f for f in whitelisted_funcs if is_function_used(f["name"], filepath, target_dir)]
        other_funcs = [f for f in other_funcs if is_function_used(f["name"], filepath, target_dir)]
        
        if whitelisted_funcs:
            lines.append("## Whitelisted API Endpoints")
            lines.append("")
            for func in whitelisted_funcs:
                lines.append(f"### `{fn_prefix}{func['name']}({func['args']})`")
                if func["docstring"]:
                    lines.append(func["docstring"].strip())
                else:
                    cached_hash, cached_doc = ai_cache.get(func["name"], (None, None))
                    if cached_hash == func["hash"]:
                        lines.append(f"<!-- {func['hash']} -->")
                        lines.append(cached_doc)
                    elif not check_only:
                        print(f"Generating AI documentation for {func['name']}...")
                        ai_doc = generate_ai_doc(func["source"], func["name"], func["args"])
                        if ai_doc:
                            lines.append(f"<!-- {func['hash']} -->")
                            lines.append(ai_doc)
                        else:
                            lines.append("*No documentation provided (generation failed).*")
                    else:
                        if cached_hash and cached_doc:
                            lines.append(f"<!-- {func['hash']} -->")
                            lines.append(cached_doc)
                        else:
                            lines.append("*No documentation provided.*")
                lines.append("")
                
        if other_funcs:
            lines.append("## Documented Module Functions")
            lines.append("")
            for func in other_funcs:
                lines.append(f"### `{fn_prefix}{func['name']}({func['args']})`")
                if func["docstring"]:
                    lines.append(func["docstring"].strip())
                lines.append("")

    content = "\n".join(lines).strip() + "\n"
    return content

def scan_and_sync(target_dir, check_only=False):
    """Scan directory and sync docs to target_dir/docs/api/."""
    global LOGGER
    target_dir = os.path.abspath(target_dir)
    docs_api_dir = os.path.join(target_dir, "docs", "api")
    
    if LOGGER is None:
        LOGGER = setup_logger(target_dir)

    project_type = detect_project_type(target_dir)
    if LOGGER:
        LOGGER.info(f"Detected project type: {project_type} for {target_dir}")

    out_of_sync = []
    
    for root, dirs, files in os.walk(target_dir):
        dirs[:] = [d for d in dirs if d not in [".git", "env", "node_modules", "__pycache__", ".next", "dist", ".dart_tool", "build", "docs", ".rokct", "Compliance"]]
        for file in files:
            is_valid_file = False
            parser_func = None
            
            if project_type == "flutter" and file.endswith(".dart"):
                is_valid_file = True
                parser_func = parse_dart_file
            elif project_type == "typescript" and (file.endswith(".ts") or file.endswith(".tsx")):
                is_valid_file = True
                parser_func = parse_ts_file
            elif project_type == "python" and file.endswith(".py"):
                is_valid_file = True
                parser_func = parse_python_file
                
            if is_valid_file and parser_func:
                filepath = os.path.join(root, file)
                spec = parser_func(filepath)
                if spec:
                    rel_path = os.path.relpath(filepath, target_dir)
                    
                    rel_dir = os.path.relpath(root, target_dir)
                    if rel_dir == ".":
                        out_md_name = f"{os.path.splitext(file)[0]}.md"
                    else:
                        out_md_name = f"{rel_dir.replace(os.sep, '_')}_{os.path.splitext(file)[0]}.md"
                        
                    out_md_path = os.path.join(docs_api_dir, out_md_name)
                    
                    if not os.path.exists(out_md_path):
                        if LOGGER:
                            LOGGER.info(f"Auto-creating missing documentation for: {rel_path}")
                        md_content = generate_markdown(filepath, rel_path, spec, existing_md_content="", check_only=False, target_dir=target_dir)
                        os.makedirs(docs_api_dir, exist_ok=True)
                        with open(out_md_path, "w", encoding="utf-8") as f:
                            f.write(md_content)
                        if LOGGER:
                            LOGGER.info(f"Auto-created missing doc: {os.path.relpath(out_md_path, target_dir)} <- {rel_path}")
                    else:
                        with open(out_md_path, "r", encoding="utf-8") as f:
                            existing_content = f.read()
                            
                        md_content = generate_markdown(filepath, rel_path, spec, existing_md_content=existing_content, check_only=check_only, target_dir=target_dir)
                        
                        if existing_content != md_content:
                            out_of_sync.append((out_md_path, md_content, existing_content, rel_path))
                            if not check_only:
                                os.makedirs(docs_api_dir, exist_ok=True)
                                with open(out_md_path, "w", encoding="utf-8") as f:
                                    f.write(md_content)
                                if LOGGER:
                                    LOGGER.info(f"Synced: {os.path.relpath(out_md_path, target_dir)} <- {rel_path}")

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

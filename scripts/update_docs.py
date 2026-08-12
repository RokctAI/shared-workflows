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
import textwrap
import urllib.request
import urllib.error
import logging
import re
from pathlib import Path

# markdownlint's default MD013 line limit; generated markdown must stay
# within it (including fenced code blocks - MD013 checks those by default).
MD_LINE_LIMIT = 80

def find_git_root(start_path):
    """Traverse upwards to find the root of the git repository."""
    curr = Path(start_path).resolve()
    while curr != curr.parent:
        if (curr / ".git").is_dir():
            return str(curr)
        curr = curr.parent
    return str(Path(start_path).resolve())

def setup_logger(target_dir):
    """Set up file logging into .rokct/agent/logs/ at the git root."""
    git_root = find_git_root(target_dir)
    log_dir = os.path.join(git_root, ".rokct", "agent", "logs")
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
    """Yield file contents from target_dir except defining_filepath. Cached per target_dir."""
    # Cache keyed only on target_dir — all files in a project are read once, not per-function
    if target_dir not in FILE_CONTENTS_CACHE:
        cache = {}
        for root, dirs, files in os.walk(target_dir):
            dirs[:] = [d for d in dirs if d not in [".git", "env", "node_modules", "__pycache__", ".next", "dist", ".dart_tool", "build", "docs", ".rokct", "Compliance"]]
            for file in files:
                fp = os.path.join(root, file)
                if file.endswith((".py", ".ts", ".tsx", ".dart", ".js", ".jsx", ".json", ".html")):
                    try:
                        with open(fp, "r", encoding="utf-8") as f:
                            cache[fp] = f.read()
                    except Exception:
                        pass
        FILE_CONTENTS_CACHE[target_dir] = cache
    project_cache = FILE_CONTENTS_CACHE[target_dir]
    return (content for fp, content in project_cache.items() if fp != defining_filepath)

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
    """Detect the dominant project type (flutter, typescript, python, or data)."""
    has_dart = False
    has_ts = False
    has_py = False
    has_data = False
    
    for root, dirs, files in os.walk(target_dir):
        dirs[:] = [d for d in dirs if d not in [".git", "env", "node_modules", "__pycache__", ".next", "dist", ".dart_tool", "build", "docs", ".rokct", "Compliance"]]
        for file in files:
            if file.endswith(".dart"):
                has_dart = True
            elif file.endswith(".ts") or file.endswith(".tsx"):
                has_ts = True
            elif file.endswith(".py"):
                has_py = True
            elif file.endswith((".md", ".json", ".yml", ".yaml")):
                has_data = True
                
    if has_dart:
        return "flutter"
    elif has_ts:
        return "typescript"
    elif has_py:
        return "python"
    elif has_data:
        return "data"
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
    # A cleaner, less catastrophic backtracking regex pattern or line-by-line helper.
    # To prevent MemoryError (regex stack overflow / catastrophic backtracking), let's process carefully.
    if is_ts:
        pattern = re.compile(
            r'("(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`)|'
            r'(/\*\*.*?\*/)|'
            r'(/\*.*?\*/|//.*?$)',
            re.DOTALL | re.MULTILINE
        )
    else:  # Dart
        # Dart multi-line comments don't nest arbitrarily in this parser's context, but let's make it simpler and avoid DOTALL/large block recursion if we can.
        pattern = re.compile(
            r'("(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\')|'
            r'(///[^\r\n]*)|'
            r'(/\*.*?\*/|//[^\r\n]*)',
            re.DOTALL
        )
    
    def replace(match):
        if match.group(1):
            return match.group(1)
        elif match.group(2):
            return match.group(2)
        else:
            return ""
            
    try:
        return pattern.sub(replace, content)
    except (MemoryError, OverflowError, RuntimeError):
        # Fallback to line by line or return content if regex fails
        return content

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

# Reserved words that can never be a declaration name, and (as a leading
# token) mark statements like `return Foo(...)` / `await bar(...)` rather
# than declarations.
DART_STATEMENT_KEYWORDS = {
    "if", "for", "while", "switch", "catch", "return", "else", "do", "try",
    "assert", "new", "await", "throw", "yield", "case", "default", "in", "is",
    "on", "with", "super", "this",
}
DART_DECL_MODIFIERS = {
    "static", "final", "const", "late", "external", "factory", "abstract",
    "covariant",
}

# A declaration must start a line (only indentation before it): optional
# modifiers, an optional return type (with an optional single-line generic
# argument and `?`), then the declared name and its opening parenthesis.
# The parameter list itself is NOT matched here - it is walked with a
# balanced-parenthesis scanner (see _find_matching_paren), because a lazy
# `\((.*?)\)` regex stops at the wrong `)` for any non-trivial signature.
DART_DECL_RE = re.compile(
    r'^[ \t]*'
    r'(?P<mods>(?:(?:static|final|const|late|external|factory|abstract|covariant)\s+)*)'
    r'(?:(?P<type>[A-Za-z_$][\w$]*(?:<[^;{}()=\r\n]*>)?\??)[ \t]+)?'
    r'(?P<name>[A-Za-z_$][\w$]*)[ \t]*\(',
    re.MULTILINE
)

DART_CLASS_RE = re.compile(
    r'^[ \t]*(?:(?:abstract|base|final|sealed|interface|mixin)\s+)*'
    r'class\s+(?P<name>[A-Za-z_$][\w$]*)',
    re.MULTILINE
)


def _find_matching_paren(text, open_idx):
    """Return the index of the ')' matching the '(' at open_idx, skipping
    string literals, or -1 when unbalanced. Comments must already be
    stripped from text."""
    depth = 0
    i = open_idx
    n = len(text)
    while i < n:
        c = text[i]
        if c == '"' or c == "'":
            quote = c
            i += 1
            while i < n and text[i] != quote:
                if text[i] == "\\":
                    i += 1
                i += 1
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _dart_decl_terminator(text, idx):
    """Classify what follows a declaration's closing ')': returns '{', '=>',
    ';', ':' (constructor initializer list) or None. Skips whitespace and
    the async/async*/sync* modifiers."""
    n = len(text)
    while idx < n and text[idx].isspace():
        idx += 1
    m = re.match(r'(?:async\*?|sync\*)', text[idx:])
    if m:
        idx += m.end()
        while idx < n and text[idx].isspace():
            idx += 1
    if idx >= n:
        return None
    if text[idx] == "{":
        return "{"
    if text.startswith("=>", idx):
        return "=>"
    if text[idx] == ";":
        return ";"
    if text[idx] == ":":
        return ":"
    return None


def _dartdoc_before(lines, line_idx):
    """Collect the contiguous /// DartDoc block immediately above
    lines[line_idx], allowing @annotation lines between the doc and the
    declaration."""
    i = line_idx - 1
    while i >= 0 and lines[i].strip().startswith("@"):
        i -= 1
    doc = []
    while i >= 0 and lines[i].strip().startswith("///"):
        doc.append(lines[i].strip())
        i -= 1
    return "\n".join(reversed(doc))


def parse_dart_file(filepath):
    """Parse Dart file and extract documentation information."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return None

    stripped = strip_comments_except_docs(content, is_ts=False)
    lines = stripped.splitlines()
    line_start_to_idx = {}
    pos = 0
    for idx, line in enumerate(lines):
        line_start_to_idx[pos] = idx
        pos += len(line) + 1

    classes = []
    functions = []
    seen_functions = set()

    for match in DART_CLASS_RE.finditer(stripped):
        class_name = match.group("name")
        if class_name.startswith("_"):
            continue
        line_idx = line_start_to_idx.get(match.start(), 0)
        dartdoc = _dartdoc_before(lines, line_idx)
        classes.append({
            "name": class_name,
            "docstring": clean_dartdoc(dartdoc) if dartdoc else "",
            "methods": []
        })

    for match in DART_DECL_RE.finditer(stripped):
        name = match.group("name")
        ret_type = match.group("type") or ""
        mods = (match.group("mods") or "").split()

        if name.startswith("_") or name in DART_STATEMENT_KEYWORDS:
            continue
        if ret_type in DART_STATEMENT_KEYWORDS:
            continue

        open_idx = match.end() - 1
        close_idx = _find_matching_paren(stripped, open_idx)
        if close_idx == -1:
            continue

        terminator = _dart_decl_terminator(stripped, close_idx + 1)
        if terminator is None:
            continue
        if terminator == ";" and not (ret_type or mods or name[0].isupper()):
            # `foo(...);` with no return type/modifier and a lowercase name
            # is a call statement, not an abstract/external declaration.
            continue
        if terminator == ":" and not name[0].isupper():
            # Initializer lists only follow constructors.
            continue

        args = clean_args_string(stripped[open_idx + 1:close_idx])
        dedupe_key = (name, args)
        if dedupe_key in seen_functions:
            continue
        seen_functions.add(dedupe_key)

        line_idx = line_start_to_idx.get(
            stripped.rfind("\n", 0, match.start()) + 1)
        if line_idx is None:
            line_idx = 0
        dartdoc = _dartdoc_before(lines, line_idx)

        decl_source = stripped[match.start():close_idx + 1]
        signature = clean_args_string(decl_source)
        functions.append({
            "name": name,
            "args": args,
            "signature": signature,
            "docstring": clean_dartdoc(dartdoc) if dartdoc else "",
            "whitelisted": True,
            "hash": hashlib.sha256(decl_source.encode("utf-8")).hexdigest(),
            "source": decl_source
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
            "User-Agent": "curl/7.81.0",
            "x-trace-id": "gh-docs-run"
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
    groq_api_key = os.environ.get("GROQ_API_KEY") or os.environ.get("GROQ_API")
    if not groq_api_key:
        return None  # Caller handles missing key; no per-function log spam

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

def get_fence_language(filepath):
    """Fence language tag for signature code blocks (MD040 wants one)."""
    ext = os.path.splitext(filepath)[1]
    if ext == ".py":
        return "python"
    if ext in [".ts", ".tsx"]:
        return "typescript"
    if ext == ".dart":
        return "dart"
    return "text"

def wrap_markdown_text(text, width=MD_LINE_LIMIT):
    """Wrap prose lines to the markdownlint line limit. Fenced code and
    table lines are left alone; unbreakable long tokens stay on their own
    line (MD013 only flags lines with a space past the limit)."""
    out = []
    in_fence = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence or len(line) <= width or stripped.startswith("|"):
            out.append(line)
            continue
        indent = line[:len(line) - len(line.lstrip())]
        marker = re.match(r'(?:[-*+]\s+|\d+[.)]\s+|>\s*)', stripped)
        subsequent = indent + " " * (marker.end() if marker else 0)
        out.extend(textwrap.wrap(
            line, width=width,
            subsequent_indent=subsequent,
            break_long_words=False, break_on_hyphens=False,
        ) or [line])
    return "\n".join(out)

def _split_top_level_args(args):
    """Split a parameter list at commas that sit outside any nested
    brackets or string literals."""
    parts = []
    depth = 0
    quote = None
    start = 0
    i = 0
    while i < len(args):
        c = args[i]
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c in "([{<":
            depth += 1
        elif c in ")]}>":
            depth -= 1
        elif c == "," and depth == 0:
            parts.append(args[start:i].strip())
            start = i + 1
        i += 1
    tail = args[start:].strip()
    if tail:
        parts.append(tail)
    return parts

def format_signature_lines(signature, width=MD_LINE_LIMIT):
    """Format a signature for a fenced code block: one line when it fits,
    otherwise one parameter per line (Dart optional-parameter {...}/[...]
    wrappers hug the parentheses)."""
    if len(signature) <= width:
        return [signature]
    open_idx = signature.find("(")
    close_idx = signature.rfind(")")
    if open_idx == -1 or close_idx <= open_idx:
        return textwrap.wrap(
            signature, width=width, subsequent_indent="    ",
            break_long_words=False, break_on_hyphens=False) or [signature]
    prefix = signature[:open_idx]
    inner = signature[open_idx + 1:close_idx].strip()
    suffix = signature[close_idx + 1:].strip()
    open_wrap = close_wrap = ""
    if inner[:1] in "{[" and inner[-1:] in "}]":
        open_wrap, close_wrap = inner[0], inner[-1]
        inner = inner[1:-1].strip().rstrip(",")
    lines = [f"{prefix}({open_wrap}"]
    parts = _split_top_level_args(inner)
    for idx, part in enumerate(parts):
        line = f"  {part}," if idx < len(parts) - 1 or open_wrap else f"  {part}"
        if len(line) > width:
            lines.extend(textwrap.wrap(
                line, width=width, subsequent_indent="      ",
                break_long_words=False, break_on_hyphens=False))
        else:
            lines.append(line)
    lines.append(f"{close_wrap}){suffix}" if suffix else f"{close_wrap})")
    return lines

def append_heading(lines, level, name, args, fn_prefix, lang, signature=None):
    """Append a symbol heading, spilling signatures that would overflow the
    heading line into a fenced code block below a short heading. A blank
    line always follows the heading (MD022)."""
    marker = "#" * level
    full = f"{marker} `{fn_prefix}{name}({args})`"
    if len(full) <= MD_LINE_LIMIT:
        lines.append(full)
        lines.append("")
        return
    lines.append(f"{marker} `{fn_prefix}{name}`")
    lines.append("")
    lines.append(f"```{lang}")
    lines.extend(format_signature_lines(signature or f"{fn_prefix}{name}({args})"))
    lines.append("```")
    lines.append("")

def lint_clean_markdown(text):
    """Final normalization pass: exactly one blank line around headings,
    no consecutive blank lines, single trailing newline. Fenced blocks are
    left untouched."""
    out = []
    in_fence = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            if not in_fence and out and out[-1] != "":
                out.append("")
            in_fence = not in_fence
            out.append(line)
            if not in_fence:
                out.append("")
            continue
        if in_fence:
            out.append(line)
            continue
        if line == "":
            if not out or out[-1] == "":
                continue
            out.append(line)
            continue
        if line.startswith("#") and out and out[-1] != "":
            out.append("")
        if out and out[-1].startswith("#"):
            out.append("")
        out.append(line)
    return "\n".join(out).strip() + "\n"

def append_symbol_doc_body(lines, item, ai_cache, check_only):
    """Append the description for a symbol: its docstring, a cached or
    freshly generated AI doc, or the no-doc placeholder. Prose is wrapped
    to the markdownlint line limit."""
    if item["docstring"]:
        lines.append(wrap_markdown_text(item["docstring"].strip()))
    else:
        cached_hash, cached_doc = ai_cache.get(item["name"], (None, None))
        if cached_hash == item["hash"]:
            lines.append(f"<!-- {item['hash']} -->")
            lines.append(wrap_markdown_text(cached_doc))
        elif not check_only:
            ai_doc = generate_ai_doc(item["source"], item["name"], item["args"])
            if ai_doc:
                lines.append(f"<!-- {item['hash']} -->")
                lines.append(wrap_markdown_text(ai_doc))
            else:
                lines.append("*No documentation provided (generation failed).*")
        else:
            if cached_hash and cached_doc:
                lines.append(f"<!-- {item['hash']} -->")
                lines.append(wrap_markdown_text(cached_doc))
            else:
                lines.append("*No documentation provided.*")
    lines.append("")

def generate_markdown(filepath, rel_path, spec, existing_md_content="", check_only=False, target_dir="."):
    """Generate Markdown representation of the Python, TS, or Dart specification."""
    lines = []
    basename = os.path.basename(filepath)
    module_name = os.path.splitext(basename)[0]
    fn_prefix = get_fn_prefix(filepath)
    lang = get_fence_language(filepath)

    ai_cache = extract_cached_ai_docs(existing_md_content) if existing_md_content else {}

    # Use git root for the source file path in the documentation
    git_root = find_git_root(filepath)
    git_rel_path = os.path.relpath(filepath, git_root)

    lines.append(f"# API Reference: {module_name}")
    lines.append("")
    lines.append(f"Source file: `{git_rel_path.replace(os.sep, '/')}`")
    lines.append("")

    if spec["module_doc"]:
        lines.append("## Module Description")
        lines.append("")
        lines.append(wrap_markdown_text(spec["module_doc"].strip()))
        lines.append("")

    if spec["classes"]:
        lines.append("## Classes")
        lines.append("")
        for cls in spec["classes"]:
            lines.append(f"### class `{cls['name']}`")
            lines.append("")
            if cls["docstring"]:
                lines.append(wrap_markdown_text(cls["docstring"].strip()))
                lines.append("")

            whitelisted_methods = [m for m in cls["methods"] if m["whitelisted"]]
            other_methods = [m for m in cls["methods"] if not m["whitelisted"] and m["docstring"]]

            # Filter unused class methods
            whitelisted_methods = [m for m in whitelisted_methods if is_function_used(m["name"], filepath, target_dir)]
            other_methods = [m for m in other_methods if is_function_used(m["name"], filepath, target_dir)]

            if whitelisted_methods:
                lines.append("#### Whitelisted API Methods")
                lines.append("")
                for method in whitelisted_methods:
                    append_heading(lines, 5, method["name"], method["args"],
                                   "", lang, method.get("signature"))
                    append_symbol_doc_body(lines, method, ai_cache, check_only)

            if other_methods:
                lines.append("#### Documented Internal Methods")
                lines.append("")
                for method in other_methods:
                    append_heading(lines, 5, method["name"], method["args"],
                                   "", lang, method.get("signature"))
                    if method["docstring"]:
                        lines.append(wrap_markdown_text(method["docstring"].strip()))
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
                append_heading(lines, 3, func["name"], func["args"],
                               fn_prefix, lang, func.get("signature"))
                append_symbol_doc_body(lines, func, ai_cache, check_only)

        if other_funcs:
            lines.append("## Documented Module Functions")
            lines.append("")
            for func in other_funcs:
                append_heading(lines, 3, func["name"], func["args"],
                               fn_prefix, lang, func.get("signature"))
                if func["docstring"]:
                    lines.append(wrap_markdown_text(func["docstring"].strip()))
                lines.append("")

    return lint_clean_markdown("\n".join(lines))

# Stack mapping for per-stack documentation output nested inside each stack
# directory: a doc for a source file goes to <stack_dir>/docs/api/<name>.md,
# where <stack_dir> is the nearest ancestor directory named after the stack
# (dart for .dart, frappe for .py, nextjs for .ts/.tsx). SDK repos are laid
# out <module>/{dart,frappe,nextjs}/, so e.g.
#   fav/dart/lib/src/di/fav_di.dart -> fav/dart/docs/api/fav_dart_lib_src_di_fav_di.md
# Files with no such ancestor fall back to <git_root>/<stack>/docs/api/.
STACK_PARSERS = {
    "dart": parse_dart_file,
    "frappe": parse_python_file,
    "nextjs": parse_ts_file,
}

def get_file_stack(filename):
    """Map a source filename to its documentation stack (dart, frappe, nextjs) or None."""
    if filename.endswith(".dart"):
        # Skip generated Dart files — same exclusions as before the per-stack split.
        if filename.endswith((".freezed.dart", ".g.dart", ".gr.dart")) or filename == "app_assets.dart":
            return None
        return "dart"
    if filename.endswith((".ts", ".tsx")):
        return "nextjs"
    if filename.endswith(".py"):
        return "frappe"
    return None

def detect_stacks(target_dir):
    """Detect every documentation stack present under target_dir (dart, frappe, nextjs)."""
    stacks = set()
    for root, dirs, files in os.walk(target_dir):
        dirs[:] = [d for d in dirs if d not in [".git", "env", "node_modules", "__pycache__", ".next", "dist", ".dart_tool", "build", "docs", ".rokct", "Compliance"]]
        for file in files:
            stack = get_file_stack(file)
            if stack:
                stacks.add(stack)
        if stacks == set(STACK_PARSERS):
            break
    return sorted(stacks)

def is_excluded(target_dir):
    exclude_path = os.path.join(target_dir, ".exclude")
    if os.path.isfile(exclude_path):
        with open(exclude_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        if not content.strip():
            return True
        return "update_docs" in content
    return False

def get_stack_docs_dir(filepath, stack, git_root):
    """Return the docs/api dir for a source file: nested inside the nearest
    ancestor directory named after the file's stack (dart, frappe, nextjs).
    Falls back to <git_root>/<stack>/docs/api when no such ancestor exists."""
    git_root_p = Path(git_root).resolve()
    curr = Path(filepath).resolve().parent
    while True:
        if curr.name == stack:
            return os.path.join(str(curr), "docs", "api")
        if curr == git_root_p or curr == curr.parent:
            break
        curr = curr.parent
    return os.path.join(git_root, stack, "docs", "api")

def find_legacy_doc(docs_api_dir, stack, out_md_name):
    """Locate a doc under either legacy layout: per-stack docs/api/<stack>/<name>.md
    (preferred, newer) or pre-split flat docs/api/<name>.md."""
    legacy_paths = [
        os.path.join(docs_api_dir, stack, out_md_name),
        os.path.join(docs_api_dir, out_md_name),
    ]
    return [p for p in legacy_paths if os.path.isfile(p)]

def read_first_content(paths):
    """Return the content of the first readable file in paths, else empty string."""
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            continue
    return ""

def remove_legacy_docs(legacy_paths, git_root):
    """Delete legacy docs (flat docs/api/<name>.md or docs/api/<stack>/<name>.md)
    once their nested per-stack replacement exists."""
    for legacy_md_path in legacy_paths:
        try:
            os.remove(legacy_md_path)
            if LOGGER:
                LOGGER.info(f"Migrated legacy doc: removed {os.path.relpath(legacy_md_path, git_root).replace(os.sep, '/')}")
        except OSError:
            pass

def prune_empty_legacy_dirs(docs_api_dir):
    """Remove now-empty legacy docs/api/<stack>/ and docs/api/ directories."""
    for stack in STACK_PARSERS:
        stack_dir = os.path.join(docs_api_dir, stack)
        if os.path.isdir(stack_dir):
            try:
                os.rmdir(stack_dir)
                if LOGGER:
                    LOGGER.info(f"Pruned empty legacy dir: docs/api/{stack}/")
            except OSError:
                pass
    if os.path.isdir(docs_api_dir):
        try:
            os.rmdir(docs_api_dir)
            if LOGGER:
                LOGGER.info("Pruned empty legacy dir: docs/api/")
        except OSError:
            pass

def scan_and_sync(target_dir, check_only=False):
    """Scan directory and sync docs into each stack directory (<stack_dir>/docs/api/) for every stack present."""
    global LOGGER
    target_dir = os.path.abspath(target_dir)
    git_root = find_git_root(target_dir)
    # Legacy locations only — new docs live inside each stack directory.
    docs_api_dir = os.path.join(git_root, "docs", "api")

    if LOGGER is None:
        LOGGER = setup_logger(target_dir)

    if is_excluded(target_dir):
        if LOGGER:
            LOGGER.info(f"Repo exclusion found (.exclude). Skipping auto-creation for {target_dir}")
        return []

    stacks = detect_stacks(target_dir)
    if LOGGER:
        LOGGER.info(f"Detected stacks: {', '.join(stacks) if stacks else 'none'} for {target_dir}")

    out_of_sync = []

    for root, dirs, files in os.walk(target_dir):
        dirs[:] = [d for d in dirs if d not in [".git", "env", "node_modules", "__pycache__", ".next", "dist", ".dart_tool", "build", "docs", ".rokct", "Compliance"]]
        for file in files:
            stack = get_file_stack(file)
            if not stack:
                continue
            parser_func = STACK_PARSERS[stack]

            filepath = os.path.join(root, file)
            spec = parser_func(filepath)
            if not spec:
                continue

            rel_path = os.path.relpath(filepath, target_dir)

            rel_dir = os.path.relpath(root, git_root)
            if rel_dir == ".":
                out_md_name = f"{os.path.splitext(file)[0]}.md"
            else:
                out_md_name = f"{rel_dir.replace(os.sep, '_')}_{os.path.splitext(file)[0]}.md"

            # The flattened-from-repo-root filename is kept as-is — only the
            # location changes, so migration is a pure move and names stay
            # collision-safe when shells union docs later.
            stack_docs_dir = get_stack_docs_dir(filepath, stack, git_root)
            out_md_path = os.path.join(stack_docs_dir, out_md_name)
            # Earlier layouts wrote docs to git-root docs/api/ (flat) and then
            # docs/api/<stack>/ — migrate (reuse cached AI docs, then delete)
            # so repos converge.
            legacy_paths = find_legacy_doc(docs_api_dir, stack, out_md_name)

            if not os.path.exists(out_md_path):
                existing_content = read_first_content(legacy_paths)
                if LOGGER:
                    LOGGER.info(f"Auto-creating missing documentation for: {rel_path}")
                md_content = generate_markdown(filepath, rel_path, spec, existing_md_content=existing_content, check_only=False, target_dir=target_dir)
                os.makedirs(stack_docs_dir, exist_ok=True)
                with open(out_md_path, "w", encoding="utf-8") as f:
                    f.write(md_content)
                if legacy_paths:
                    remove_legacy_docs(legacy_paths, git_root)
                if LOGGER:
                    LOGGER.info(f"Auto-created missing doc: {os.path.relpath(out_md_path, target_dir)} <- {rel_path}")
            else:
                with open(out_md_path, "r", encoding="utf-8") as f:
                    existing_content = f.read()

                md_content = generate_markdown(filepath, rel_path, spec, existing_md_content=existing_content, check_only=check_only, target_dir=target_dir)

                if existing_content != md_content:
                    out_of_sync.append((out_md_path, md_content, existing_content, rel_path))
                    if not check_only:
                        os.makedirs(stack_docs_dir, exist_ok=True)
                        with open(out_md_path, "w", encoding="utf-8") as f:
                            f.write(md_content)
                        if LOGGER:
                            LOGGER.info(f"Synced: {os.path.relpath(out_md_path, target_dir)} <- {rel_path}")
                if legacy_paths and not check_only:
                    remove_legacy_docs(legacy_paths, git_root)

    # Legacy docs/api/<stack>/ and docs/api/ dirs are pruned once emptied by
    # the migration above (rmdir is a no-op while files remain).
    prune_empty_legacy_dirs(docs_api_dir)

    # Free memory after scan — the cache can be very large for big Flutter projects
    FILE_CONTENTS_CACHE.clear()
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

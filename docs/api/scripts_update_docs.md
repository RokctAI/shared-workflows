# API Reference: update_docs

Source file: `scripts/update_docs.py`

## Documented Module Functions

### `def is_whitelisted(node)`
Check if the function has a @frappe.whitelist or @whitelist decorator.

### `def get_args_string(node)`
Format function arguments to a readable string.

### `def parse_python_file(filepath)`
Parse python file and extract documentation information.

### `def generate_ai_doc(func_source, func_name, args_string)`
Use Groq API to generate a natural language description for a Python function.

### `def extract_cached_ai_docs(md_content)`
Parse existing markdown and return a mapping of function name -> (hash, doc).

### `def generate_markdown(filepath, rel_path, spec, existing_md_content='', check_only=False)`
Generate Markdown representation of the Python specification.

### `def scan_and_sync(target_dir, check_only=False)`
Scan directory and sync docs to target_dir/docs/api/.

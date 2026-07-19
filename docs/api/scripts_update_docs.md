# API Reference: update_docs

Source file: `scripts/update_docs.py`

## Documented Module Functions

### `def find_git_root(start_path)`
Traverse upwards to find the root of the git repository.

### `def detect_project_type(target_dir)`
Detect the dominant project type (flutter, typescript, python, or data).

### `def is_whitelisted(node)`
Check if the function has a @frappe.whitelist or @whitelist decorator.

### `def scan_and_sync(target_dir, check_only=False)`
Scan directory and sync docs to git_root/docs/api/.

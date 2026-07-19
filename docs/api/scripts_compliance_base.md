# API Reference: base

Source file: `scripts/compliance/base.py`

## Classes

### class `PlatformComplianceVisitor`

## Documented Module Functions

### `def get_known_api_paths(filename)`
Return the known API path globs, plus a dynamic glob for the file's
top-level app directory (the scanner always runs from repo root, so the
first non-'.' path segment IS the app/module name).

### `def is_frappe_whitelisted(node)`
True if a FunctionDef carries a (frappe.)whitelist decorator.

### `def collect_suppressions(content)`
Parse suppression directives out of file content.

Returns (file_level: set[str], line_level: dict[int, set[str]]) where
line numbers are 1-based and 'all' may appear in any set.

### `def is_suppressed(check_id, line_no, file_level, line_level)`
True if check_id at line_no is silenced by a suppression directive.

A line-level directive applies to its own line and the line directly below
it (so a comment above the offending line works).

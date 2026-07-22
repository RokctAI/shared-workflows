# API Reference: config

Source file: `scripts/compliance/config.py`

## Module Description
Per-repo compliance configuration.

Looks for `compliance.config.json` at the repo root (or wherever
COMPLIANCE_CONFIG points). Shape:

    {
      "exclude_dirs":   ["vendor", "third_party"],
      "exclude_paths":  ["legacy/**", "*/generated/*"],
      "severity":       {"nextjs-i18n": "off", "caching-cdn": "error"},
      "fail_on":        "error"
    }

  exclude_dirs  — directory names pruned during the walk (added to the built-in
                  defaults; they are no longer hardcoded in compliance_scanner.py)
  exclude_paths — fnmatch globs matched against the repo-relative path of each file
  severity      — per-check overrides; "error" | "warning" | "off"
  fail_on       — "error" (default) fails only on error-severity findings;
                  "warning" makes warnings fail the gate too

## Documented Module Functions

### `def load_config(start_dirs)`
Return (config_dict, config_path_or_None). Malformed config is non-fatal.

### `def is_path_excluded(filepath, config, base_dir=None)`
True if filepath matches any exclude_paths glob.

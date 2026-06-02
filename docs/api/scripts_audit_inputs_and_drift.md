# API Reference: audit_inputs_and_drift

Source file: `scripts/audit_inputs_and_drift.py`

## Documented Module Functions

### `def parse_semver(version_str)`
Parse version string like '1.2.3' or 'v1.2.3-rc' into major, minor, patch.

### `def check_version_drift(latest_version_str)`
Scan all workflows in .github/workflows for version drift against latest_version.

### `def audit_inputs()`
Scan workflows for deprecated or unpinned parameters.

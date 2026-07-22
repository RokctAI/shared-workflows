# API Reference: controls

Source file: `scripts/compliance/controls.py`

## Module Description
Central control-ID registry for the compliance scanner.

Every check emitted by the 18 layers has a short internal check-id. This table
maps each check-id to:
  * title      — human-readable name of the check
  * layer      — which layer module owns it
  * soc2       — SOC 2 Trust Services Criteria control
  * iso27001   — ISO/IEC 27001:2022 Annex A control
  * severity   — default severity ("error" fails the gate, "warning" reports only)

This is the single place where new compliance frameworks hook in: add a new
field (e.g. "nist") to the entries and surface it in the evidence writer.

Layers attach a legacy human-readable "type" string to each finding; the
TYPE_TO_CHECK map resolves that string to the check-id so the scanner and
evidence writer can annotate findings with their real control IDs.

## Documented Module Functions

### `def resolve_check(type_str)`
Resolve a layer 'type' string to its check-id ('unmapped' if unknown).

### `def annotate(error, severity_overrides=None)`
Attach check-id, severity and framework control IDs to a finding dict.

severity_overrides: optional {check-id: "error"|"warning"|"off"} from the
per-repo compliance.config.json.

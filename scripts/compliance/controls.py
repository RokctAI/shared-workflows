# Copyright 2026 RokctAI
"""Central control-ID registry for the compliance scanner.

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
"""

# The scan run itself is ongoing-monitoring evidence (SOC 2 CC7.1). The
# run-summary evidence file (and the CI evidence auto-push) stays under this ID.
SCAN_RUN_CONTROL_ID = "SOC2-CC7.1-COMPLIANCE"

CONTROLS = {
    # ── Layer 2 — API contracts & structure ─────────────────────────────────
    # KNOWN GAP: structural presence check only — the path glob is self-satisfying
    # and validates nothing about API conventions. See layer_2.py and the README.
    "api-unknown-path":      {"title": "Whitelisted function present; path NOT validated against API conventions (known gap)", "layer": "2",  "soc2": "CC8.1", "iso27001": "A.8.26", "severity": "warning"},
    "api-docstring":         {"title": "Whitelisted API missing docstring",       "layer": "2",  "soc2": "CC8.1", "iso27001": "A.8.25", "severity": "warning"},
    "api-type-safety":       {"title": "Whitelisted API missing type hints",      "layer": "2",  "soc2": "CC8.1", "iso27001": "A.8.28", "severity": "error"},
    "flutter-dynamic-type":  {"title": "Raw 'dynamic' types in Flutter",          "layer": "2",  "soc2": "CC8.1", "iso27001": "A.8.28", "severity": "warning"},
    "structural-special-dirs": {"title": "Python files under forbidden dirs",     "layer": "2",  "soc2": "CC8.1", "iso27001": "A.8.9",  "severity": "error"},

    # ── Layer 3 — Database ──────────────────────────────────────────────────
    "sql-injection":         {"title": "Raw SQL instead of ORM",                  "layer": "3",  "soc2": "CC7.1", "iso27001": "A.8.28", "severity": "error"},
    "db-migrations":         {"title": "DocType change without migration patch",  "layer": "3",  "soc2": "CC8.1", "iso27001": "A.8.32", "severity": "error"},

    # ── Layers 4 & 5 — Secrets & secure headers ─────────────────────────────
    "py-hardcoded-secret":      {"title": "Hardcoded secret (Python)",            "layer": "4-5", "soc2": "CC6.1", "iso27001": "A.5.17", "severity": "error"},
    "nextjs-hardcoded-secret":  {"title": "Hardcoded secret (Next.js)",           "layer": "4-5", "soc2": "CC6.1", "iso27001": "A.5.17", "severity": "error"},
    "flutter-hardcoded-secret": {"title": "Hardcoded secret (Flutter)",           "layer": "4-5", "soc2": "CC6.1", "iso27001": "A.5.17", "severity": "error"},
    "nextjs-i18n":              {"title": "Hardcoded UI string not wrapped in t()", "layer": "4-5", "soc2": "CC8.1", "iso27001": "A.8.28", "severity": "warning"},
    "nginx-secure-headers":     {"title": "Missing secure response headers",      "layer": "5",  "soc2": "CC6.6", "iso27001": "A.8.9",  "severity": "error"},

    # ── Layer 6 — Rate limiting ─────────────────────────────────────────────
    "nginx-rate-limiting":   {"title": "Nginx server without limit_req",          "layer": "6",  "soc2": "CC6.6", "iso27001": "A.8.20", "severity": "error"},

    # ── Layer 7 — Caching & CDN ─────────────────────────────────────────────
    "caching-cdn":           {"title": "Missing caching/CDN directives",          "layer": "7",  "soc2": "A1.1",  "iso27001": "A.8.6",  "severity": "warning"},

    # ── Layer 8 — Scaling ───────────────────────────────────────────────────
    "docker-memory-limits":  {"title": "Compose service without memory limits",   "layer": "8",  "soc2": "A1.1",  "iso27001": "A.8.6",  "severity": "warning"},

    # ── Layer 9 — Containers ────────────────────────────────────────────────
    "dockerfile-multistage": {"title": "Dockerfile without multi-stage build",    "layer": "9",  "soc2": "CC8.1", "iso27001": "A.8.9",  "severity": "warning"},

    # ── Layer 10 — Architecture & deployment ────────────────────────────────
    "nextjs-clean-architecture":  {"title": "UI component imports DB clients",    "layer": "10", "soc2": "CC8.1", "iso27001": "A.8.27", "severity": "error"},
    "flutter-clean-architecture": {"title": "Widget makes raw HTTP calls",        "layer": "10", "soc2": "CC8.1", "iso27001": "A.8.27", "severity": "error"},
    "flutter-presentation-db":    {"title": "Widget imports local DB directly",   "layer": "10", "soc2": "CC8.1", "iso27001": "A.8.27", "severity": "error"},
    "flutter-presentation-logic": {"title": "Widget contains low-level business logic", "layer": "10", "soc2": "CC8.1", "iso27001": "A.8.27", "severity": "warning"},
    "hardcoded-ip":               {"title": "Hardcoded public IP in deploy files", "layer": "10", "soc2": "CC8.1", "iso27001": "A.8.9",  "severity": "error"},
    "localhost-decoupling":       {"title": "Hardcoded localhost/loopback URL",   "layer": "10", "soc2": "CC8.1", "iso27001": "A.8.9",  "severity": "warning"},

    # ── Layer 11 — Auth & token lifecycle ───────────────────────────────────
    "auth-hardcoded-token":  {"title": "Hardcoded credential literal",            "layer": "11", "soc2": "CC6.1", "iso27001": "A.5.17", "severity": "error"},
    "auth-token-expiry":     {"title": "Token issued/used without expiry",        "layer": "11", "soc2": "CC6.1", "iso27001": "A.8.5",  "severity": "error"},
    "auth-token-storage":    {"title": "Token in insecure client storage",        "layer": "11", "soc2": "CC6.1", "iso27001": "A.8.5",  "severity": "error"},
    "auth-token-rotation":   {"title": "Token use without refresh/rotation",      "layer": "11", "soc2": "CC6.1", "iso27001": "A.5.18", "severity": "warning"},

    # ── Layer 12 — Observability ────────────────────────────────────────────
    # KNOWN GAP: same self-satisfying path glob as api-unknown-path.
    "obs-unknown-api-path":  {"title": "Whitelisted function present; observability skipped, path NOT validated (known gap)", "layer": "12", "soc2": "CC7.2", "iso27001": "A.8.16", "severity": "warning"},
    "obs-trace-logging":     {"title": "API without trace-id/stderr logging",     "layer": "12", "soc2": "CC7.2", "iso27001": "A.8.15", "severity": "error"},
    "obs-db-tracing":        {"title": "DB query without trace propagation",      "layer": "12", "soc2": "CC7.2", "iso27001": "A.8.15", "severity": "error"},
    # Deliberately a warning, not an error: the fleet has ~174 existing copies of
    # the no-op appeasement line. This check makes the migration queue visible
    # without turning every repo red overnight; escalate once the queue drains.
    "obs-noop-trace":        {"title": "No-op trace line (reads x-trace-id, propagates nothing)", "layer": "12", "soc2": "CC7.2", "iso27001": "A.8.15", "severity": "warning"},
    "obs-flutter-trace":     {"title": "Flutter HTTP without telemetry SDK trace propagation", "layer": "12", "soc2": "CC7.2", "iso27001": "A.8.16", "severity": "error"},
    "obs-nextjs-trace":      {"title": "Next.js HTTP without trace propagation",  "layer": "12", "soc2": "CC7.2", "iso27001": "A.8.16", "severity": "error"},
    "obs-crash-reporting":   {"title": "Flutter entrypoint without crash reporting", "layer": "12", "soc2": "CC7.2", "iso27001": "A.8.16", "severity": "error"},
    "obs-analytics":         {"title": "Flutter entrypoint without analytics",    "layer": "12", "soc2": "CC7.2", "iso27001": "A.8.16", "severity": "warning"},
    "obs-python-trace":      {"title": "Python HTTP without trace header",        "layer": "12", "soc2": "CC7.2", "iso27001": "A.8.15", "severity": "error"},
    "flutter-keyboard-avoidance": {"title": "Inputs without keyboard avoidance (usability)", "layer": "12", "soc2": "CC8.1", "iso27001": "A.8.28", "severity": "warning"},
    # APP-SPECIFIC: only applies to the Gravity app (see layer_12.py).
    "gravity-error-reporting": {"title": "APP-SPECIFIC (Gravity): mutations without error telemetry", "layer": "12", "soc2": "CC7.2", "iso27001": "A.8.16", "severity": "error"},

    # ── Layer 13 — Availability & backup ────────────────────────────────────
    "backup-tests":              {"title": "Backup/recovery script without tests", "layer": "13", "soc2": "A1.3", "iso27001": "A.8.13", "severity": "error"},
    "backup-volume-persistence": {"title": "DB service without persistent volumes", "layer": "13", "soc2": "A1.2", "iso27001": "A.8.13", "severity": "error"},

    # ── Layer 14 — LLM orchestration ────────────────────────────────────────
    "llm-orchestration":     {"title": "LLM service missing templates/limits/fallback", "layer": "14", "soc2": "CC8.1", "iso27001": "A.8.26", "severity": "warning"},

    # ── Layer 15 — Webhooks & integration ───────────────────────────────────
    "http-timeout":          {"title": "Python HTTP call without timeout",        "layer": "15", "soc2": "A1.1",  "iso27001": "A.8.6",  "severity": "error"},
    "flutter-http-timeout":  {"title": "Flutter HTTP client without timeout",     "layer": "15", "soc2": "A1.1",  "iso27001": "A.8.6",  "severity": "error"},
    "webhook-signature":     {"title": "Webhook handler without signature verification", "layer": "15", "soc2": "CC6.7", "iso27001": "A.8.26", "severity": "error"},

    # ── Layer 16 — Multi-tenant isolation ───────────────────────────────────
    "tenant-isolation":      {"title": "Tenant queries without isolation filters", "layer": "16", "soc2": "CC6.1", "iso27001": "A.5.15", "severity": "error"},
    "tenant-quota":          {"title": "AI service without usage quota checks",   "layer": "16", "soc2": "A1.1",  "iso27001": "A.8.6",  "severity": "error"},

    # ── Layer 17 — Edge / IoT ───────────────────────────────────────────────
    "iot-edge-buffering":    {"title": "IoT module without offline buffering/sync", "layer": "17", "soc2": "A1.2", "iso27001": "A.8.14", "severity": "warning"},

    # ── Layer 18 — Zero trust & process hardening ───────────────────────────
    "ztna-authz":            {"title": "Auth/API module without zero-trust checks", "layer": "18", "soc2": "CC6.1", "iso27001": "A.5.15", "severity": "error"},
    "path-traversal":        {"title": "Path joins without containment validation", "layer": "18", "soc2": "CC7.1", "iso27001": "A.8.28", "severity": "error"},
    "command-injection":     {"title": "subprocess with shell=True",              "layer": "18", "soc2": "CC7.1", "iso27001": "A.8.28", "severity": "error"},
    "thread-safety":         {"title": "Global mutable state mutated without a lock", "layer": "18", "soc2": "CC7.1", "iso27001": "A.8.28", "severity": "error"},
    "thread-exception-logging": {"title": "Background threads without exception logging", "layer": "18", "soc2": "CC7.2", "iso27001": "A.8.15", "severity": "error"},

    # ── Layer 19 — Event-driven architecture ────────────────────────────────
    "event-driven":          {"title": "Event module without publisher/consumer/broker", "layer": "19", "soc2": "CC8.1", "iso27001": "A.8.27", "severity": "error"},

    # ── Scanner-internal / meta ─────────────────────────────────────────────
    "syntax-error":          {"title": "Source file fails to parse",              "layer": "meta", "soc2": "CC7.1", "iso27001": "A.8.28", "severity": "error"},
    "project-type":          {"title": "Unrecognized project type",               "layer": "meta", "soc2": "CC7.1", "iso27001": "A.8.9",  "severity": "error"},
    "unmapped":              {"title": "Check with no registered control mapping", "layer": "meta", "soc2": "CC7.1", "iso27001": "A.8.16", "severity": "error"},
}

# Legacy human-readable "type" strings (as emitted by the layer modules)
# resolved to check-ids. Every type string a layer can emit MUST appear here —
# the test suite asserts this stays complete.
TYPE_TO_CHECK = {
    "Layer 2 (Whitelisted Function - Path Not Validated)": "api-unknown-path",
    # Legacy label kept so older evidence readers still resolve:
    "Layer 2 (Unknown API Path)":                       "api-unknown-path",
    "Layer 2 (API/Documentation)":                      "api-docstring",
    "Layer 2 (API/Type Safety)":                        "api-type-safety",
    "Layer 2 (Type Safety - Flutter)":                  "flutter-dynamic-type",
    "Layer 2 (Structural)":                             "structural-special-dirs",
    "Layer 3 (Database / ORM Enforcement)":             "sql-injection",
    "Layer 3 (Database Integrity)":                     "db-migrations",
    "Layer 4 & 5 (Security)":                           "py-hardcoded-secret",
    "Layer 4 & 5 (Security - Next.js)":                 "nextjs-hardcoded-secret",
    "Layer 4 & 5 (Localization - Next.js)":             "nextjs-i18n",
    "Layer 4 & 5 (Security - Flutter)":                 "flutter-hardcoded-secret",
    "Layer 5 (Security - Secure Headers)":              "nginx-secure-headers",
    "Layer 6 (Rate Limiting)":                          "nginx-rate-limiting",
    "Layer 7 (Caching & CDN)":                          "caching-cdn",
    "Layer 7 (Caching & CDN - Next.js)":                "caching-cdn",
    "Layer 8 (Load Balancing & Scaling)":               "docker-memory-limits",
    "Layer 9 (Containers)":                             "dockerfile-multistage",
    "Layer 10 (Clean Architecture - Next.js)":          "nextjs-clean-architecture",
    "Layer 10 (Clean Architecture - Flutter)":          "flutter-clean-architecture",
    "Layer 10 (Clean Architecture - Flutter Local DB)": "flutter-presentation-db",
    "Layer 10 (Clean Architecture - Flutter Business Logic)": "flutter-presentation-logic",
    "Layer 10 (Hosting & Deployment Safety)":           "hardcoded-ip",
    "Layer 10 (Localhost Decoupling Gate)":             "localhost-decoupling",
    "Layer 11 (Auth - Hardcoded Token)":                "auth-hardcoded-token",
    "Layer 11 (Auth - Missing Token Expiry)":           "auth-token-expiry",
    "Layer 11 (Auth - Missing Token Expiry Check)":     "auth-token-expiry",
    "Layer 11 (Auth - Insecure Token Storage)":         "auth-token-storage",
    "Layer 11 (Auth - Missing Token Rotation)":         "auth-token-rotation",
    "Layer 12 (Whitelisted Function - Path Not Validated, Observability Skipped)": "obs-unknown-api-path",
    # Legacy label kept so older evidence readers still resolve:
    "Layer 12 (Unknown API Path - Observability Skipped)": "obs-unknown-api-path",
    "Layer 12 (Observability)":                         "obs-trace-logging",
    "Layer 12 (Observability - DB Tracing)":            "obs-db-tracing",
    "Layer 12 (Observability - No-op Trace Line)":      "obs-noop-trace",
    "Layer 12 (Observability - Flutter Trace ID)":      "obs-flutter-trace",
    "Layer 12 (Observability - Next.js Trace ID)":      "obs-nextjs-trace",
    "Layer 12 (Observability - Crash Reporting)":       "obs-crash-reporting",
    "Layer 12 (Observability - Analytics)":             "obs-analytics",
    "Layer 12 (Observability - Python Trace ID)":       "obs-python-trace",
    "Layer 12 (Usability - Keyboard Avoidance)":        "flutter-keyboard-avoidance",
    "Layer 12 (APP-SPECIFIC Gravity - Error Reporting)": "gravity-error-reporting",
    # Legacy label kept so older evidence readers still resolve:
    "Layer 12 (Observability - Gravity Error Reporting)": "gravity-error-reporting",
    "Layer 13 (Availability & Backup)":                 "backup-tests",
    "Layer 13 (Availability & Backup - Volume Persistence)": "backup-volume-persistence",
    "Layer 14 (Agentic & LLM Orchestration)":           "llm-orchestration",
    "Layer 15 (Webhook & Integration Federation)":      "http-timeout",
    "Layer 15 (Webhook & Integration - Flutter HTTP Timeout)": "flutter-http-timeout",
    "Layer 15 (Webhook Federation)":                    "webhook-signature",
    "Layer 16 (Multi-Tenant Isolation Gate)":           "tenant-isolation",
    "Layer 16 (Quota Isolation Gate)":                  "tenant-quota",
    "Layer 17 (Edge IoT)":                              "iot-edge-buffering",
    "Layer 18 (ZTNA & mTLS)":                           "ztna-authz",
    "Layer 18 (ZTNA & path containment checks)":        "path-traversal",
    "Layer 18 (Process execution security hardening)":  "command-injection",
    "Layer 18 (Thread Concurrency Safety)":             "thread-safety",
    "Layer 18 (Background Thread Exception Safety)":    "thread-exception-logging",
    "Layer 19 (Event-Driven Architecture)":             "event-driven",
    "Syntax Error":                                     "syntax-error",
    "Parse Error":                                      "syntax-error",
    "Project Type Detection":                           "project-type",
}

VALID_SEVERITIES = ("error", "warning", "off")


def resolve_check(type_str):
    """Resolve a layer 'type' string to its check-id ('unmapped' if unknown)."""
    return TYPE_TO_CHECK.get(type_str, "unmapped")


def annotate(error, severity_overrides=None):
    """Attach check-id, severity and framework control IDs to a finding dict.

    severity_overrides: optional {check-id: "error"|"warning"|"off"} from the
    per-repo compliance.config.json.
    """
    check_id = error.get("check") or resolve_check(error.get("type", ""))
    control = CONTROLS.get(check_id, CONTROLS["unmapped"])
    severity = control["severity"]
    if severity_overrides and check_id in severity_overrides:
        override = severity_overrides[check_id]
        if override in VALID_SEVERITIES:
            severity = override
    error["check"] = check_id
    error["severity"] = severity
    error["soc2"] = control["soc2"]
    error["iso27001"] = control["iso27001"]
    return error

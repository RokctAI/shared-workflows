# Compliance Scanner

Static compliance gate for the ROKCT fleet. Walks a repo's source, runs ~50 checks
grouped into 18 layers, maps every finding to a **SOC 2** and an **ISO/IEC
27001:2022 Annex A** control, and writes an auditable evidence record.

Entry point: [`scripts/compliance_scanner.py`](../compliance_scanner.py).
Wired into `.github/workflows/universal-pipeline.yml`.

```bash
python scripts/compliance_scanner.py <dir-or-file> [...]   # scan specific targets
python scripts/compliance_scanner.py                       # scan cwd
python scripts/compliance_scanner.py <dir> --verbose        # every finding, not a summary
```

Exit code `1` if any **error**-severity finding survives; warnings report but do
not block (configurable — see `fail_on`).

---

## Contents

- [Architecture](#architecture)
- [Control mapping table](#control-mapping-table)
- [Known gap: the API-path check validates nothing](#known-gap-the-api-path-check-validates-nothing)
- [Suppression syntax](#suppression-syntax)
- [Configuration](#configuration)
- [What each layer checks](#what-each-layer-checks)
- [Adding a new check](#adding-a-new-check)
- [Tests](#tests)
- [App-specific rules](#app-specific-rules)

---

## Architecture

| File | Role |
|---|---|
| `base.py` | Registry decorators, the AST visitor, shared path helpers, suppression parsing |
| `controls.py` | **The control table** — check-id → title, layer, SOC 2, ISO 27001, default severity |
| `config.py` | Loads per-repo `compliance.config.json` (exclusions, severity overrides) |
| `layer_*.py` | The checks themselves |
| `__init__.py` | Imports every layer (triggers registration), exposes `scan_file()` |

Checks register themselves via decorators:

```python
@register_file_checker          # gets a filepath, returns a list of findings
@register_ast_function_def      # called per FunctionDef  (visitor, node)
@register_ast_call              # called per Call         (visitor, node)
@register_ast_assign            # called per Assign       (visitor, node)
```

`scan_file()` runs every registered check, then annotates each finding with its
check-id, severity and framework control IDs via `controls.annotate()`, then
drops anything suppressed or configured `off`.

### Evidence output

Written under `.rokct/evidence/`:

- `SOC2-CC7.1-COMPLIANCE/<ts>_<PASS|FAIL>.json` — the **run record**. The scan
  itself is the SOC 2 CC7.1 ongoing-monitoring artifact, so this exists on pass
  as well as fail. In CI this file is committed and pushed (`[skip ci]`) — that
  push *is* the monitoring evidence trail and is deliberate.
- `checks/<check-id>__SOC2-<id>__ISO-<id>/<ts>_<FAIL|WARN>.json` — one record
  per check that actually fired, so each control has its own trail.

Every finding in both files carries `check_id`, `severity`, and
`controls.{soc2,iso27001}`. Paths, IPs and secrets are redacted on write.

---

## Control mapping table

Source of truth: `controls.py`. Adding a framework (NIST, PCI) means adding one
field here, not touching any layer.

| Check ID | Layer | Severity | SOC 2 | ISO 27001 | What it checks |
|---|---|---|---|---|---|
| `api-docstring` | 2 | warning | CC8.1 | A.8.25 | Whitelisted API missing docstring |
| `api-type-safety` | 2 | error | CC8.1 | A.8.28 | Whitelisted API missing type hints |
| `api-unknown-path` | 2 | warning | CC8.1 | A.8.26 | ⚠️ Whitelisted function present; path **not** validated — [known gap](#known-gap-the-api-path-check-validates-nothing) |
| `flutter-dynamic-type` | 2 | warning | CC8.1 | A.8.28 | Raw `dynamic` types in Flutter |
| `structural-special-dirs` | 2 | error | CC8.1 | A.8.9 | Python files under forbidden dirs |
| `db-migrations` | 3 | error | CC8.1 | A.8.32 | DocType change without migration patch |
| `sql-injection` | 3 | error | CC7.1 | A.8.28 | Raw SQL instead of ORM |
| `py-hardcoded-secret` | 4-5 | error | CC6.1 | A.5.17 | Hardcoded secret (Python) |
| `nextjs-hardcoded-secret` | 4-5 | error | CC6.1 | A.5.17 | Hardcoded secret (Next.js) |
| `flutter-hardcoded-secret` | 4-5 | error | CC6.1 | A.5.17 | Hardcoded secret (Flutter) |
| `nextjs-i18n` | 4-5 | warning | CC8.1 | A.8.28 | Hardcoded UI string not wrapped in `t()` |
| `nginx-secure-headers` | 5 | error | CC6.6 | A.8.9 | Missing secure response headers |
| `nginx-rate-limiting` | 6 | error | CC6.6 | A.8.20 | Nginx server without `limit_req` |
| `caching-cdn` | 7 | warning | A1.1 | A.8.6 | Missing caching/CDN directives |
| `docker-memory-limits` | 8 | warning | A1.1 | A.8.6 | Compose service without memory limits |
| `dockerfile-multistage` | 9 | warning | CC8.1 | A.8.9 | Dockerfile without multi-stage build |
| `nextjs-clean-architecture` | 10 | error | CC8.1 | A.8.27 | UI component imports DB clients |
| `flutter-clean-architecture` | 10 | error | CC8.1 | A.8.27 | Widget makes raw HTTP calls |
| `flutter-presentation-db` | 10 | error | CC8.1 | A.8.27 | Widget imports local DB directly |
| `flutter-presentation-logic` | 10 | warning | CC8.1 | A.8.27 | Widget contains low-level business logic |
| `hardcoded-ip` | 10 | error | CC8.1 | A.8.9 | Hardcoded public IP in deploy files |
| `localhost-decoupling` | 10 | warning | CC8.1 | A.8.9 | Hardcoded localhost/loopback URL |
| `auth-hardcoded-token` | 11 | error | CC6.1 | A.5.17 | Hardcoded credential literal |
| `auth-token-expiry` | 11 | error | CC6.1 | A.8.5 | Token issued/used without expiry |
| `auth-token-storage` | 11 | error | CC6.1 | A.8.5 | Token in insecure client storage |
| `auth-token-rotation` | 11 | warning | CC6.1 | A.5.18 | Token use without refresh/rotation |
| `obs-unknown-api-path` | 12 | warning | CC7.2 | A.8.16 | ⚠️ Observability skipped; path **not** validated — [known gap](#known-gap-the-api-path-check-validates-nothing) |
| `obs-trace-logging` | 12 | error | CC7.2 | A.8.15 | API without trace-id / stderr logging |
| `obs-db-tracing` | 12 | error | CC7.2 | A.8.15 | DB query without trace propagation |
| `obs-flutter-trace` | 12 | error | CC7.2 | A.8.16 | Flutter HTTP without trace header |
| `obs-python-trace` | 12 | error | CC7.2 | A.8.15 | Python HTTP without trace header |
| `obs-crash-reporting` | 12 | error | CC7.2 | A.8.16 | Flutter entrypoint without crash reporting |
| `obs-analytics` | 12 | warning | CC7.2 | A.8.16 | Flutter entrypoint without analytics |
| `flutter-keyboard-avoidance` | 12 | warning | CC8.1 | A.8.28 | Inputs without keyboard avoidance |
| `gravity-error-reporting` | 12 | error | CC7.2 | A.8.16 | **APP-SPECIFIC (Gravity)** — mutations without error telemetry |
| `backup-tests` | 13 | error | A1.3 | A.8.13 | Backup/recovery script without tests |
| `backup-volume-persistence` | 13 | error | A1.2 | A.8.13 | DB service without persistent volumes |
| `llm-orchestration` | 14 | warning | CC8.1 | A.8.26 | LLM service missing templates/limits/fallback |
| `http-timeout` | 15 | error | A1.1 | A.8.6 | Python HTTP call without timeout |
| `flutter-http-timeout` | 15 | error | A1.1 | A.8.6 | Flutter HTTP client without timeout |
| `webhook-signature` | 15 | error | CC6.7 | A.8.26 | Webhook handler without signature verification |
| `tenant-isolation` | 16 | error | CC6.1 | A.5.15 | Tenant queries without isolation filters |
| `tenant-quota` | 16 | error | A1.1 | A.8.6 | AI service without usage quota checks |
| `iot-edge-buffering` | 17 | warning | A1.2 | A.8.14 | IoT module without offline buffering/sync |
| `ztna-authz` | 18 | error | CC6.1 | A.5.15 | Auth/API module without zero-trust checks |
| `path-traversal` | 18 | error | CC7.1 | A.8.28 | Path joins without containment validation |
| `command-injection` | 18 | error | CC7.1 | A.8.28 | `subprocess` with `shell=True` |
| `thread-safety` | 18 | error | CC7.1 | A.8.28 | Global mutable state mutated without a lock |
| `thread-exception-logging` | 18 | error | CC7.2 | A.8.15 | Background threads without exception logging |
| `event-driven` | 19 | error | CC8.1 | A.8.27 | Event module without publisher/consumer/broker |
| `syntax-error` | meta | error | CC7.1 | A.8.28 | Source file fails to parse |
| `project-type` | meta | error | CC7.1 | A.8.9 | Unrecognized project type |
| `unmapped` | meta | error | CC7.1 | A.8.16 | Check with no registered control mapping |

**ISO 27001:2022 Annex A controls referenced:** A.5.15 (access control),
A.5.17 (authentication information), A.5.18 (access rights), A.8.5 (secure
authentication), A.8.6 (capacity management), A.8.9 (configuration management),
A.8.13 (information backup), A.8.14 (redundancy of processing facilities),
A.8.15 (logging), A.8.16 (monitoring activities), A.8.20 (network security),
A.8.25 (secure development lifecycle), A.8.26 (application security
requirements), A.8.27 (secure system architecture), A.8.28 (secure coding),
A.8.32 (change management).

---

## Known gap: the API-path check validates nothing

`api-unknown-path` and `obs-unknown-api-path` are **structural presence checks
only**. They do not validate that a `@frappe.whitelist` function lives anywhere
appropriate. Treat a pass as "a whitelisted function was seen", never as "this
endpoint's location was verified".

**Why.** `get_known_api_paths()` appends a glob derived from the file's *own*
first path segment (`*/<parts[0]>/*`). That glob therefore always matches the
file it came from, whenever the path has two or more segments. The test is
self-satisfying:

```text
./lms/frappe/src/rlms/api/course.py   → glob */lms/*        → passes  (legitimate)
./lms/frappe/src/rlms/helpers/misc.py → glob */lms/*        → passes  (no api/ dir)
./nonsense/deep/nowhere/rogue.py      → glob */nonsense/*   → passes  (no module at all)
./a/b/c/d/e/f.py                      → glob */a/*          → passes  (meaningless)
./rootlevel.py                        → glob */rootlevel.py/* → FIRES (only real trigger)
```

In practice the check fires **only** for a whitelisted function in a file at the
repo root. Everything nested passes regardless of where it sits.

**Measured impact.** In the `agent/` repo: **39 of 39** whitelisted files pass
this check, and **0 of 39** match any entry in `KNOWN_API_PATHS` — every one
passes on the self-derived glob alone (`agent` 33, `lms` 4, `replay` 1,
`subscriptions` 1).

**Status: deferred, not fixed.** Gating on real endpoint conventions is a
fleet-wide policy decision — which directories are legitimate homes for
whitelisted endpoints, per stack and per module — and needs proper review.
Removing the self-derived glob today would flag all 39 functions in `agent/`
alone, and comparable numbers fleet-wide. The leniency stays until that review
happens; the labels were corrected so the check stops claiming otherwise.

**A note for whoever does that review:** the obvious-looking fix — deriving the
glob from the *second* path segment to get per-module granularity — does not
work. CI runs the scanner from the repo root with no args
(`universal-pipeline.yml`), so paths arrive as `./lms/frappe/src/...` and
segment 2 is `frappe`, a directory every module shares. That would produce
`*/frappe/*` spanning the whole repo: strictly *more* permissive than today.
Segment 1 is already the module name in the CI invocation.

Behaviour is pinned by `TestUnknownApiPathGlob` in the test suite, which asserts
the tautological pass explicitly so the gap stays visible. When the glob is
tightened, `test_relative_nested_path_passes_tautologically` is the test that
should start failing — that is the intended signal to update this section.

---

## Suppression syntax

**One syntax, everywhere.** Both forms work behind any comment leader (`#`,
`//`, `///`) — the directive token is what gets matched, not the comment style.

```python
# compliance-ignore: <check-id>[, <check-id>...]        # this line + the line below
# compliance-ignore-file: <check-id>[, ...] | all       # the whole file
```

```python
def run(name):
    # compliance-ignore: sql-injection
    return frappe.db.sql("SELECT ...")   # reporting query, reviewed 2026-07
```

```dart
// compliance-ignore-file: obs-flutter-trace
```

Always suppress the *narrowest* thing that works: a line-level directive over a
file-level one, a specific check-id over `all`. Say why in an adjacent comment —
a bare suppression is indistinguishable from a mistake six months later.

### Legacy conventions (deprecated, honoured for one release)

Five ad hoc, undocumented escape hatches were unified into the above. Each still
works for one release, then gets deleted:

| Legacy | Silenced | Replace with |
|---|---|---|
| `# compliance-silent` | `structural-special-dirs` | `# compliance-ignore-file: structural-special-dirs` |
| docstring contains `raw_sql` / `bypass_sql` / `complex_query` | `sql-injection` | `# compliance-ignore: sql-injection` |
| `ignore-observability` in a Dart file | `obs-flutter-trace` | `// compliance-ignore-file: obs-flutter-trace` |
| `// compliance: ignore-keyboard-avoidance` (3 spellings) | `flutter-keyboard-avoidance` | `// compliance-ignore: flutter-keyboard-avoidance` |
| the bare word `bypass` anywhere in a Dart file | `obs-flutter-trace` | **removed, not deprecated** — see below |

The bare `bypass` substring was deleted outright rather than deprecated: it
silenced any Dart file that merely contained the word in unrelated prose, which
is not a suppression mechanism but an accident. No file in this workspace relied
on it (verified: 3 Dart files contain the word, none make HTTP calls).

---

## Configuration

Drop `compliance.config.json` at a repo root (or point `COMPLIANCE_CONFIG` at
one). Discovery walks upward from the scan target.

```json
{
  "exclude_dirs":  ["vendor", "third_party"],
  "exclude_paths": ["legacy/**", "*/generated/*"],
  "severity":      { "nextjs-i18n": "off", "caching-cdn": "error" },
  "fail_on":       "error"
}
```

| Key | Effect |
|---|---|
| `exclude_dirs` | Directory *names* pruned during the walk, added to the built-in defaults |
| `exclude_paths` | `fnmatch` globs against each file's path |
| `severity` | Per-check override: `error` \| `warning` \| `off` |
| `fail_on` | `error` (default) — warnings don't block. `warning` — everything blocks |

Exclusions used to be hardcoded in `compliance_scanner.py`; a repo now tunes the
gate without editing scanner source.

---

## What each layer checks

| Layer | Theme | Checks |
|---|---|---|
| 2 | API contracts & structure | Whitelisted Frappe APIs need docstrings and param + return type hints. (The "must live in a known API path" test is present but **validates nothing** — see [known gap](#known-gap-the-api-path-check-validates-nothing).) No raw `dynamic` in Dart; no Python under `.github/` or `.rokct/` |
| 3 | Database | No raw `frappe.db.sql()`; DocType schema changes need a migration patch |
| 4 & 5 | Secrets & headers | Hardcoded credentials across Python/TS/Dart; i18n enforcement on JSX strings; Nginx `X-Frame-Options` + `X-Content-Type-Options` |
| 6 | Rate limiting | Nginx server/location blocks need `limit_req` |
| 7 | Caching & CDN | `next.config`, Nginx, and route handlers need cache directives |
| 8 | Scaling | Compose services need memory limits |
| 9 | Containers | Dockerfiles should be multi-stage |
| 10 | Architecture & deploy | Presentation layer must not import DB clients or do raw HTTP/serialization; no hardcoded public IPs or localhost URLs |
| 11 | Auth & token lifecycle | No hardcoded tokens; tokens need expiry, secure storage, and rotation |
| 12 | Observability | Trace-ID propagation (Python, Dart, DB queries); structured stderr logging; crash reporting and analytics in Flutter entrypoints; keyboard avoidance |
| 13 | Availability & backup | Backup scripts need tests; DB services need persistent volumes |
| 14 | LLM orchestration | Prompt templates, token budgets, fallback paths |
| 15 | Webhooks & integration | HTTP timeouts (Python + Dart); webhook signature verification |
| 16 | Multi-tenant isolation | Tenant filters on queries; quota gates on AI services |
| 17 | Edge / IoT | Offline buffering and sync protocols |
| 18 | Zero trust & hardening | Authorization checks; path containment; no `shell=True`; lock-guarded global state; background-thread exception logging |
| 19 | Event-driven | Event modules need a publisher/consumer/broker |
| 20 | Documentation sync | Runs on a clean pass (`update_docs.py`), not a gate |

> **Note on layers 11/12 tracing:** the Flutter trace checks accept *any* Dio
> interceptor that injects `x-trace-id`. Tightening them to require
> `telemetry_sdk` specifically is queued for after that SDK's Dart client
> exists — doing it now would fail every app. Leave these as they are.

---

## Adding a new check

1. **Register the control** in `controls.py` — add a `CONTROLS` entry (check-id,
   title, layer, `soc2`, `iso27001`, `severity`) and a `TYPE_TO_CHECK` row
   mapping your finding's `type` string to the check-id. A finding whose type
   isn't mapped resolves to `unmapped`, and a test fails on that.

2. **Write the check** in the layer module it belongs to:

   ```python
   @register_file_checker
   def check_layer9_something(filepath):
       errors = []
       if not filepath.endswith(".py"):
           return errors
       ...
       errors.append({
           "line": lineno,
           "type": "Layer 9 (Containers)",   # must exist in TYPE_TO_CHECK
           "message": "What is wrong, and what to do about it.",
       })
       return errors
   ```

   Normalize paths with `filepath.replace("\\", "/")` before matching directory
   boundaries — unnormalized `"/components/"` tests silently never fire on
   Windows. Don't add a bespoke bypass keyword; suppression is handled centrally.

3. **Add fixtures** to `CASES` in `scripts/tests/test_compliance_layers.py`: one
   source string that must trip the check, one that must not.

4. **Pick a severity honestly.** `error` for anything in the injection/secrets/
   isolation class. `warning` for heuristics with real false-positive rates
   (the i18n JSX-string check is the archetype — it guesses at what "looks like
   user-facing text").

---

## Tests

```bash
python scripts/tests/test_compliance_layers.py
python -m unittest discover -s scripts/tests    # equivalent
```

Stdlib `unittest` — no pytest dependency, so it runs anywhere the scanner does.
Covers a positive + negative fixture per check, the control table's internal
consistency, suppression parsing, severity overrides, and the two checks with a
history of false confidence (thread-safety genericity, Gravity rule scoping).

Fixtures are written to a temp dir whose path deliberately avoids the substrings
`test` and `compliance` — several layers skip such paths, which would silently
mask a real regression.

---

## App-specific rules

`gravity-error-reporting` is hardcoded to one app: `/gravity/` paths, the literal
helpers `push_workspace` / `write_workspace_file`, and the literal telemetry sink
`send_error_to_control()`. It is named, titled, and documented as app-specific so
it can't be misread as a general observability guarantee — it proves nothing about
any other repo.

If another app wants an equivalent guarantee, give it its own clearly-labelled
rule. Do not extend this one by adding app names to it.

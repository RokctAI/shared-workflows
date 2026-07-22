# API Reference: test_compliance_layers

Source file: `scripts/tests/test_compliance_layers.py`

## Module Description
Test suite for the compliance scanner's own check layers.

Every check registered in compliance/controls.py gets at least one positive
fixture (code that MUST trip it) and one negative fixture (code that MUST NOT).
Fixtures are written to a throwaway temp dir and run through the real scan_file
entry point, so registration, annotation and suppression are all exercised.

Run:  python scripts/tests/test_compliance_layers.py
      python -m unittest discover -s scripts/tests    (also works)

Note on cross-talk: one fixture often trips several checks (a Dart file with a
raw Dio import trips both the architecture and the trace-id checks). Assertions
are therefore per-check membership tests, never "this file has exactly N
findings".

## Classes

### class `TestCheckFixtures`
Positive + negative fixture per registered check.

### class `TestUnknownApiPathGlob`
Path-glob behaviour for api-unknown-path / obs-unknown-api-path.

This class documents a KNOWN GAP rather than asserting a working gate.

`matches_known_api_path()` appends a glob built from the file's OWN first
path segment (`*/<parts[0]>/*`), so it matches its own file whenever the
path has two or more segments. The check is therefore self-satisfying for
any nested file and only fires for a file at the repo root.

An earlier version of this suite asserted the positive case using a Windows
ABSOLUTE temp path. That passed for the wrong reason: `parts[0]` became the
drive letter `c:`, producing the glob `*/c:/*`, which fails to match by
coincidence of path shape — not because the check validated anything. The
tests below pin BOTH path forms and assert what each actually does, so the
gap stays visible instead of reading as a green gate.

When the fleet-wide endpoint-convention review lands and the glob is
tightened, `test_relative_nested_path_passes_tautologically` is the test
that should start failing. That is the intended signal.

### class `TestThreadSafetyGenericity`
The thread-safety check must work on arbitrary global names.

The previous implementation only recognised three literal names from one
script; these cases would all have been missed.

### class `TestGravityRuleIsScoped`
The Gravity rule is app-specific by design and must stay that way.

### class `TestSuppressionSyntax`
Unified '# compliance-ignore: <check-id>' syntax.

### class `TestSeverityAndOverrides`

### class `TestControlsTable`

### class `TestWalkExclusions`
The walk must not prune the very directories a check is looking for.

### class `TestDatabaseMigrations`
check_database_migrations runs outside scan_file, on the changed-file list.

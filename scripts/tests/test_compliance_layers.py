#!/usr/bin/env python3
# Copyright 2026 RokctAI
"""Test suite for the compliance scanner's own check layers.

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
"""

import os
import shutil
import sys
import tempfile
import unittest

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS_DIR)

from compliance import scan_file, check_database_migrations  # noqa: E402
from compliance import controls  # noqa: E402
from compliance.base import (  # noqa: E402
    collect_suppressions,
    is_suppressed,
    matches_known_api_path,
    get_known_api_paths,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixture table: check_id -> (relative path, violating source, clean source)
# ─────────────────────────────────────────────────────────────────────────────

WHITELIST_CLEAN = (
    'import frappe\n'
    '@frappe.whitelist()\n'
    'def get_thing(name: str) -> dict:\n'
    '    """Return a thing by name."""\n'
    '    import sys\n'
    '    trace_id = frappe.local.request.headers.get("x-trace-id")\n'
    '    sys.stderr.write(trace_id)\n'
    '    return {}\n'
)

CASES = {
    # ── Layer 2 ─────────────────────────────────────────────────────────────
    # NOTE: 'api-unknown-path' and 'obs-unknown-api-path' are deliberately NOT
    # in this table. Their behaviour depends on the path FORM (relative vs
    # absolute), which this generic harness absolutises into a temp dir — a
    # fixture here would assert a coincidence rather than the real behaviour.
    # See TestUnknownApiPathGlob, which pins both forms explicitly.
    "api-docstring": (
        "api/auth/svc.py",
        'import frappe\n@frappe.whitelist()\ndef f(a: int) -> dict:\n    return {}\n',
        'api/auth/svc.py|' + WHITELIST_CLEAN,
    ),
    "api-type-safety": (
        "api/auth/svc.py",
        'import frappe\n@frappe.whitelist()\ndef f(a):\n    """Doc."""\n    return {}\n',
        'api/auth/svc.py|' + WHITELIST_CLEAN,
    ),
    "flutter-dynamic-type": (
        "lib/model.dart",
        'class M {\n  final Map<String, dynamic> data;\n}\n',
        'class M {\n  final Map<String, String> data;\n}\n',
    ),
    "structural-special-dirs": (
        ".github/helper.py",
        'x = 1\n',
        'src/helper.py|x = 1\n',
    ),

    # ── Layer 3 ─────────────────────────────────────────────────────────────
    "sql-injection": (
        "app/queries.py",
        'import frappe\n'
        'def run(name):\n'
        '    """Fetch rows."""\n'
        '    return frappe.db.sql("SELECT * FROM tabUser")\n',
        'import frappe\n'
        'def run(name):\n'
        '    """Fetch rows."""\n'
        '    return frappe.get_all("User")\n',
    ),

    # ── Layers 4 & 5 ────────────────────────────────────────────────────────
    "py-hardcoded-secret": (
        "app/conf.py",
        'api_token = "sk_live_abcdef123456"\n',
        'import os\napi_token = os.environ.get("API_TOKEN")\n',
    ),
    "nextjs-hardcoded-secret": (
        "web/settings.ts",
        'const apiSecret = "sk_live_abcdefghijklmnopq";\n',
        'const apiSecret = process.env.API_SECRET;\n',
    ),
    # NB: not under lib/ — layer_4_5 deliberately excludes /lib/ paths.
    "flutter-hardcoded-secret": (
        "mobile/config.dart",
        "final apiKey = 'abcdefghij1234567890';\n",
        "final apiKey = dotenv.env['API_KEY'];\n",
    ),
    "nextjs-i18n": (
        "web/page.tsx",
        'export const P = () => <div title="Welcome to the dashboard" />;\n',
        'export const P = () => <div title={t("welcome")} />;\n',
    ),
    "nginx-secure-headers": (
        "deploy/site.conf",
        'server {\n  listen 80;\n}\n',
        'server {\n'
        '  listen 80;\n'
        '  add_header X-Frame-Options "SAMEORIGIN";\n'
        '  add_header X-Content-Type-Options "nosniff";\n'
        '}\n',
    ),

    # ── Layer 6 ─────────────────────────────────────────────────────────────
    "nginx-rate-limiting": (
        "deploy/site.conf",
        'server {\n  listen 80;\n}\n',
        'limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;\n'
        'server {\n  listen 80;\n  limit_req zone=api;\n}\n',
    ),

    # ── Layer 7 ─────────────────────────────────────────────────────────────
    "caching-cdn": (
        "deploy/site.conf",
        'server {\n  listen 80;\n}\n',
        'server {\n  listen 80;\n  expires 30d;\n}\n',
    ),

    # ── Layer 8 ─────────────────────────────────────────────────────────────
    "docker-memory-limits": (
        "docker-compose.yml",
        'services:\n  web:\n    image: nginx\n',
        'services:\n  web:\n    image: nginx\n    mem_limit: 512m\n',
    ),

    # ── Layer 9 ─────────────────────────────────────────────────────────────
    "dockerfile-multistage": (
        "Dockerfile",
        'FROM python:3.11\nRUN pip install .\n',
        'FROM python:3.11 AS build\nRUN pip install .\nFROM python:3.11-slim\n',
    ),

    # ── Layer 10 ────────────────────────────────────────────────────────────
    "nextjs-clean-architecture": (
        "app/components/Card.tsx",
        'import { db } from "drizzle-orm";\nexport const C = () => null;\n',
        'export const C = () => null;\n',
    ),
    "flutter-clean-architecture": (
        "lib/presentation/home.dart",
        "import 'package:dio/dio.dart';\nclass Home {}\n",
        "class Home {}\n",
    ),
    "flutter-presentation-db": (
        "lib/widgets/list.dart",
        "import 'package:isar/isar.dart';\nclass L {}\n",
        "class L {}\n",
    ),
    "flutter-presentation-logic": (
        "lib/pages/detail.dart",
        "class D {\n  void load() { jsonDecode('{}'); }\n}\n",
        "class D {\n  void load() {}\n}\n",
    ),
    "hardcoded-ip": (
        "deploy/hosts.yml",
        'app:\n  host: 8.8.8.8\n',
        'app:\n  host: 10.0.0.4\n',
    ),
    "localhost-decoupling": (
        "web/client.ts",
        'const base = "http://localhost:3000";\n',
        'const base = process.env.NEXT_PUBLIC_API_URL;\n',
    ),

    # ── Layer 11 ────────────────────────────────────────────────────────────
    "auth-hardcoded-token": (
        "app/session.py",
        'access_token = "abcdef1234567890"\n',
        'import os\naccess_token = os.environ.get("ACCESS_TOKEN")\n',
    ),
    "auth-token-expiry": (
        "app/issue.py",
        'def go(u):\n    return create_token(u)\n',
        'def go(u):\n    return create_token(u, expires_in=3600)\n',
    ),
    "auth-token-storage": (
        "web/store.ts",
        'localStorage.setItem("access_token", t);\n',
        'document.cookie = "session=1; HttpOnly";\n',
    ),
    "auth-token-rotation": (
        "web/apiclient.ts",
        'const h = { Authorization: `Bearer ${access_token}` };\n',
        'const h = { Authorization: `Bearer ${access_token}` };\n'
        'export const refreshToken = () => {};\n',
    ),

    # ── Layer 12 ────────────────────────────────────────────────────────────
    "obs-trace-logging": (
        "api/auth/handler.py",
        'import frappe\n'
        '@frappe.whitelist()\n'
        'def f(a: int) -> dict:\n'
        '    """Doc."""\n'
        '    return {}\n',
        'api/auth/handler.py|' + WHITELIST_CLEAN,
    ),
    "obs-db-tracing": (
        "app/people.py",
        'import frappe\n'
        'def load(name):\n'
        '    """Load a record."""\n'
        '    return frappe.get_doc("User", name)\n',
        'import frappe\n'
        'def load(name):\n'
        '    """Load a record."""\n'
        '    trace_id = frappe.local.trace_id\n'
        '    return frappe.get_doc("User", name)\n',
    ),
    "obs-flutter-trace": (
        "lib/remote/client.dart",
        "import 'package:dio/dio.dart';\n"
        "final d = Dio(BaseOptions(connectTimeout: Duration(seconds: 5)));\n",
        "import 'package:dio/dio.dart';\n"
        "final d = Dio(BaseOptions(\n"
        "  connectTimeout: Duration(seconds: 5),\n"
        "  headers: {'x-trace-id': traceId},\n"
        "));\n",
    ),
    "obs-crash-reporting": (
        "lib/main.dart",
        "void main() { runApp(App()); }\n",
        "import 'package:sentry_flutter/sentry_flutter.dart';\n"
        "// firebase_analytics wired in bootstrap\n"
        "void main() { SentryFlutter.init((o) {}); }\n",
    ),
    "obs-analytics": (
        "lib/main.dart",
        "void main() { runApp(App()); }\n",
        "import 'package:firebase_analytics/firebase_analytics.dart';\n"
        "import 'package:sentry_flutter/sentry_flutter.dart';\n"
        "void main() { FirebaseAnalytics.instance.logEvent(name: 'start'); }\n",
    ),
    "obs-python-trace": (
        "app/fetcher.py",
        'import requests\n'
        'def go(url):\n'
        '    return requests.get(url, timeout=5)\n',
        'import requests\n'
        'def go(url, trace_id):\n'
        '    return requests.get(url, timeout=5, headers={"x-trace-id": trace_id})\n',
    ),
    "flutter-keyboard-avoidance": (
        "lib/screens/login.dart",
        "class S {\n"
        "  build() => Scaffold(\n"
        "    resizeToAvoidBottomInset: false,\n"
        "    body: TextField(),\n"
        "  );\n"
        "}\n",
        "class S {\n"
        "  build() => Scaffold(\n"
        "    resizeToAvoidBottomInset: false,\n"
        "    body: Padding(\n"
        "      padding: MediaQuery.of(context).viewInsets,\n"
        "      child: TextField(),\n"
        "    ),\n"
        "  );\n"
        "}\n",
    ),
    # APP-SPECIFIC rule — only fires under /gravity/. The negative fixture is the
    # identical file outside /gravity/, which is the point: it does not generalize.
    "gravity-error-reporting": (
        "gravity/actions.py",
        'def push_workspace(x):\n    return x\n',
        'otherapp/actions.py|def push_workspace(x):\n    return x\n',
    ),

    # ── Layer 13 ────────────────────────────────────────────────────────────
    "backup-volume-persistence": (
        "docker-compose.yml",
        'services:\n  db:\n    image: postgres\n    mem_limit: 512m\n',
        'services:\n  db:\n    image: postgres\n    mem_limit: 512m\n'
        '    volumes:\n      - pgdata:/var/lib/postgresql/data\n',
    ),

    # ── Layer 14 ────────────────────────────────────────────────────────────
    "llm-orchestration": (
        "app/chat.py",
        'def send(x):\n    return x\n',
        'SYSTEM_PROMPT = "you are"\n'
        'def send(x):\n'
        '    """Send with budget + fallback."""\n'
        '    max_tokens = 100\n'
        '    try:\n'
        '        return x\n'
        '    except Exception:\n'
        '        return None\n',
    ),

    # ── Layer 15 ────────────────────────────────────────────────────────────
    "http-timeout": (
        "app/caller.py",
        'import requests\n'
        'def go(url):\n'
        '    return requests.get(url, headers={"x-trace-id": "1"})\n',
        'import requests\n'
        'def go(url):\n'
        '    return requests.get(url, timeout=5, headers={"x-trace-id": "1"})\n',
    ),
    "flutter-http-timeout": (
        "lib/net/client.dart",
        "import 'package:dio/dio.dart';\n"
        "final d = Dio(BaseOptions(headers: {'x-trace-id': t}));\n",
        "import 'package:dio/dio.dart';\n"
        "final d = Dio(BaseOptions(\n"
        "  connectTimeout: Duration(seconds: 5),\n"
        "  headers: {'x-trace-id': t},\n"
        "));\n",
    ),
    "webhook-signature": (
        "app/webhook_handler.py",
        'def handle(payload):\n    return payload\n',
        'import hmac\n'
        'def handle(payload, signature):\n'
        '    """Verify the HMAC sha256 signature."""\n'
        '    return hmac.compare_digest(signature, payload)\n',
    ),

    # ── Layer 16 ────────────────────────────────────────────────────────────
    "tenant-isolation": (
        "rcore/service.py",
        'import frappe\n'
        'def load():\n'
        '    """Load rows."""\n'
        '    return frappe.get_all("Note")\n',
        'import frappe\n'
        'def load(tenant_id):\n'
        '    """Load rows for the tenant."""\n'
        '    return frappe.get_all("Note", filters={"tenant": tenant_id})\n',
    ),
    "tenant-quota": (
        "rcore/chat.py",
        'def send(msg, tenant):\n    return msg\n',
        'def send(msg, tenant):\n'
        '    """Send within quota."""\n'
        '    if free_rok_msg_count(tenant) > 0:\n'
        '        return msg\n',
    ),

    # ── Layer 17 ────────────────────────────────────────────────────────────
    "iot-edge-buffering": (
        "app/iot_bridge.py",
        'def read():\n    return 1\n',
        'def read():\n'
        '    """Read via mqtt with an offline buffer."""\n'
        '    return mqtt.poll()\n',
    ),

    # ── Layer 18 ────────────────────────────────────────────────────────────
    "ztna-authz": (
        "app/auth_gateway.py",
        'def handle(req):\n    return req\n',
        'def handle(req):\n'
        '    """Verify the jwt and check permission."""\n'
        '    return verify(req)\n',
    ),
    "path-traversal": (
        "app/files.py",
        'import os\n'
        'def read(base, name):\n'
        '    return open(os.path.join(base, name))\n',
        'import os\n'
        'def read(base, name):\n'
        '    p = os.path.abspath(os.path.join(base, name))\n'
        '    if not p.startswith(os.path.abspath(base)):\n'
        '        raise ValueError("escape")\n'
        '    return open(p)\n',
    ),
    "command-injection": (
        "app/runner.py",
        'import subprocess\n'
        'def go(cmd):\n'
        '    return subprocess.run(cmd, shell=True)\n',
        'import subprocess\n'
        'def go(cmd):\n'
        '    return subprocess.run(["ls", cmd])\n',
    ),
    "thread-safety": (
        "app/state.py",
        'import threading\n'
        'CACHE = {}\n'
        'def put(k, v):\n'
        '    CACHE[k] = v\n',
        'import threading\n'
        'CACHE = {}\n'
        '_lock = threading.Lock()\n'
        'def put(k, v):\n'
        '    with _lock:\n'
        '        CACHE[k] = v\n',
    ),
    "thread-exception-logging": (
        "app/worker.py",
        'import threading\n'
        'def spawn():\n'
        '    threading.Thread(target=run).start()\n',
        'import sys\n'
        'import threading\n'
        'def spawn():\n'
        '    try:\n'
        '        threading.Thread(target=run).start()\n'
        '    except Exception as e:\n'
        '        sys.stderr.write(str(e))\n',
    ),

    # ── Layer 19 ────────────────────────────────────────────────────────────
    "event-driven": (
        "app/event_bus.py",
        'def handle(x):\n    return x\n',
        'def handle(x):\n'
        '    """Publish to the broker."""\n'
        '    return publish(x)\n',
    ),
}


def _write(root, relpath, content):
    full = os.path.join(root, relpath.replace("/", os.sep))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    return full


def _split_spec(default_path, spec):
    """A fixture may override its path with 'path|content'."""
    if spec is None:
        return None, None
    if "|" in spec.split("\n")[0]:
        head, rest = spec.split("|", 1)
        return head, rest
    return default_path, spec


class TestCheckFixtures(unittest.TestCase):
    """Positive + negative fixture per registered check."""

    def setUp(self):
        # Temp root must not contain 'test' or 'compliance' — several layers
        # deliberately skip such paths, which would mask a real regression.
        self.root = tempfile.mkdtemp(prefix="fixt_")
        self.assertNotIn("test", self.root.lower().replace("fixt_", ""))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _checks_for(self, relpath, content):
        case_dir = tempfile.mkdtemp(prefix="c_", dir=self.root)
        full = _write(case_dir, relpath, content)
        return {e["check"] for e in scan_file(full)}

    def test_positive_fixtures_trip_their_check(self):
        for check_id, (path, bad, _good) in sorted(CASES.items()):
            with self.subTest(check=check_id, case="positive"):
                p, c = _split_spec(path, bad)
                self.assertIn(
                    check_id, self._checks_for(p, c),
                    f"{check_id}: violating fixture did not trip the check",
                )

    def test_negative_fixtures_stay_clean(self):
        for check_id, (path, _bad, good) in sorted(CASES.items()):
            if good is None:
                continue
            with self.subTest(check=check_id, case="negative"):
                p, c = _split_spec(path, good)
                self.assertNotIn(
                    check_id, self._checks_for(p, c),
                    f"{check_id}: clean fixture produced a false positive",
                )

    def test_unknown_api_path_negative(self):
        """api-unknown-path / obs-unknown-api-path clear inside a known API path."""
        found = self._checks_for("api/auth/svc.py", WHITELIST_CLEAN)
        self.assertNotIn("api-unknown-path", found)
        self.assertNotIn("obs-unknown-api-path", found)


class TestUnknownApiPathGlob(unittest.TestCase):
    """Path-glob behaviour for api-unknown-path / obs-unknown-api-path.

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
    """

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="fixt_")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _checks_for_literal_path(self, path_str):
        """Resolve checks for a path string WITHOUT touching the filesystem.

        The glob logic is a pure function of the path string, so this exercises
        it directly — no temp-dir absolutisation to muddy which form is tested.
        """
        return matches_known_api_path(path_str)

    # ── The two path forms, asserted honestly ───────────────────────────────

    def test_relative_nested_path_passes_tautologically(self):
        """KNOWN GAP: a CI-style relative path always satisfies its own glob.

        This is the form CI actually produces (scanner runs from repo root with
        no args, per universal-pipeline.yml). Nothing about the location is
        validated — `./nonsense/deep/nowhere/rogue.py` passes exactly as
        `./lms/frappe/src/rlms/api/course.py` does.
        """
        for relative_path in (
            "./lms/frappe/src/rlms/api/course.py",     # legitimate endpoint
            "./lms/frappe/src/rlms/helpers/misc.py",   # no api/ dir
            "./nonsense/deep/nowhere/rogue.py",        # no module at all
            "./a/b/c/d/e/f.py",                        # meaningless nesting
        ):
            with self.subTest(path=relative_path):
                self.assertTrue(
                    self._checks_for_literal_path(relative_path),
                    "KNOWN GAP changed: relative nested paths are expected to "
                    "pass tautologically until the endpoint-convention review "
                    "tightens the glob. If this now fails, update this test and "
                    "the README's known-gap note together.",
                )

    def test_absolute_path_fails_by_drive_letter_coincidence(self):
        """A Windows absolute path mismatches because parts[0] is the drive.

        Asserted explicitly so nobody mistakes this for the check working: the
        derived glob is `*/c:/*`, which is nonsense, not path validation.
        """
        absolute_path = r"C:\Users\someone\AppData\Local\Temp\fixt_ab12\somewhere\svc.py"
        self.assertFalse(self._checks_for_literal_path(absolute_path))
        self.assertEqual("*/c:/*", get_known_api_paths(absolute_path)[-1],
                         "the mismatch must come from the drive letter, not from "
                         "any real convention check")

    def test_repo_root_file_is_the_only_real_trigger(self):
        """A single-segment relative path has no glob that can match it."""
        self.assertFalse(self._checks_for_literal_path("./rootlevel.py"))

    def test_known_static_api_path_matches(self):
        """The static KNOWN_API_PATHS entries still work as written."""
        self.assertTrue(self._checks_for_literal_path("./app/api/auth/login.py"))

    # ── End-to-end, through the real scanner ────────────────────────────────

    def test_end_to_end_rogue_function_is_not_flagged(self):
        """Documents the gap through scan_file(), not just the helper.

        A whitelisted function in a nonexistent module with no api/ directory
        produces NO unknown-path finding. Fully-typed and documented so the
        downstream layer-2 checks stay quiet and the assertion is unambiguous.
        """
        case_dir = tempfile.mkdtemp(prefix="c_", dir=self.root)
        _write(case_dir, "nonsense/deep/nowhere/rogue.py", WHITELIST_CLEAN)
        cwd = os.getcwd()
        try:
            os.chdir(case_dir)  # reproduce CI's relative-path invocation
            found = {e["check"] for e in scan_file("./nonsense/deep/nowhere/rogue.py")}
        finally:
            os.chdir(cwd)
        self.assertNotIn("api-unknown-path", found)
        self.assertNotIn("obs-unknown-api-path", found)

    def test_end_to_end_repo_root_function_is_flagged(self):
        """The one case that does still fire, through the real scanner."""
        case_dir = tempfile.mkdtemp(prefix="c_", dir=self.root)
        _write(case_dir, "rootlevel.py", WHITELIST_CLEAN)
        cwd = os.getcwd()
        try:
            os.chdir(case_dir)
            found = {e["check"] for e in scan_file("./rootlevel.py")}
        finally:
            os.chdir(cwd)
        self.assertIn("api-unknown-path", found)
        self.assertIn("obs-unknown-api-path", found)

    # ── Labelling ───────────────────────────────────────────────────────────

    def test_labels_do_not_claim_path_validation(self):
        """The control titles must not read as 'API path verified'."""
        for check_id in ("api-unknown-path", "obs-unknown-api-path"):
            title = controls.CONTROLS[check_id]["title"].lower()
            self.assertIn("known gap", title, check_id)
            self.assertIn("not validated", title, check_id)

    def test_legacy_type_strings_still_resolve(self):
        """Renaming the finding type must not orphan existing evidence files."""
        self.assertEqual("api-unknown-path",
                         controls.resolve_check("Layer 2 (Unknown API Path)"))
        self.assertEqual("obs-unknown-api-path",
                         controls.resolve_check("Layer 12 (Unknown API Path - Observability Skipped)"))


class TestThreadSafetyGenericity(unittest.TestCase):
    """The thread-safety check must work on arbitrary global names.

    The previous implementation only recognised three literal names from one
    script; these cases would all have been missed.
    """

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="fixt_")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _checks(self, content, name="app/mod.py"):
        full = _write(tempfile.mkdtemp(prefix="c_", dir=self.root), name, content)
        return {e["check"] for e in scan_file(full)}

    def test_arbitrary_global_name_is_detected(self):
        src = ('import threading\n'
               'SESSION_REGISTRY = {}\n'
               'def add(k):\n'
               '    SESSION_REGISTRY[k] = 1\n')
        self.assertIn("thread-safety", self._checks(src))

    def test_list_append_is_detected(self):
        src = ('import threading\n'
               'PENDING = []\n'
               'def add(x):\n'
               '    PENDING.append(x)\n')
        self.assertIn("thread-safety", self._checks(src))

    def test_lock_guarded_mutation_is_clean(self):
        src = ('import threading\n'
               'PENDING = []\n'
               '_guard = threading.Lock()\n'
               'def add(x):\n'
               '    with _guard:\n'
               '        PENDING.append(x)\n')
        self.assertNotIn("thread-safety", self._checks(src))

    def test_no_concurrency_means_no_finding(self):
        src = ('CACHE = {}\n'
               'def put(k, v):\n'
               '    CACHE[k] = v\n')
        self.assertNotIn("thread-safety", self._checks(src))

    def test_lock_only_present_but_unused_is_still_flagged(self):
        """The old check passed any file merely containing the text 'Lock()'."""
        src = ('import threading\n'
               'CACHE = {}\n'
               '_unused = threading.Lock()\n'
               'def put(k, v):\n'
               '    with open("f") as fh:\n'
               '        CACHE[k] = v\n')
        self.assertIn("thread-safety", self._checks(src))


class TestGravityRuleIsScoped(unittest.TestCase):
    """The Gravity rule is app-specific by design and must stay that way."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="fixt_")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _checks(self, relpath):
        src = 'def push_workspace(x):\n    return x\n'
        full = _write(tempfile.mkdtemp(prefix="c_", dir=self.root), relpath, src)
        return {e["check"] for e in scan_file(full)}

    def test_fires_inside_gravity(self):
        self.assertIn("gravity-error-reporting", self._checks("gravity/actions.py"))

    def test_silent_outside_gravity(self):
        self.assertNotIn("gravity-error-reporting", self._checks("commerce/actions.py"))

    def test_labelled_as_app_specific(self):
        control = controls.CONTROLS["gravity-error-reporting"]
        self.assertIn("APP-SPECIFIC", control["title"])


class TestSuppressionSyntax(unittest.TestCase):
    """Unified '# compliance-ignore: <check-id>' syntax."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="fixt_")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _checks(self, relpath, content):
        full = _write(tempfile.mkdtemp(prefix="c_", dir=self.root), relpath, content)
        return {e["check"] for e in scan_file(full)}

    def test_inline_suppression(self):
        src = ('import subprocess\n'
               'def go(cmd):\n'
               '    return subprocess.run(cmd, shell=True)\n')
        self.assertIn("command-injection", self._checks("app/r.py", src))
        suppressed = ('# compliance-ignore-file: command-injection\n' + src)
        self.assertNotIn("command-injection", self._checks("app/r.py", suppressed))

    def test_line_level_suppression_applies_to_next_line(self):
        src = ('import threading\n'
               'CACHE = {}\n'
               'def put(k, v):\n'
               '    # compliance-ignore: thread-safety\n'
               '    CACHE[k] = v\n')
        self.assertNotIn("thread-safety", self._checks("app/s.py", src))

    def test_suppressing_one_check_leaves_others(self):
        src = ('# compliance-ignore-file: command-injection\n'
               'import subprocess\n'
               'import os\n'
               'def go(cmd, base, name):\n'
               '    subprocess.run(cmd, shell=True)\n'
               '    return open(os.path.join(base, name))\n')
        found = self._checks("app/t.py", src)
        self.assertNotIn("command-injection", found)
        self.assertIn("path-traversal", found)

    def test_ignore_all(self):
        src = ('# compliance-ignore-file: all\n'
               'import subprocess\n'
               'def go(cmd):\n'
               '    return subprocess.run(cmd, shell=True)\n')
        self.assertEqual(set(), self._checks("app/u.py", src))

    def test_comment_leader_agnostic(self):
        """The directive works behind //, #, /// — the token is what matters."""
        file_level, _ = collect_suppressions("// compliance-ignore-file: obs-flutter-trace\n")
        self.assertIn("obs-flutter-trace", file_level)

    def test_multiple_ids_on_one_directive(self):
        file_level, _ = collect_suppressions("# compliance-ignore-file: a-b, c-d\n")
        self.assertEqual({"a-b", "c-d"}, file_level)

    def test_is_suppressed_line_window(self):
        _, line_level = collect_suppressions("x\n# compliance-ignore: foo\ny\n")
        self.assertTrue(is_suppressed("foo", 3, set(), line_level))   # line below
        self.assertTrue(is_suppressed("foo", 2, set(), line_level))   # same line
        self.assertFalse(is_suppressed("foo", 5, set(), line_level))  # unrelated
        self.assertFalse(is_suppressed("bar", 3, set(), line_level))  # other check


class TestSeverityAndOverrides(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="fixt_")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _scan(self, relpath, content, overrides=None):
        full = _write(tempfile.mkdtemp(prefix="c_", dir=self.root), relpath, content)
        return scan_file(full, severity_overrides=overrides)

    def test_injection_class_defaults_to_error(self):
        for check_id in ("command-injection", "sql-injection", "path-traversal",
                         "py-hardcoded-secret", "auth-hardcoded-token"):
            self.assertEqual("error", controls.CONTROLS[check_id]["severity"], check_id)

    def test_i18n_heuristic_defaults_to_warning(self):
        self.assertEqual("warning", controls.CONTROLS["nextjs-i18n"]["severity"])

    def test_severity_override_downgrades(self):
        src = 'import subprocess\ndef g(c):\n    return subprocess.run(c, shell=True)\n'
        found = self._scan("app/v.py", src, {"command-injection": "warning"})
        entry = next(e for e in found if e["check"] == "command-injection")
        self.assertEqual("warning", entry["severity"])

    def test_severity_off_removes_finding(self):
        src = 'import subprocess\ndef g(c):\n    return subprocess.run(c, shell=True)\n'
        found = self._scan("app/w.py", src, {"command-injection": "off"})
        self.assertNotIn("command-injection", {e["check"] for e in found})

    def test_findings_carry_both_framework_ids(self):
        src = 'import subprocess\ndef g(c):\n    return subprocess.run(c, shell=True)\n'
        entry = next(e for e in self._scan("app/x.py", src) if e["check"] == "command-injection")
        self.assertEqual("CC7.1", entry["soc2"])
        self.assertEqual("A.8.28", entry["iso27001"])


class TestControlsTable(unittest.TestCase):
    def test_every_type_string_resolves_to_a_known_control(self):
        for type_str, check_id in controls.TYPE_TO_CHECK.items():
            self.assertIn(check_id, controls.CONTROLS,
                          f"'{type_str}' maps to unregistered check '{check_id}'")

    def test_every_control_has_both_frameworks_and_valid_severity(self):
        for check_id, entry in controls.CONTROLS.items():
            self.assertTrue(entry.get("soc2"), check_id)
            self.assertTrue(entry.get("iso27001"), check_id)
            self.assertTrue(entry["iso27001"].startswith("A."),
                            f"{check_id}: '{entry['iso27001']}' is not an Annex A control id")
            self.assertIn(entry["severity"], controls.VALID_SEVERITIES, check_id)
            self.assertTrue(entry.get("title"), check_id)

    def test_no_finding_falls_through_to_unmapped(self):
        """Every check with a fixture resolves to a real control, never 'unmapped'."""
        for check_id in CASES:
            self.assertIn(check_id, controls.CONTROLS)
            self.assertNotEqual("unmapped", check_id)

    def test_annotate_is_idempotent(self):
        e = {"line": 1, "type": "Layer 18 (Process execution security hardening)", "message": "m"}
        controls.annotate(e)
        first = dict(e)
        controls.annotate(e)
        self.assertEqual(first, e)

    def test_unknown_type_falls_back_to_unmapped(self):
        e = {"line": 1, "type": "Layer 99 (Does Not Exist)", "message": "m"}
        controls.annotate(e)
        self.assertEqual("unmapped", e["check"])


class TestWalkExclusions(unittest.TestCase):
    """The walk must not prune the very directories a check is looking for."""

    def test_github_and_rokct_dirs_are_not_pruned(self):
        """structural-special-dirs flags .py under .github/ and .rokct/.

        If either is in the default prune list the walk never reaches those
        files and the check cannot fire — a silent hole, not a visible failure.
        """
        from compliance.config import DEFAULT_EXCLUDE_DIRS
        for forbidden_dir in (".github", ".rokct"):
            self.assertNotIn(
                forbidden_dir, DEFAULT_EXCLUDE_DIRS,
                f"'{forbidden_dir}' is pruned from the walk, which disables the "
                f"structural-special-dirs check for it",
            )


class TestDatabaseMigrations(unittest.TestCase):
    """check_database_migrations runs outside scan_file, on the changed-file list."""

    def setUp(self):
        self._argv = sys.argv
        sys.argv = ["compliance_scanner.py", "some-target"]  # force explicit-list mode

    def tearDown(self):
        sys.argv = self._argv

    def test_doctype_without_patch_is_flagged(self):
        errs = check_database_migrations(["app/doctype/thing/thing.json"])
        self.assertTrue(any(e["type"] == "Layer 3 (Database Integrity)" for e in errs))

    def test_doctype_with_patch_is_clean(self):
        errs = check_database_migrations([
            "app/doctype/thing/thing.json",
            "app/patches/v1_add_thing.py",
        ])
        self.assertEqual([], errs)


if __name__ == "__main__":
    unittest.main(verbosity=2)

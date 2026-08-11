#!/usr/bin/env python3
# Copyright 2026 RokctAI
# Compliance Scanner: Programmatically enforces production-grade quality across all layers.

import sys
import os
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from compliance import scan_file, check_database_migrations
from compliance import controls as controls_table
from compliance import config as compliance_config
from update_docs import scan_and_sync, detect_project_type


def _is_scannable(filename):
    lowered = filename.lower()
    if filename.endswith((".g.dart", ".gr.dart", ".freezed.dart")):
        return False
    return (
        filename.endswith((".py", ".ts", ".tsx", ".dart", ".conf", ".yml", ".yaml"))
        or "nginx" in lowered
        or "dockerfile" in lowered
    )


def app_shell_marker(git_root):
    """Return the marker identifying a composed app shell, or None for SDK repos.

    composer.json at the git root is the established shell-app idiom (see
    universal-linter.yml / universal-flutter-analyze.yml); .rokct/config/app_type
    is the secondary marker written by the platform tooling.
    """
    if os.path.isfile(os.path.join(git_root, "composer.json")):
        return "composer.json"
    if os.path.isfile(os.path.join(git_root, ".rokct", "config", "app_type")):
        return ".rokct/config/app_type"
    return None


def main():
    print("=" * 80)
    print("ROKCT PLATFORM ECOSYSTEM - ARCHITECTURAL COMPLIANCE GATEWAY")
    print("=" * 80)

    # ── SDK-only guard ──────────────────────────────────────────────────────
    # The compliance scanner (and its Layer 20 doc generation / evidence
    # writing) runs on SDK repos only. Composed app shells assemble already-
    # scanned SDKs, so scanning them duplicates findings and docs. This guard
    # covers every invocation path (CI, sdk_validator.py, fleet_compliance.py,
    # manual runs) because they all go through this entrypoint.
    guard_args = [a for a in sys.argv[1:] if os.path.exists(a)]
    guard_base = os.path.abspath(guard_args[0]) if guard_args else os.getcwd()
    git_root = find_git_root(guard_base)
    if os.environ.get("COMPLIANCE_FORCE") != "1":
        marker = app_shell_marker(git_root)
        if marker:
            print(f"app shell detected ({marker}) — compliance scanner runs on SDK repos only; skipping (set COMPLIANCE_FORCE=1 to override)")
            sys.exit(0)

    files_to_scan = []
    changed_files_list = []
    target_dirs = []

    # Load per-repo config first — exclusions come from it, not from this source file.
    arg_dirs = [a for a in sys.argv[1:] if os.path.isdir(a)] or ["."]
    cfg, cfg_path = compliance_config.load_config(arg_dirs)
    prune_dirs = compliance_config.excluded_dirs(cfg)
    if cfg_path:
        print(f"Config: {os.path.relpath(cfg_path)}")

    def collect(walk_root, also_changed):
        for root, dirs, files in os.walk(walk_root):
            dirs[:] = [d for d in dirs if d not in prune_dirs]
            for file in files:
                fp = os.path.join(root, file)
                if compliance_config.is_path_excluded(fp, cfg, walk_root):
                    continue
                if _is_scannable(file):
                    files_to_scan.append(fp)
                    if also_changed:
                        changed_files_list.append(fp)
                if not also_changed and file.endswith(".json") and "doctype" in fp:
                    changed_files_list.append(fp)

    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if os.path.isfile(arg):
                files_to_scan.append(arg)
                changed_files_list.append(arg)
                target_dirs.append(os.path.dirname(os.path.abspath(arg)))
            elif os.path.isdir(arg):
                target_dirs.append(arg)
                collect(arg, also_changed=True)
    else:
        print("Scanning all python/config/nextjs/flutter files in current workspace for full compliance...")
        target_dirs.append(".")
        collect(".", also_changed=False)

    target_dirs = list(set(os.path.abspath(d) for d in target_dirs))

    total_violations = 0
    violations_list = []

    def record(entry):
        """Annotate a finding with its control IDs + severity and file it."""
        controls_table.annotate(entry, cfg.get("severity"))
        if entry["severity"] == "off":
            return None
        violations_list.append(entry)
        return entry

    # Validate project type compliance for target directories
    for target_dir in target_dirs:
        project_type = detect_project_type(target_dir)
        if project_type == "unknown":
            record({
                "file": target_dir,
                "line": 1,
                "type": "Project Type Detection",
                "message": "Unknown project type. Compliance scanning requires a recognized stack (Frappe/Python, Next.js/TypeScript, Flutter/Dart, or Data/Specifications)."
            })
    total_violations = len(violations_list)

    if not files_to_scan and not changed_files_list:
        if total_violations > 0:
            print(f"\nARCHITECTURAL COMPLIANCE FAILED: Unknown project type violation found.")
            log_compliance_evidence(target_dirs, "FAIL", f"Architectural compliance scan failed with unknown project type violation.", violations=violations_list)
            sys.exit(1)
        print("SUCCESS: No source files resolved for scan. Exiting.")
        sys.exit(0)

    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    n_files = len(files_to_scan)
    print(f"Auditing {n_files} source files...")

    # ── Scan loop — compact progress, no per-violation spam ─────────────────
    from collections import defaultdict
    by_check = defaultdict(list)  # check-id -> list of violation dicts

    for i, filepath in enumerate(files_to_scan):
        errors = scan_file(filepath, severity_overrides=cfg.get("severity"))
        for err in errors:
            v = record({
                "file": filepath,
                "line": err["line"],
                "type": err["type"],
                "message": err["message"],
                "check": err.get("check"),
            })
            if v:
                by_check[v["check"]].append(v)
        total_violations = len(violations_list)
        # Progress: print a dot every 50 files so the terminal isn't silent
        if not verbose and (i + 1) % 50 == 0:
            print(f"  ... {i + 1}/{n_files} files checked ({total_violations} findings so far)", flush=True)

    for err in check_database_migrations(changed_files_list) or []:
        v = record({
            "file": "Git Schema Diff",
            "line": err["line"],
            "type": err["type"],
            "message": err["message"],
        })
        if v:
            by_check[v["check"]].append(v)

    errors_list = [v for v in violations_list if v["severity"] == "error"]
    warnings_list = [v for v in violations_list if v["severity"] == "warning"]
    total_violations = len(violations_list)
    # fail_on = "error" (default) means warnings report but do not fail the gate.
    blocking = violations_list if cfg.get("fail_on") == "warning" else errors_list
    total_blocking = len(blocking)

    # ── Output ───────────────────────────────────────────────────────────────
    if verbose:
        # Old behaviour: print every finding, now with its control IDs
        for check_id, vs in sorted(by_check.items()):
            for v in vs:
                print(f"\nCOMPLIANCE {v['severity'].upper()} in: {v['file']}")
                print(f"  [Line {v['line']}] [{v['check']}] [{v['type']}]")
                print(f"  SOC 2: {v['soc2']} | ISO 27001: {v['iso27001']}")
                print(f"  -> {v['message']}")
    else:
        # Compact grouped summary, keyed by check-id with both framework IDs
        if by_check:
            print(f"\n{'Check':<30} {'Sev':<8} {'SOC 2':<8} {'ISO 27001':<10} {'Count':>5}")
            print("-" * 66)
            for check_id, vs in sorted(by_check.items(), key=lambda x: (-len(x[1]), x[0])):
                v = vs[0]
                print(f"{check_id:<30} {v['severity']:<8} {v['soc2']:<8} {v['iso27001']:<10} {len(vs):>5}")
            print("-" * 66)
            print(f"{'TOTAL':<30} {'':<8} {'':<8} {'':<10} {total_violations:>5}")
            print(f"  ({len(errors_list)} error / {len(warnings_list)} warning; "
                  f"fail_on={cfg.get('fail_on')})")
            # Show top 3 examples per check
            print("\nTop examples per check (see evidence JSON for full list):")
            for check_id, vs in sorted(by_check.items(), key=lambda x: (-len(x[1]), x[0])):
                v0 = vs[0]
                print(f"\n  [{check_id}] {v0['severity']} — SOC 2 {v0['soc2']} / ISO 27001 {v0['iso27001']}")
                print(f"    {controls_table.CONTROLS.get(check_id, {}).get('title', v0['type'])}")
                for v in vs[:3]:
                    try:
                        fname = os.path.relpath(v['file']).replace('\\', '/')
                    except ValueError:
                        fname = v['file']
                    print(f"    L{v['line']:>4}  {fname}")
                    print(f"           {v['message'][:100]}{'...' if len(v['message']) > 100 else ''}")
                if len(vs) > 3:
                    print(f"    ... and {len(vs) - 3} more (see evidence JSON)")

    if total_blocking == 0:
        # One-time notice if AI doc generation is unavailable — not repeated per function
        if not (os.environ.get("GROQ_API_KEY") or os.environ.get("GROQ_API")):
            print("[update_docs] GROQ_API_KEY not set — AI doc generation skipped; using cached docs only.", file=sys.stderr)
        
        for target_dir in target_dirs:
            drifted = scan_and_sync(target_dir, check_only=False)
            if drifted:
                print(f"\nDOCUMENTATION AUTO-HEALED: {len(drifted)} file(s) updated in {target_dir}")
                for doc_path, _, _, src in drifted[:5]:
                    print(f"  [Layer 20 (Documentation Sync)] -> {os.path.basename(doc_path)} <- {src}")
                if len(drifted) > 5:
                    print(f"  ... and {len(drifted) - 5} more doc(s) synced.")
    else:
        print("\nSkipping Documentation Sync (fix violations first).")

    print("\n" + "=" * 80)
    if total_blocking > 0:
        print(f"ARCHITECTURAL COMPLIANCE FAILED: {len(errors_list)} error(s), {len(warnings_list)} warning(s).")
        print("All changes must adhere to ROKCT production-grade standards before merging.")
        print("Tip: run with --verbose / -v for full per-file output.")
        print("Suppress a specific finding with: '# compliance-ignore: <check-id>'")
        print("=" * 80)
        log_compliance_evidence(
            target_dirs, "FAIL",
            f"Architectural compliance scan failed with {len(errors_list)} error(s) and "
            f"{len(warnings_list)} warning(s) across source code checks.",
            violations=violations_list)
        sys.exit(1)
    else:
        if warnings_list:
            print(f"ARCHITECTURAL COMPLIANCE SUCCESS (with {len(warnings_list)} non-blocking warning(s)).")
        else:
            print("ARCHITECTURAL COMPLIANCE SUCCESS: All systems pass production standards.")
        print("=" * 80)
        log_compliance_evidence(
            target_dirs, "PASS",
            f"Architectural compliance scan completed successfully with 0 blocking violations "
            f"({len(warnings_list)} warning(s) recorded). Codebase standards verified.",
            violations=violations_list)
        sys.exit(0)

def is_ci_environment():
    return os.environ.get("CI") == "true" or os.environ.get("GITHUB_ACTIONS") == "true"

def sanitize_text(text):
    if not isinstance(text, str):
        return text
    text = re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '[REDACTED_IP]', text)
    text = re.sub(r'[A-Za-z]:\\[Uu]sers\\[^\\]+', r'[WORKSPACE_ROOT]', text)
    text = re.sub(r'/home/[^/]+', r'[WORKSPACE_ROOT]', text)
    text = re.sub(r'(?i)(password|passwd|secret|token|key|auth|credential|api_key|pkey)\s*[:=]\s*[^\s,;]+', r'\1=[REDACTED]', text)
    return text

def find_git_root(start_path):
    curr = Path(start_path).resolve()
    while curr != curr.parent:
        if (curr / ".git").is_dir():
            return str(curr)
        curr = curr.parent
    return str(Path(start_path).resolve())

def resolve_evidence_repo(target_dirs):
    override = os.environ.get("EVIDENCE_REPO_DIR")
    if override:
        # Callers (e.g. sdk_validator.py) may pass an SDK subfolder rather than the
        # actual monorepo root — walk up to the real .git the same way update_docs.py does.
        return find_git_root(os.path.abspath(override))
    
    # If we have target directories, try to find the git root based on the first one
    if target_dirs:
        # Use the target_dir to find the nearest .git root
        return find_git_root(target_dirs[0])
    
    # Fallback to current working directory's git root
    return find_git_root(os.getcwd())

def _evidence_violation(v):
    """Serialize one finding with its real per-check control IDs."""
    check_id = v.get("check") or controls_table.resolve_check(v.get("type", ""))
    control = controls_table.CONTROLS.get(check_id, controls_table.CONTROLS["unmapped"])
    return {
        "file": sanitize_text(v["file"]),
        "line": v["line"],
        "check_id": check_id,
        "title": control["title"],
        "layer": control["layer"],
        "severity": v.get("severity", control["severity"]),
        "controls": {
            "soc2": v.get("soc2", control["soc2"]),
            "iso27001": v.get("iso27001", control["iso27001"]),
        },
        "what": sanitize_text(v["type"]),
        "why": sanitize_text(v["message"]),
    }


def write_evidence_file(repo_dir, control_id, status, detail, violations=[], target_dir=None):
    # control_id may be a nested id ("checks/<id>__SOC2-..__ISO-..") — keep it
    # POSIX-style in the payload regardless of host path separators.
    control_id = control_id.replace("\\", "/")
    evidence_dir = os.path.join(repo_dir, ".rokct", "evidence", *control_id.split("/"))
    os.makedirs(evidence_dir, exist_ok=True)
    from datetime import timezone
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{timestamp}_{status}.json"
    filepath = os.path.join(evidence_dir, filename)

    serialized = [_evidence_violation(v) for v in violations]

    # Per-control rollup so an auditor can answer "what fired under CC6.1 /
    # A.5.17?" without re-deriving it from the finding list.
    rollup = {}
    for item in serialized:
        key = item["check_id"]
        entry = rollup.setdefault(key, {
            "check_id": key,
            "title": item["title"],
            "layer": item["layer"],
            "severity": item["severity"],
            "controls": item["controls"],
            "count": 0,
        })
        entry["count"] += 1

    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        # The scan run itself is the CC7.1 ongoing-monitoring evidence record;
        # individual findings carry their own control IDs below.
        "control_id": control_id,
        "status": status,
        "system": "compliance-scanner",
        "frameworks": ["SOC 2", "ISO/IEC 27001:2022"],
        "target_dir": sanitize_text(target_dir) if target_dir else "unknown",
        "detail": sanitize_text(detail),
        "summary": {
            "total": len(serialized),
            "error": sum(1 for x in serialized if x["severity"] == "error"),
            "warning": sum(1 for x in serialized if x["severity"] == "warning"),
        },
        "controls_triggered": sorted(rollup.values(), key=lambda x: -x["count"]),
        "violations": serialized,
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return filepath

def commit_and_push_evidence(repo_dir, evidence_filepath, control_id, status, detail):
    token = os.environ.get("MONOREPO_PAT") or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print("MONOREPO_PAT / GITHUB_TOKEN / GH_TOKEN not set; skipping evidence push.", file=sys.stderr)
        return
    try:
        remote_url = subprocess.run(["git", "-C", repo_dir, "remote", "get-url", "origin"], capture_output=True, text=True, check=True).stdout.strip()
        if remote_url.startswith("https://"):
            authed_url = remote_url.replace("https://", f"https://x-access-token:{token}@")
            subprocess.run(["git", "-C", repo_dir, "remote", "set-url", "origin", authed_url], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["git", "-C", repo_dir, "config", "user.name", "rokctbot[bot]"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["git", "-C", repo_dir, "config", "user.email", "rokctbot[bot]@users.noreply.github.com"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["git", "-C", repo_dir, "add", evidence_filepath], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        commit_msg = f"compliance(evidence): log SOC 2 evidence for {control_id} ({status}) [skip ci]"
        subprocess.run(["git", "-C", repo_dir, "commit", "-m", commit_msg], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        ref = os.environ.get("GITHUB_REF", "refs/heads/main")
        branch = ref.replace("refs/heads/", "")
        subprocess.run(["git", "-C", repo_dir, "push", "origin", f"HEAD:{branch}"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print(f"Evidence committed and pushed to {branch}.")
    except subprocess.CalledProcessError as e:
        print(f"Evidence push failed: {e}", file=sys.stderr)
    except Exception as e:
        print(f"Unexpected error in evidence push: {e}", file=sys.stderr)

def log_compliance_evidence(target_dirs, status, detail, violations=[]):
    repo_dir = resolve_evidence_repo(target_dirs)
    if not repo_dir:
        print("No repo with .rokct directory found for evidence logging.")
        return
    
    # Use the primary target directory to identify the scan target
    scanned_path = target_dirs[0] if target_dirs else "unknown"
    scanned_path_rel = scanned_path

    # "target_dir" is reported relative to the parent of the git repo (i.e. the folder that holds
    # every repo as a sibling), not the repo root itself — so it reads naturally even when the
    # scanned path is nested a level deeper than the repo (e.g. agent/agent/dart inside the agent
    # repo shows as "agent/agent/dart", not just "agent/dart"). Derived purely from the git repo
    # root found above — no hardcoding, works on any machine/workspace layout.
    display_base = os.path.dirname(repo_dir)

    # Calculate path relative to the display root for the evidence log
    if scanned_path != "unknown":
        try:
            scanned_path_rel = os.path.relpath(scanned_path, display_base).replace(os.sep, "/")
            target_dir_for_log = f"[WORKSPACE_ROOT]/{scanned_path_rel}"
        except Exception:
            target_dir_for_log = sanitize_text(scanned_path)
    else:
        target_dir_for_log = "unknown"
    
    run_control_id = controls_table.SCAN_RUN_CONTROL_ID
    try:
        # 1. Run-level record: the scan itself is the SOC 2 CC7.1 ongoing-monitoring
        #    evidence trail. This is the file the CI auto-push commits.
        evidence_path = write_evidence_file(
            repo_dir, run_control_id, status, detail,
            violations=violations, target_dir=target_dir_for_log)
        print(f"Compliance evidence written to: {evidence_path} (Target: {scanned_path_rel})")

        # 2. Per-control records: one evidence file per check-id that actually
        #    fired, filed under its own SOC 2 / ISO 27001 control directory so
        #    each control has its own auditable trail.
        by_check = {}
        for v in violations:
            check_id = v.get("check") or controls_table.resolve_check(v.get("type", ""))
            by_check.setdefault(check_id, []).append(v)

        for check_id, items in sorted(by_check.items()):
            control = controls_table.CONTROLS.get(check_id, controls_table.CONTROLS["unmapped"])
            control_dir = f"{check_id}__SOC2-{control['soc2']}__ISO-{control['iso27001']}"
            sub_status = "FAIL" if any(i.get("severity") == "error" for i in items) else "WARN"
            write_evidence_file(
                repo_dir, f"checks/{control_dir}", sub_status,
                f"{control['title']} — {len(items)} finding(s) "
                f"[SOC 2 {control['soc2']} / ISO 27001 {control['iso27001']}].",
                violations=items, target_dir=target_dir_for_log)
        if by_check:
            print(f"Per-control evidence written for {len(by_check)} control(s) under .rokct/evidence/checks/")

        if is_ci_environment():
            commit_and_push_evidence(repo_dir, evidence_path, run_control_id, status, detail)
    except Exception as e:
        print(f"Error logging compliance evidence: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()

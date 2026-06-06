#!/usr/bin/env python3
# Copyright 2026 RokctAI
# Compliance Scanner: Programmatically enforces production-grade quality across all layers.

import sys
import os
import json
import re
import subprocess
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from compliance import scan_file, check_database_migrations
from update_docs import scan_and_sync

def main():
    print("=" * 80)
    print("ROKCT PLATFORM ECOSYSTEM - ARCHITECTURAL COMPLIANCE GATEWAY")
    print("=" * 80)

    files_to_scan = []
    changed_files_list = []
    target_dirs = []

    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if os.path.isfile(arg):
                files_to_scan.append(arg)
                changed_files_list.append(arg)
                target_dirs.append(os.path.dirname(os.path.abspath(arg)))
            elif os.path.isdir(arg):
                target_dirs.append(arg)
                for root, dirs, files in os.walk(arg):
                    dirs[:] = [d for d in dirs if d not in [".git", "node_modules", ".next", "dist", ".dart_tool", "build", "ios", "android", "env", "__pycache__", ".rokct", "Compliance"]]
                    for file in files:
                        fp = os.path.join(root, file)
                        if (file.endswith(".py") or file.endswith(".ts") or file.endswith(".tsx") or file.endswith(".dart") or "nginx" in file.lower() or file.endswith(".conf") or file.endswith(".yml") or file.endswith(".yaml") or "dockerfile" in file.lower()) and not file.endswith(".g.dart") and not file.endswith(".gr.dart") and not file.endswith(".freezed.dart"):
                            files_to_scan.append(fp)
                            changed_files_list.append(fp)
    else:
        print("Scanning all python/config/nextjs/flutter files in current workspace for full compliance...")
        target_dirs.append(".")
        for root, dirs, files in os.walk("."):
            dirs[:] = [d for d in dirs if d not in [".git", "env", "node_modules", "__pycache__", ".shared-workflows", ".next", "dist", ".dart_tool", "build", "ios", "android", ".rokct", "Compliance"]]
            for file in files:
                fp = os.path.join(root, file)
                if (file.endswith(".py") or file.endswith(".ts") or file.endswith(".tsx") or file.endswith(".dart") or "nginx" in file.lower() or file.endswith(".conf") or file.endswith(".yml") or file.endswith(".yaml") or "dockerfile" in file.lower()) and not file.endswith(".g.dart") and not file.endswith(".gr.dart") and not file.endswith(".freezed.dart"):
                    files_to_scan.append(fp)
                if file.endswith(".json") and "doctype" in fp:
                    changed_files_list.append(fp)

    target_dirs = list(set(os.path.abspath(d) for d in target_dirs))

    if not files_to_scan and not changed_files_list:
        print("SUCCESS: No source files resolved for scan. Exiting.")
        sys.exit(0)

    print(f"Auditing {len(files_to_scan)} source files...")
    total_violations = 0

    for filepath in files_to_scan:
        errors = scan_file(filepath)
        if errors:
            print(f"\nCOMPLIANCE VIOLATION in: {filepath}")
            for err in errors:
                print(f"  [Line {err['line']}] [{err['type']}] -> {err['message']}")
                total_violations += 1

    migration_errors = check_database_migrations(changed_files_list)
    if migration_errors:
        print("\nCOMPLIANCE VIOLATION in: Git Schema Diff")
        for err in migration_errors:
            print(f"  [Line {err['line']}] [{err['type']}] -> {err['message']}")
            total_violations += 1

    if total_violations == 0:
        for target_dir in target_dirs:
            drifted = scan_and_sync(target_dir, check_only=False)
            if drifted:
                print(f"\nDOCUMENTATION AUTO-HEALED: Documentation drift detected and fixed in {target_dir}")
                for doc_path, _, _, src in drifted:
                    print(f"  [Layer 20 (Documentation Sync)] -> API Reference doc updated: {os.path.basename(doc_path)} (source: {src})")
                print("  Note: These changes will be automatically committed to the repository by CI.")
    else:
        print("\nSkipping Documentation Sync Compliance Checks because prior violations exist.")

    print("\n" + "=" * 80)
    if total_violations > 0:
        print(f"ARCHITECTURAL COMPLIANCE FAILED: {total_violations} violations found.")
        print("All changes must adhere to ROKCT production-grade standards before merging.")
        print("=" * 80)
        log_compliance_evidence(target_dirs, "FAIL", f"Architectural compliance scan failed with {total_violations} violations across source code checks.")
        sys.exit(1)
    else:
        print("ARCHITECTURAL COMPLIANCE SUCCESS: All systems pass production standards.")
        print("=" * 80)
        log_compliance_evidence(target_dirs, "PASS", "Architectural compliance scan completed successfully with 0 violations. Codebase standards verified.")
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

def resolve_evidence_repo(target_dirs):
    override = os.environ.get("EVIDENCE_REPO_DIR")
    if override and os.path.isdir(os.path.join(override, ".rokct")):
        return os.path.abspath(override)
    for d in target_dirs:
        d = os.path.abspath(d)
        if os.path.isdir(os.path.join(d, ".rokct")):
            return d
    return os.getcwd()

def write_evidence_file(repo_dir, control_id, status, detail):
    evidence_dir = os.path.join(repo_dir, ".rokct", "evidence", control_id)
    os.makedirs(evidence_dir, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    filename = f"{timestamp}_{status}.json"
    filepath = os.path.join(evidence_dir, filename)
    payload = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "control_id": control_id,
        "status": status,
        "system": "compliance-scanner",
        "detail": sanitize_text(detail)
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return filepath

def gh_push_evidence_pr(repo_dir, evidence_filepath, control_id, status, detail):
    branch = f"compliance/evidence/{control_id.lower()}"
    title = f"compliance(evidence): log SOC 2 evidence for {control_id} ({status}) [skip ci]"
    try:
        subprocess.run(["git", "-C", repo_dir, "checkout", "-b", branch], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["git", "-C", repo_dir, "add", evidence_filepath], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["git", "-C", repo_dir, "commit", "-m", title], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["git", "-C", repo_dir, "push", "-u", "origin", branch], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        pr_body = f"Automated compliance evidence for `{control_id}`.\n\n- **Status:** {status}\n- **Detail:** {detail}"
        res = subprocess.run(["gh", "-C", repo_dir, "pr", "create", "--title", title, "--body", pr_body, "--base", "main", "--head", branch], capture_output=True, text=True)
        if res.returncode != 0 and "already exists" not in (res.stderr or "").lower():
            print(f"gh pr create warning: {res.stderr.strip()}", file=sys.stderr)
        elif res.returncode == 0:
            print(f"Opened evidence PR: {res.stdout.strip()}")
    except subprocess.CalledProcessError as e:
        print(f"Evidence PR flow failed: {e}", file=sys.stderr)
    except Exception as e:
        print(f"Unexpected error in evidence PR flow: {e}", file=sys.stderr)

def log_compliance_evidence(target_dirs, status, detail):
    repo_dir = resolve_evidence_repo(target_dirs)
    if not repo_dir:
        print("No repo with .rokct directory found for evidence logging.")
        return
    try:
        evidence_path = write_evidence_file(repo_dir, "SOC2-CC7.1-COMPLIANCE", status, detail)
        print(f"Compliance evidence written to: {evidence_path}")
        if is_ci_environment():
            gh_push_evidence_pr(repo_dir, evidence_path, "SOC2-CC7.1-COMPLIANCE", status, detail)
    except Exception as e:
        print(f"Error logging compliance evidence: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()

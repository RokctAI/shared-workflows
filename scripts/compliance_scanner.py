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
from update_docs import scan_and_sync, detect_project_type

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
                    dirs[:] = [d for d in dirs if d not in [".git", "node_modules", ".next", "dist", ".dart_tool", "build", "ios", "android", "env", "__pycache__", "Compliance"]]
                    for file in files:
                        fp = os.path.join(root, file)
                        if (file.endswith(".py") or file.endswith(".ts") or file.endswith(".tsx") or file.endswith(".dart") or "nginx" in file.lower() or file.endswith(".conf") or file.endswith(".yml") or file.endswith(".yaml") or "dockerfile" in file.lower()) and not file.endswith(".g.dart") and not file.endswith(".gr.dart") and not file.endswith(".freezed.dart"):
                            files_to_scan.append(fp)
                            changed_files_list.append(fp)
    else:
        print("Scanning all python/config/nextjs/flutter files in current workspace for full compliance...")
        target_dirs.append(".")
        for root, dirs, files in os.walk("."):
            dirs[:] = [d for d in dirs if d not in [".git", "env", "node_modules", "__pycache__", ".shared-workflows", ".next", "dist", ".dart_tool", "build", "ios", "android", "Compliance"]]
            for file in files:
                fp = os.path.join(root, file)
                if (file.endswith(".py") or file.endswith(".ts") or file.endswith(".tsx") or file.endswith(".dart") or "nginx" in file.lower() or file.endswith(".conf") or file.endswith(".yml") or file.endswith(".yaml") or "dockerfile" in file.lower()) and not file.endswith(".g.dart") and not file.endswith(".gr.dart") and not file.endswith(".freezed.dart"):
                    files_to_scan.append(fp)
                if file.endswith(".json") and "doctype" in fp:
                    changed_files_list.append(fp)

    target_dirs = list(set(os.path.abspath(d) for d in target_dirs))

    total_violations = 0
    violations_list = []

    # Validate project type compliance for target directories
    for target_dir in target_dirs:
        project_type = detect_project_type(target_dir)
        if project_type == "unknown":
            print(f"\nCOMPLIANCE VIOLATION in: {target_dir}")
            print(f"  [Project Type Detection] -> Unknown project type. Compliance scanning requires a recognized stack (Frappe/Python, Next.js/TypeScript, or Flutter/Dart).")
            total_violations += 1
            violations_list.append({
                "file": target_dir,
                "line": 1,
                "type": "Project Type Detection",
                "message": "Unknown project type. Compliance scanning requires a recognized stack (Frappe/Python, Next.js/TypeScript, or Flutter/Dart)."
            })

    if not files_to_scan and not changed_files_list:
        if total_violations > 0:
            print(f"\nARCHITECTURAL COMPLIANCE FAILED: Unknown project type violation found.")
            log_compliance_evidence(target_dirs, "FAIL", f"Architectural compliance scan failed with unknown project type violation.", violations=violations_list)
            sys.exit(1)
        print("SUCCESS: No source files resolved for scan. Exiting.")
        sys.exit(0)

    print(f"Auditing {len(files_to_scan)} source files...")


    for filepath in files_to_scan:
        errors = scan_file(filepath)
        if errors:
            print(f"\nCOMPLIANCE VIOLATION in: {filepath}")
            for err in errors:
                print(f"  [Line {err['line']}] [{err['type']}] -> {err['message']}")
                total_violations += 1
                violations_list.append({
                    "file": filepath,
                    "line": err["line"],
                    "type": err["type"],
                    "message": err["message"]
                })

    migration_errors = check_database_migrations(changed_files_list)
    if migration_errors:
        print("\nCOMPLIANCE VIOLATION in: Git Schema Diff")
        for err in migration_errors:
            print(f"  [Line {err['line']}] [{err['type']}] -> {err['message']}")
            total_violations += 1
            violations_list.append({
                "file": "Git Schema Diff",
                "line": err["line"],
                "type": err["type"],
                "message": err["message"]
            })

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
        log_compliance_evidence(target_dirs, "FAIL", f"Architectural compliance scan failed with {total_violations} violations across source code checks.", violations=violations_list)
        sys.exit(1)
    else:
        print("ARCHITECTURAL COMPLIANCE SUCCESS: All systems pass production standards.")
        print("=" * 80)
        log_compliance_evidence(target_dirs, "PASS", "Architectural compliance scan completed successfully with 0 violations. Codebase standards verified.", violations=[])
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
    if override:
        return os.path.abspath(override)
    if target_dirs:
        return os.path.abspath(target_dirs[0])
    return os.getcwd()

def write_evidence_file(repo_dir, control_id, status, detail, violations=[]):
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
        "detail": sanitize_text(detail),
        "violations": [
            {
                "file": sanitize_text(v["file"]),
                "line": v["line"],
                "what": sanitize_text(v["type"]),
                "why": sanitize_text(v["message"])
            } for v in violations
        ]
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
    try:
        evidence_path = write_evidence_file(repo_dir, "SOC2-CC7.1-COMPLIANCE", status, detail, violations=violations)
        print(f"Compliance evidence written to: {evidence_path}")
        if is_ci_environment():
            commit_and_push_evidence(repo_dir, evidence_path, "SOC2-CC7.1-COMPLIANCE", status, detail)
    except Exception as e:
        print(f"Error logging compliance evidence: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()

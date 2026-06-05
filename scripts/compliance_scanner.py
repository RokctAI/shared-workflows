#!/usr/bin/env python3
# Copyright 2026 RokctAI
# Compliance Scanner: Programmatically enforces production-grade quality across all layers.

import sys
import os
import subprocess

# Append current script folder to path so local 'compliance' package is resolvable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from compliance import scan_file, check_database_migrations
from update_docs import scan_and_sync

def main():
    print("=" * 80)
    print("ROKCT PLATFORM ECOSYSTEM - ARCHITECTURAL COMPLIANCE GATEWAY")
    print("=" * 80)

    # 1. Resolve files to scan: either passed directly or changed in git diff
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
                    # Prune third-party dependency, build, and platform cache directories
                    dirs[:] = [d for d in dirs if d not in [".git", "node_modules", ".next", "dist", ".dart_tool", "build", "ios", "android", "env", "__pycache__", ".rokct", "Compliance"]]
                    for file in files:
                        fp = os.path.join(root, file)
                        if (file.endswith(".py") or file.endswith(".ts") or file.endswith(".tsx") or file.endswith(".dart") or "nginx" in file.lower() or file.endswith(".conf") or file.endswith(".yml") or file.endswith(".yaml") or "dockerfile" in file.lower()) and not file.endswith(".g.dart") and not file.endswith(".gr.dart") and not file.endswith(".freezed.dart"):
                            files_to_scan.append(fp)
                            changed_files_list.append(fp)
    else:
        # Default: scan recursively from current directory to force strict codebase-wide compliance
        print("Scanning all python/config/nextjs/flutter files in current workspace for full compliance...")
        target_dirs.append(".")
        for root, dirs, files in os.walk("."):
            # Prune third-party and platform build cache folders
            dirs[:] = [d for d in dirs if d not in [".git", "env", "node_modules", "__pycache__", ".shared-workflows", ".next", "dist", ".dart_tool", "build", "ios", "android", ".rokct", "Compliance"]]
            for file in files:
                fp = os.path.join(root, file)
                if (file.endswith(".py") or file.endswith(".ts") or file.endswith(".tsx") or file.endswith(".dart") or "nginx" in file.lower() or file.endswith(".conf") or file.endswith(".yml") or file.endswith(".yaml") or "dockerfile" in file.lower()) and not file.endswith(".g.dart") and not file.endswith(".gr.dart") and not file.endswith(".freezed.dart"):
                    files_to_scan.append(fp)
                if file.endswith(".json") and "doctype" in fp:
                    changed_files_list.append(fp)

    # Deduplicate target directories
    target_dirs = list(set(os.path.abspath(d) for d in target_dirs))

    if not files_to_scan and not changed_files_list:
        print("SUCCESS: No source files resolved for scan. Exiting.")
        sys.exit(0)

    print(f"Auditing {len(files_to_scan)} source files...")
    total_violations = 0

    # 2. Run AST and File Scanning
    for filepath in files_to_scan:
        errors = scan_file(filepath)
        if errors:
            print(f"\nCOMPLIANCE VIOLATION in: {filepath}")
            for err in errors:
                print(f"  [Line {err['line']}] [{err['type']}] -> {err['message']}")
                total_violations += 1

    # 3. Run Layer 3 Schema Compliance Checks
    migration_errors = check_database_migrations(changed_files_list)
    if migration_errors:
        print("\nCOMPLIANCE VIOLATION in: Git Schema Diff")
        for err in migration_errors:
            print(f"  [Line {err['line']}] [{err['type']}] -> {err['message']}")
            total_violations += 1

    # 4. Run Layer 20 Documentation Sync Compliance Checks
    if total_violations == 0:
        for target_dir in target_dirs:
            # Run in write mode so missing AI docs are generated and written to disk.
            # The CI will auto-commit these changes instead of failing.
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
        log_compliance_evidence("FAIL", f"Architectural compliance scan failed with {total_violations} violations across source code checks.")
        sys.exit(1)
    else:
        print("ARCHITECTURAL COMPLIANCE SUCCESS: All systems pass production standards.")
        print("=" * 80)
        log_compliance_evidence("PASS", "Architectural compliance scan completed successfully with 0 violations. Codebase standards verified.")
        sys.exit(0)

def log_compliance_evidence(status, detail):
    try:
        current_file_dir = os.path.dirname(os.path.abspath(__file__))
        # Navigate 2 levels up to common workspace root (C:\Users\sinya\Desktop\RokctAI)
        workspace_root = os.path.abspath(os.path.join(current_file_dir, "..", ".."))
        logger_script = os.path.join(workspace_root, "PlatformStack", ".rokct", "scripts", "log_evidence.py")
        
        if os.path.exists(logger_script):
            import subprocess
            subprocess.run([
                sys.executable, logger_script,
                "--control-id", "SOC2-CC7.1-COMPLIANCE",
                "--status", status,
                "--system", "compliance-scanner",
                "--detail", detail
            ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            print("Compliance scan evidence logged to PlatformStack successfully.")
        else:
            print(f"Compliance evidence logger not found at: {logger_script}")
    except Exception as e:
        print(f"Error logging compliance evidence: {e}")

if __name__ == "__main__":
    main()

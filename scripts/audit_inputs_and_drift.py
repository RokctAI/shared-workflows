#!/usr/bin/env python3
# Copyright (c) 2026, Rokct Intelligence (pty) Ltd.
# For license information, please see license.txt

import os
import re
import sys
import json

def parse_semver(version_str):
    """Parse version string like '1.2.3' or 'v1.2.3-rc' into major, minor, patch."""
    version_str = version_str.lstrip('v').split('-')[0]
    parts = version_str.split('.')
    try:
        return [int(p) for p in parts[:3]]
    except ValueError:
        return [0, 0, 0]

def check_version_drift(latest_version_str):
    """Scan all workflows in .github/workflows for version drift against latest_version."""
    latest_major, latest_minor, _ = parse_semver(latest_version_str)
    workflow_dir = ".github/workflows"
    if not os.path.exists(workflow_dir):
        return

    print("🔍 Auditing workflow version drift...")
    for root, _, files in os.walk(workflow_dir):
        for file in files:
            if not file.endswith((".yml", ".yaml")):
                continue
            
            filepath = os.path.join(root, file)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            except Exception as e:
                print(f"⚠️ Failed to read {filepath}: {e}")
                continue

            for idx, line in enumerate(lines):
                # Search for uses: RokctAI/shared-workflows/...@vX.Y.Z
                match = re.search(r"uses:\s*RokctAI/shared-workflows/[^@]+@(v?\d+\.\d+\.\d+(?:-\w+)?)", line)
                if match:
                    ref_version_str = match.group(1)
                    ref_major, ref_minor, _ = parse_semver(ref_version_str)

                    # Check if major version differs, or minor version is lagging by more than 2 minor releases
                    lagging = False
                    reason = ""
                    if ref_major < latest_major:
                        lagging = True
                        reason = f"major version upgrade (local: v{ref_version_str}, latest: v{latest_version_str})"
                    elif ref_major == latest_major and (latest_minor - ref_minor) > 2:
                        lagging = True
                        reason = f"lagging by {latest_minor - ref_minor} minor releases (local: v{ref_version_str}, latest: v{latest_version_str})"

                    if lagging:
                        print(f"::warning file={filepath},line={idx+1}::⚠️ Workflow version drift detected! Local reference is using v{ref_version_str} but latest stable is v{latest_version_str} ({reason}). Run fleet standardizer to align.")

def audit_inputs():
    """Scan workflows for deprecated or unpinned parameters."""
    workflow_dir = ".github/workflows"
    if not os.path.exists(workflow_dir):
        return

    print("🔍 Auditing parameter inputs and recommendations...")
    for root, _, files in os.walk(workflow_dir):
        for file in files:
            if not file.endswith((".yml", ".yaml")):
                continue
            
            filepath = os.path.join(root, file)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                print(f"⚠️ Failed to read {filepath}: {e}")
                continue

            lines = content.splitlines()

            # Recommendation 1: Pin flutter-version if using Flutter
            if "project_type: 'flutter'" in content or "project_type: flutter" in content:
                has_flutter_version_pin = False
                for line in lines:
                    if re.search(r"flutter-version:\s*['\"].+['\"]", line):
                        has_flutter_version_pin = True
                        break
                if not has_flutter_version_pin:
                    print(f"::warning file={filepath},line=1::💡 Recommendation: flutter-version is not explicitly pinned in Flutter project. We recommend pinning it to guarantee build reproducibility.")

            # Deprecation 1: Warn against using legacy `counter-key` if present (obsolete parameter)
            for idx, line in enumerate(lines):
                if "counter-key:" in line or "counter_key:" in line:
                    print(f"::warning file={filepath},line={idx+1}::⚠️ Deprecated input detected: 'counter-key' is deprecated in favor of central MONOREPO_PAT or repository-level COUNTER_API_KEY secret.")

def main():
    print("=" * 80)
    print("ROKCT FLEET STANDARD - AUTOMATED INPUTS & ROADMAP AUDITOR")
    print("=" * 80)

    # 1. Load latest stable version from version.json
    latest_version = "1.0.0"
    if os.path.exists("version.json"):
        try:
            with open("version.json", "r") as f:
                version_data = json.load(f)
                latest_version = version_data.get("version", "1.0.0")
        except Exception as e:
            print(f"⚠️ Failed to read version.json: {e}")
    
    print(f"Latest stable fleet version: v{latest_version}")

    # 2. Check for version drift
    check_version_drift(latest_version)

    # 3. Audit workflow parameters
    audit_inputs()

    print("=" * 80)
    print("AUDIT COMPLETE.")
    print("=" * 80)

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    main()

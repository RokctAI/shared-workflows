# Copyright (c) 2026 RokctAI
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Audits every SDK in the workspace: structure, manifest imports, and
cross-feature SDK imports (ADR-005).

The enforced structure is re-derived from a 2026-08 census of all 25 fleet
SDKs (directory -> SDKs having it, counted with the same combined
common/ + persona logic validate_structure uses):

    di 24 | application 18 | infrastructure/repositories 16 |
    domain/interface 13 | infrastructure/services 9 |
    infrastructure/models 6 | utils 5 | infrastructure/database 2

Rules follow the census: near-universal dirs (>=90%) are ERRORs,
common-but-not-universal (>=50%) are WARNINGs, minority patterns are not
required at all. Uniformity rules stay strict regardless of counts: the
repository folder must be spelled `infrastructure/repositories` (plural),
`infrastructure/models` must be sliced into data/ + response/ wherever it
exists, and `infrastructure/database` is required exactly when the
manifest declares the `database` key (2/2 correlation in the fleet).
"""
import argparse
import os
import json
import re
import sys
import subprocess
from pathlib import Path
from datetime import datetime

class SDKLogger:
    def __init__(self, log_dir="."):
        self.audit_log = os.path.join(log_dir, "sdk_audit.log")
        self.error_log = os.path.join(log_dir, "sdk_errors.log")
        self.valid_log = os.path.join(log_dir, "sdk_valid.log")
        self.issues = {} # sdk_name -> [messages]
        self.valid_sdks = []
        
        # Clear old logs
        open(self.audit_log, 'w').close()
        open(self.error_log, 'w').close()
        open(self.valid_log, 'w').close()

    def log(self, message, level="INFO", sdk_name=None):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted_msg = f"[{timestamp}] [{level}] {message}"
        
        with open(self.audit_log, 'a', encoding='utf-8') as f:
            f.write(formatted_msg + "\n")
        
        if level in ["ERROR", "WARNING"] and sdk_name:
            if sdk_name not in self.issues:
                self.issues[sdk_name] = []
            self.issues[sdk_name].append(formatted_msg)
        
        print(formatted_msg)

    def write_summaries(self, all_sdks):
        # Write Valid SDKs
        invalid_sdks = self.issues.keys()
        valid_sdks = [sdk for sdk in all_sdks if sdk not in invalid_sdks]
        
        with open(self.valid_log, 'w', encoding='utf-8') as f:
            f.write("=== 100% VALID SDKS ===\n")
            for sdk in sorted(valid_sdks):
                f.write(f"{sdk}\n")
        
        # Write Grouped Errors
        with open(self.error_log, 'w', encoding='utf-8') as f:
            f.write("=== SDK ISSUES SUMMARY ===\n\n")
            for sdk in sorted(self.issues.keys()):
                f.write(f"SDK: {sdk}\n")
                for issue in self.issues[sdk]:
                    f.write(f"  - {issue}\n")
                f.write("\n")


def run_compliance_scanner(sdk_name, dart_dir, root_dir, logger):
    # Relative to this script's own location, not a hardcoded personal path -
    # this script and compliance_scanner.py live side by side in
    # shared-workflows/scripts/, so this resolves correctly whether run
    # locally or from a CI checkout, on any machine/account.
    scanner_path = Path(__file__).resolve().parent / "compliance_scanner.py"
    if not scanner_path.exists():
        logger.log(f"Compliance scanner not found at {scanner_path}", "ERROR")
        return False

    logger.log(f"Running compliance scanner in {dart_dir}...")
    
    env = os.environ.copy()
    env["EVIDENCE_REPO_DIR"] = str(root_dir)
    
    try:
        proc = subprocess.run(
            [sys.executable, str(scanner_path)],
            cwd=str(dart_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env
        )
        
        out = proc.stdout + proc.stderr
        if "ARCHITECTURAL COMPLIANCE FAILED" in out:
            # Try to extract violation count
            match = re.search(r"ARCHITECTURAL COMPLIANCE FAILED: (\d+)", out)
            count = match.group(1) if match else "some"
            logger.log(f"Compliance check FAILED for {sdk_name} ({count} violations).", "ERROR", sdk_name)
            return False
        
        logger.log(f"Compliance check PASSED for {sdk_name}.", "INFO")
        return True
    except Exception as e:
        logger.log(f"Error running compliance scanner for {sdk_name}: {e}", "ERROR", sdk_name)
        return False

def find_manifests(root_dir):
    manifests = []
    for root, dirs, files in os.walk(root_dir):
        if 'node_modules' in dirs:
            dirs.remove('node_modules')
        if '.next' in dirs:
            dirs.remove('.next')
        if '.kilo' in dirs:
            dirs.remove('.kilo')
        if '.rokct' in dirs:
            dirs.remove('.rokct')
        if 'manifest.json' in files and 'dart' in root:
            manifests.append(os.path.join(root, 'manifest.json'))
    return manifests

def parse_manifests(manifest_paths):
    registry = {} 
    sdk_data = {} 
    
    for path in manifest_paths:
        try:
            with open(path, 'r', encoding='utf-8-sig') as f:
                data = json.load(f)
                sdk_name = data.get('name')
                if not sdk_name:
                    continue
                
                sdk_root = Path(path).parent.parent
                dart_dir = Path(path).parent
                sdk_data[sdk_name] = {
                    'manifest_path': path,
                    'root_dir': sdk_root,
                    'dart_dir': dart_dir,
                    # Whatever this SDK's own manifest declares under
                    # "app_type" - not every SDK has every role, so the
                    # structure check must only look for folders this SDK
                    # actually claims (e.g. booking_sdk only ever declares
                    # 'customer', revenue_sdk only 'manager').
                    'personas': list((data.get('app_type') or {}).keys()),
                    # infrastructure/database is only expected when the SDK
                    # actually declares tables via the manifest's "database"
                    # key (optional per SDK_ECOSYSTEM.md).
                    'declares_database': 'database' in data
                }
                
                # Top-level installs are flavor-independent; `app_type.<flavor>`
                # blocks install only into an app whose .rokct/config/app_type
                # matches. Both land real files in the host shell, so both must
                # register here - otherwise a route declared inside an app_type
                # block is reported as an invalid ${package} import.
                install_blocks = [data.get('installs', [])]
                for flavor_block in (data.get('app_type') or {}).values():
                    if isinstance(flavor_block, dict):
                        install_blocks.append(flavor_block.get('installs', []))

                for installs in install_blocks:
                    for install in installs:
                        to_path = install.get('to')
                        if to_path:
                            norm_to = to_path.replace('lib/', '', 1) if to_path.startswith('lib/') else to_path
                            registry[norm_to] = sdk_name
        except Exception as e:
            print(f"[!] Error parsing {path}: {e}")
            
    return registry, sdk_data

def has_files(path):
    """Checks if a directory exists and contains at least one file recursively."""
    if not path.is_dir():
        return False
    for root, _, files in os.walk(path):
        if files:
            return True
    return False

def validate_structure(sdk_name, dart_dir, logger, personas=None,
                       declares_database=False):
    # Determine the base path for structure checks
    # Check for lib/src first, then fallback to dart_dir
    base_path = dart_dir / 'lib' / 'src'
    if not base_path.is_dir():
        base_path = dart_dir

    # common/ (SDKs wrapped for forward-prep refork) and persona folders
    # (driver/, manager/, ...) are siblings under base_path, not parent/child -
    # nesting a role folder inside common/ buries role-only code inside the
    # "shared" directory instead of actually separating it from common. Only
    # whatever this SDK's own manifest declares under "app_type" counts as a
    # persona (see parse_manifests) - not a fixed universal list. A
    # non-marketplace SDK was never going to have a customer/ folder, and
    # requiring one there was the bug.
    common_dir = base_path / 'common'
    found_personas = [p for p in (personas or []) if (base_path / p).is_dir()]

    paths_to_validate = []
    if common_dir.is_dir():
        paths_to_validate.append(common_dir)
    paths_to_validate += [base_path / p for p in found_personas]
    if not paths_to_validate:
        paths_to_validate = [base_path]
    
    sdk_valid = True
    # A split SDK (common/ + one or more persona siblings, e.g. zones_sdk's
    # common/ + driver/) is a deliberate division of one structure across
    # multiple directories - common/ holding contracts+DI, a persona folder
    # holding the concrete implementation. Neither half is a complete SDK on
    # its own by design, so requiring every mandatory folder in EACH path
    # independently reports the split itself as a pile of errors. For a
    # split SDK, a requirement is satisfied if ANY scanned path has it;
    # missing entirely only if NONE of them do. A non-split SDK (a single
    # path, common/ absent or no personas declared) keeps the original
    # per-path behavior - there's only one path anyway.
    combined = len(paths_to_validate) > 1
    combined_label = ' + '.join(str(p).replace('\\', '/') for p in paths_to_validate)

    def report(rel_label, msg, level="ERROR"):
        label = combined_label if combined else path_str
        logger.log(f"[{label}] {msg}", level, sdk_name)
        if level == "ERROR":
            nonlocal sdk_valid
            sdk_valid = False

    for path in paths_to_validate:
        path_str = str(path).replace('\\', '/')
        logger.log(f"Checking structure at: {path_str}")

    def any_path_has(rel_path):
        return any(has_files(p / rel_path) for p in paths_to_validate)

    def any_path_is_dir(rel_path):
        return any((p / rel_path).is_dir() for p in paths_to_validate)

    # 1. Application (18/25 SDKs — common, not universal, so absence is a
    # WARNING). Where it exists it must be feature-sliced: subfolders per
    # feature, no bare pile of files.
    if any_path_is_dir('application'):
        subdirs_by_path = {
            p: [d for d in os.listdir(p / 'application') if (p / 'application' / d).is_dir()]
            for p in paths_to_validate if (p / 'application').is_dir()
        }
        if not any(subdirs_by_path.values()):
            report('application', "'application' must contain subfolders for different features.")
        else:
            for p, subdirs in subdirs_by_path.items():
                for sd in subdirs:
                    if not has_files(p / 'application' / sd):
                        logger.log(f"[{str(p).replace(chr(92), '/')}] 'application/{sd}' is empty. Expected files inside.", "WARNING", sdk_name)
    else:
        report('application', "Missing 'application' directory.", "WARNING")

    # 2. Infrastructure Models Slicing. Only a minority of SDKs (6/25) keep
    # API models under infrastructure/models, so the directory itself is not
    # required — but wherever it exists the canonical slices are data/ and
    # response/ (every conforming SDK has exactly those; request/ is not part
    # of the canonical slicing under infrastructure/models).
    if any_path_is_dir('infrastructure/models'):
        slices = ['data', 'response']
        for s in slices:
            if not any_path_has(f'infrastructure/models/{s}'):
                report(f'infrastructure/models/{s}', f"Missing or empty model slice: 'infrastructure/models/{s}'")
        for p in paths_to_validate:
            inf_models_dir = p / 'infrastructure' / 'models'
            if inf_models_dir.is_dir():
                for item in os.listdir(inf_models_dir):
                    if os.path.isfile(inf_models_dir / item):
                        logger.log(f"[{str(p).replace(chr(92), '/')}] File {item} found directly in 'infrastructure/models'. Files must be in data/response slices.", "WARNING", sdk_name)

    # 3. Repository folder naming: the fleet standard is the plural
    # 'infrastructure/repositories' (16/25 SDKs; zero conforming SDKs use the
    # singular). A singular 'infrastructure/repository' is a naming error so
    # the spelling stays uniform.
    if any_path_is_dir('infrastructure/repository'):
        report('infrastructure/repository',
               "'infrastructure/repository' found — fleet standard is the plural "
               "'infrastructure/repositories'. Rename the folder.")

    # 4. Required / expected folders with files, per the fleet census:
    #    - di (24/25) is near-universal -> ERROR when missing.
    #    - infrastructure/database is required exactly when this SDK's
    #      manifest declares the 'database' key -> ERROR then, not expected
    #      otherwise (only 2/25 SDKs declare it, and both have the folder).
    #    - infrastructure/repositories (16/25) and domain/interface (13/25)
    #      are common-but-not-universal -> WARNING when missing.
    #    (infrastructure/services (9/25) and utils (5/25) are minority
    #    patterns and no longer expected at all.)
    if not any_path_has('di'):
        report('di', "Dependency Injection configuration missing (Expected at di)")
    if declares_database and not any_path_has('infrastructure/database'):
        report('infrastructure/database',
               "Manifest declares the 'database' key but database definitions "
               "are missing (Expected at infrastructure/database)")
    expected = {
        'infrastructure/repositories': 'Repository implementations missing',
        'domain/interface': 'Domain interfaces missing',
    }
    for rel_path, msg in expected.items():
        if not any_path_has(rel_path):
            report(rel_path, f"{msg} (Expected at {rel_path})", "WARNING")

    return sdk_valid

# The one sanctioned cross-SDK dependency: base_sdk is the shared kernel that
# every SDK depends on by convention (it replaced core_sdk in the 2026-07
# refork). Do NOT add entries here without an explicit human decision —
# feature SDKs must stay decoupled from each other (consumer-owned
# interfaces + host-app adapters).
CROSS_SDK_IMPORT_ALLOWLIST = {"base_sdk"}

# Matches a real (non-commented) Dart import of another package, anchored to
# the start of the line so commented-out example adapters in di/ files are
# not flagged.
CROSS_SDK_IMPORT_RE = re.compile(r"^\s*(?:import|export)\s+['\"]package:([A-Za-z0-9_]+)/")


def validate_cross_sdk_imports(sdk_name, dart_dir, sdk_data, logger):
    """Flags direct imports of another feature SDK's package.

    Scans the SDK's own package source (lib/). templates/ is intentionally
    not scanned: template files are copied INTO the host app at install time,
    and the host app is exactly where composing multiple installed SDKs is
    legitimate.
    """
    lib_dir = Path(dart_dir) / 'lib'
    if not lib_dir.is_dir():
        return True

    sdk_valid = True
    for root, _, files in os.walk(lib_dir):
        for fname in files:
            if not fname.endswith('.dart'):
                continue
            fpath = Path(root) / fname
            try:
                with open(fpath, 'r', encoding='utf-8-sig', errors='replace') as f:
                    for lineno, line in enumerate(f, 1):
                        match = CROSS_SDK_IMPORT_RE.match(line)
                        if not match:
                            continue
                        imported_sdk = match.group(1)
                        if imported_sdk == sdk_name:
                            continue
                        if imported_sdk in CROSS_SDK_IMPORT_ALLOWLIST:
                            continue
                        if imported_sdk not in sdk_data:
                            # Not a discovered local SDK. In per-repo (CI)
                            # mode a sibling repo's SDK also lands here, so a
                            # package that looks like one of ours by naming
                            # convention gets a heuristic WARNING instead of
                            # being silently treated as third-party.
                            if imported_sdk.endswith('_sdk'):
                                rel_file = os.path.relpath(fpath, dart_dir).replace('\\', '/')
                                logger.log(
                                    f"{sdk_name} imports {imported_sdk} at {rel_file}:{lineno} "
                                    f"— possible cross-repo SDK import — run full-workspace "
                                    f"mode to verify.",
                                    "WARNING",
                                    sdk_name,
                                )
                            continue  # third-party package, not one of ours
                        rel_file = os.path.relpath(fpath, dart_dir).replace('\\', '/')
                        logger.log(
                            f"Cross-feature SDK import: {sdk_name} imports {imported_sdk} "
                            f"directly at {rel_file}:{lineno} — consumer should define its own "
                            f"interface and receive an implementation via DI, not import the "
                            f"producer SDK's package.",
                            "ERROR",
                            sdk_name,
                        )
                        sdk_valid = False
            except Exception as e:
                logger.log(
                    f"Error scanning {fpath} for cross-SDK imports: {e}",
                    "ERROR",
                    sdk_name,
                )
                sdk_valid = False
    return sdk_valid


def extract_imports(manifest_data):
    """Collects package: imports from the manifest's structured fields.

    Walks the parsed JSON instead of regex-scanning the raw text, skipping
    every `_comment*` key — those fields are the ecosystem's prose
    documentation and routinely mention package paths that are not imports.
    Real imports only live in structured fields (routes/app_routes/
    database/boot_hooks/embedded_widgets/app_type flavor blocks/...) as an
    "import" string or an "imports" list of Dart import statements; walking
    all non-comment string values covers every such shape.
    """
    found = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key.startswith('_comment'):
                    continue
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            found.extend(re.findall(r"package:([^'\"]+)", node))

    walk(manifest_data)
    return found

# ${package}/ paths generated into the host app shell by the composer itself
# (see protocol core/utils/flutter/sdk_installer_base.py, ROUTER_FILE): no
# SDK manifest "installs" these, yet importing them is valid because the
# composer guarantees they exist in every composed app. Paths are relative
# to lib/ (same normalization as the install registry).
COMPOSER_GENERATED_PATHS = {
    'presentation/routes/app_router.dart',
}

def validate_import(import_path, registry, sdk_data):
    if import_path.startswith('${package}/'):
        rel_path = import_path[len('${package}/'):]
        if rel_path in COMPOSER_GENERATED_PATHS:
            return True, None
        for to_path, provider in registry.items():
            if rel_path.startswith(to_path):
                return True, None
        return False, f"No SDK installs a file to {rel_path}"

    if '/' in import_path:
        parts = import_path.split('/', 1)
        pkg_name = parts[0]
        internal_path = parts[1]
        
        if pkg_name in sdk_data:
            filename = os.path.basename(internal_path)
            dart_dir = sdk_data[pkg_name]['dart_dir']
            
            found = False
            for root, _, files in os.walk(dart_dir):
                if filename in files:
                    found = True
                    break
            
            if found:
                return True, None
            return False, f"File {filename} not found in {pkg_name} SDK"
        else:
            return False, f"Package {pkg_name} not found in SDK registry"
    
    pkg_name = import_path.split('/')[0] if '/' in import_path else import_path
    if pkg_name in sdk_data:
        return True, None
        
    return False, f"Unknown package {import_path}"

def parse_args():
    parser = argparse.ArgumentParser(
        description="Audit every SDK in the workspace: structure, manifest "
        "imports, and cross-feature SDK imports."
    )
    parser.add_argument(
        "--compliance",
        action="store_true",
        help="Also run the architectural compliance scanner for each SDK "
        "(slow; skipped by default).",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Workspace root to scan. Defaults to $GITHUB_WORKSPACE in CI "
        "(a single-repo checkout - the per-repo/CI mode), or this script's "
        "own repo-sibling workspace root locally (scripts/ -> "
        "shared-workflows/ -> the folder holding every sibling repo - the "
        "full multi-repo scan mode). Override explicitly if neither fits.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if args.root:
        root_dir = args.root
    elif os.environ.get("GITHUB_WORKSPACE"):
        root_dir = os.environ["GITHUB_WORKSPACE"]
    else:
        root_dir = str(Path(__file__).resolve().parent.parent.parent)
    logger = SDKLogger()

    logger.log(f"Starting global SDK audit in {root_dir}...")
    if not args.compliance:
        logger.log("Compliance scan disabled (pass --compliance to enable).")
    
    manifest_paths = find_manifests(root_dir)
    if not manifest_paths:
        logger.log("No manifests found. Audit aborted.", "ERROR")
        return

    registry, sdk_data = parse_manifests(manifest_paths)
    logger.log(f"Loaded {len(sdk_data)} SDKs and {len(registry)} installation paths.")
    
    overall_errors = 0
    
    for sdk_name, info in sdk_data.items():
        logger.log(f"--- Auditing SDK: {sdk_name} ---")
        
        # 1. Structure Check
        if not validate_structure(sdk_name, info['dart_dir'], logger,
                                  info.get('personas'),
                                  info.get('declares_database', False)):
            overall_errors += 1

        # 2. Import Validation
        try:
            with open(info['manifest_path'], 'r', encoding='utf-8-sig') as f:
                content = json.load(f)

            imports = extract_imports(content)
            for imp in imports:
                # Extract just the path after 'package:'
                path_to_check = imp
                
                valid, msg = validate_import(path_to_check, registry, sdk_data)
                if not valid:
                    logger.log(f"Invalid Import [package:{imp}] - {msg}", "ERROR", sdk_name)
                    overall_errors += 1
        except Exception as e:
            logger.log(f"Error reading manifest for import check: {e}", "ERROR", sdk_name)
            overall_errors += 1

        # 3. Cross-feature SDK import check (consumer-owned interfaces + DI)
        if not validate_cross_sdk_imports(sdk_name, info['dart_dir'], sdk_data, logger):
            overall_errors += 1

        # 4. Architectural Compliance Scan (opt-in via --compliance)
        if args.compliance:
            if not run_compliance_scanner(sdk_name, info['dart_dir'], info['root_dir'], logger):
                overall_errors += 1


    logger.write_summaries(list(sdk_data.keys()))

    if overall_errors == 0:
        logger.log("Global audit completed. No issues found!")
    else:
        logger.log(f"Global audit completed. Found {overall_errors} issues. Check sdk_errors.log for details.", "WARNING")

if __name__ == '__main__':
    main()

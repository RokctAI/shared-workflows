#!/usr/bin/env python3
"""
fleet_compliance.py -- Run ROKCT compliance scanner across ALL local repos.

Discovers every folder under REPOS_ROOT that contains a .git/ directory
at its root (i.e. it IS a git repo, not just any subfolder of one).

Usage:
    python fleet_compliance.py                        # scan all repos
    python fleet_compliance.py --verbose              # full per-violation output
    python fleet_compliance.py --only rpanel engram   # specific repos only

Skips: Frappenize (upstream vendor), shared-workflows (the scanner itself),
        paas_* (paas sub-apps)
"""

import os
import sys
import subprocess
import time
from pathlib import Path

# -- Config -------------------------------------------------------------------
REPOS_ROOT = Path(r"C:\Users\sinya\Desktop\RokctAI")
SCANNER    = REPOS_ROOT / "shared-workflows" / "scripts" / "compliance_scanner.py"

# Add exact names or glob-style prefixes ending with * to skip repos.
# Examples:  "Frappenize"  (exact)   "paas_*"  (any repo starting with paas_)
SKIP = {
    "Frappenize",           # upstream vendor
    "shared-workflows",     # scanner itself
    ".rokct",
    "nextjs",
    "tloumoka",
    "ROK",
    "ROK-paperclip-adapter",
    "paas_*",               # paas sub-apps
}

# ANSI colours (Windows Terminal / PowerShell 7+)
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

# -- Repo discovery -----------------------------------------------------------
def _is_skipped(name):
    for pattern in SKIP:
        if pattern.endswith("*"):
            if name.startswith(pattern[:-1]):
                return True
        elif name == pattern:
            return True
    return False

def discover_repos(root, only):
    repos = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        if _is_skipped(entry.name):
            continue
        if only and entry.name not in only:
            continue
        if (entry / ".git").is_dir():
            repos.append(entry)
    return repos

# -- Run scanner --------------------------------------------------------------
def run_scanner(repo, verbose):
    cmd = [sys.executable, str(SCANNER)]
    if verbose:
        cmd.append("--verbose")
    start = time.time()
    proc = subprocess.run(cmd, cwd=str(repo), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    elapsed = round(time.time() - start, 1)
    out_lines = (proc.stdout + proc.stderr).splitlines()
    violations = 0
    status = "PASS"
    for line in out_lines:
        if "ARCHITECTURAL COMPLIANCE FAILED" in line:
            status = "FAIL"
            try:
                violations = int(line.split(":")[1].strip().split()[0])
            except Exception:
                violations = -1
        elif "ARCHITECTURAL COMPLIANCE SUCCESS" in line:
            status = "PASS"
    return status, violations, out_lines, elapsed

# -- Output helpers -----------------------------------------------------------
SKIP_PREFIXES = (
    "[update_docs]", "Compliance evidence written",
    "DeprecationWarning", "datetime.datetime.utcnow", "timestamp =",
    "Use timezone-aware", "is deprecated",
)

def print_output(lines):
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if any(stripped.startswith(p) for p in SKIP_PREFIXES):
            continue
        print(f"  {line}")

# -- Main ---------------------------------------------------------------------
def main():
    args = sys.argv[1:]
    verbose   = "--verbose" in args or "-v" in args
    only_repos = [a for a in args if not a.startswith("-")]

    if not SCANNER.exists():
        print(f"{RED}ERROR: Scanner not found at {SCANNER}{RESET}")
        sys.exit(1)

    repos = discover_repos(REPOS_ROOT, only_repos)

    if not repos:
        print(f"{YELLOW}No git repos found under {REPOS_ROOT}{RESET}")
        sys.exit(0)

    W = 70
    print(f"\n{'=' * W}")
    print(f"  {BOLD}ROKCT FLEET COMPLIANCE SCAN{RESET}")
    print(f"  Repos root : {REPOS_ROOT}")
    print(f"  Repos found: {len(repos)}")
    print(f"  Skipping   : {', '.join(sorted(SKIP))}")

    print(f"{'=' * W}")

    results = []

    for repo in repos:
        print(f"\n{'─' * W}")
        print(f"  {CYAN}{BOLD}{repo.name}{RESET}")
        print(f"{'─' * W}")

        status, violations, out_lines, elapsed = run_scanner(repo, verbose)
        print_output(out_lines)

        colour = GREEN if status == "PASS" else RED
        vcount = "" if status == "PASS" else f"  ({violations} violations)"
        print(f"\n  -> {colour}{BOLD}{status}{RESET}{vcount}  [{elapsed}s]")
        results.append((repo.name, status, violations, elapsed))

    # -- Summary table --------------------------------------------------------
    print(f"\n\n{'=' * W}")
    print(f"  {BOLD}FLEET SUMMARY{RESET}")
    print(f"{'=' * W}")
    print(f"  {'Repo':<35} {'Status':<8} {'Violations':>10}  {'Time':>6}")
    print(f"  {'-'*35} {'-'*8} {'-'*10}  {'-'*6}")

    total_pass = total_fail = 0
    for name, status, violations, elapsed in results:
        colour = GREEN if status == "PASS" else RED
        vlabel = "-" if status == "PASS" else str(violations)
        print(f"  {name:<35} {colour}{status:<8}{RESET} {vlabel:>10}  {elapsed:>5}s")
        if status == "PASS":
            total_pass += 1
        else:
            total_fail += 1

    print(f"  {'-'*35} {'-'*8} {'-'*10}  {'-'*6}")
    fc = RED if total_fail else GREEN
    print(f"  {'TOTAL':<35} {GREEN}{total_pass} PASS{RESET} / {fc}{total_fail} FAIL{RESET}")
    print(f"{'=' * W}\n")

    if total_fail:
        failing = [n for n, s, *_ in results if s == "FAIL"]
        print(f"{RED}Failing repos: {', '.join(failing)}{RESET}\n")
        sys.exit(1)
    else:
        print(f"{GREEN}{BOLD}All repos compliant. ✓{RESET}\n")
        sys.exit(0)


if __name__ == "__main__":
    main()

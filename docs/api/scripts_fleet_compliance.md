# API Reference: fleet_compliance

Source file: `scripts/fleet_compliance.py`

## Module Description
fleet_compliance.py -- Run ROKCT compliance scanner across ALL local repos.

Discovers every folder under REPOS_ROOT that contains a .git/ directory
at its root (i.e. it IS a git repo, not just any subfolder of one).

Usage:
    python fleet_compliance.py                        # scan all repos
    python fleet_compliance.py --verbose              # full per-violation output
    python fleet_compliance.py --only rpanel engram   # specific repos only

Skips: Frappenize (upstream vendor), shared-workflows (the scanner itself),
        paas_* (paas sub-apps)

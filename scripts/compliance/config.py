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

"""Per-repo compliance configuration.

Looks for `compliance.config.json` at the repo root (or wherever
COMPLIANCE_CONFIG points). Shape:

    {
      "exclude_dirs":   ["vendor", "third_party"],
      "exclude_paths":  ["legacy/**", "*/generated/*"],
      "severity":       {"nextjs-i18n": "off", "caching-cdn": "error"},
      "fail_on":        "error"
    }

  exclude_dirs  — directory names pruned during the walk (added to the built-in
                  defaults; they are no longer hardcoded in compliance_scanner.py)
  exclude_paths — fnmatch globs matched against the repo-relative path of each file
  severity      — per-check overrides; "error" | "warning" | "off"
  fail_on       — "error" (default) fails only on error-severity findings;
                  "warning" makes warnings fail the gate too
"""

import fnmatch
import json
import os

CONFIG_FILENAME = "compliance.config.json"

# Directories never worth scanning. Previously hardcoded inline in
# compliance_scanner.py's two os.walk calls; a repo extends this via
# "exclude_dirs" rather than editing scanner source.
#
# Do NOT add ".github" or ".rokct" here. The layer-2 'structural-special-dirs'
# check exists precisely to find .py files under those directories — pruning
# them from the walk makes the check silently unable to fire. (It was briefly
# added here by mistake; see test_github_dir_is_not_pruned.)
#
# "frappe"/"erpnext"/"payments"/"hrms"/"lms" exist to skip VENDORED upstream
# checkouts of the Frappe framework and its standard apps (third-party deps,
# not owned code — see commit 610abff). They do NOT stop an SDK's own
# module dirs from being scanned:
#   * sdk_validator.py runs the scanner with the discovered SDK half as its
#     working directory / walk root, so the half's own tree is the walk root
#     and cannot be pruned;
#   * a repo-ROOT scan keeps any colliding-name directory that carries an
#     SDK manifest half (see SDK_MANIFEST_MARKERS / is_first_party_module_dir
#     below) — first-party modules like agent/lms, pay/payments and pay/hrms
#     stay scanned while vendored framework checkouts stay excluded.
DEFAULT_EXCLUDE_DIRS = [
    ".git", "node_modules", ".next", "dist", ".dart_tool", "build",
    "ios", "android", "env", "__pycache__", "Compliance", ".shared-workflows",
    "frappe", "erpnext", "payments", "hrms", "lms",
]

DEFAULT_CONFIG = {
    "exclude_dirs": [],
    "exclude_paths": [],
    "severity": {},
    "fail_on": "error",
}


def find_config(start_dirs):
    """Locate compliance.config.json: env override, then upward from each target."""
    override = os.environ.get("COMPLIANCE_CONFIG")
    if override and os.path.isfile(override):
        return override
    for start in start_dirs or []:
        curr = os.path.abspath(start)
        while True:
            candidate = os.path.join(curr, CONFIG_FILENAME)
            if os.path.isfile(candidate):
                return candidate
            parent = os.path.dirname(curr)
            if parent == curr:
                break
            curr = parent
    return None


def load_config(start_dirs):
    """Return (config_dict, config_path_or_None). Malformed config is non-fatal."""
    config = dict(DEFAULT_CONFIG)
    config["exclude_dirs"] = []
    config["exclude_paths"] = []
    config["severity"] = {}

    path = find_config(start_dirs)
    if not path:
        return config, None
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        print(f"[compliance] WARNING: could not read {path}: {e}")
        return config, None

    for key in ("exclude_dirs", "exclude_paths"):
        value = raw.get(key)
        if isinstance(value, list):
            config[key] = [str(x) for x in value]
    if isinstance(raw.get("severity"), dict):
        config["severity"] = {str(k): str(v) for k, v in raw["severity"].items()}
    if raw.get("fail_on") in ("error", "warning"):
        config["fail_on"] = raw["fail_on"]
    return config, path


# Marker files that identify a directory as a FIRST-PARTY SDK module (or one
# of its flavor halves) rather than a vendored upstream checkout. The
# "frappe"/"erpnext"/"payments"/"hrms"/"lms" entries in DEFAULT_EXCLUDE_DIRS
# exist to skip vendored Frappe-framework checkouts, but those names collide
# with first-party fleet module dirs (agent/lms, pay/payments, pay/hrms) —
# a repo-root scan would silently hide those modules. Vendored framework
# checkouts carry none of these manifests; first-party modules always do.
SDK_MANIFEST_MARKERS = (
    "manifest.json",                             # a flavor half itself (lms/frappe/)
    os.path.join("frappe", "manifest.json"),     # a module dir holding halves (lms/)
    os.path.join("nextjs", "manifest.json"),
    os.path.join("dart", "manifest.json"),
)


def is_first_party_module_dir(path):
    """True if `path` contains an SDK manifest half — never prune such a dir.

    Applies only as an override for directories whose NAME is in the exclude
    list; everything else keeps exact-name pruning semantics unchanged.
    """
    for marker in SDK_MANIFEST_MARKERS:
        if os.path.isfile(os.path.join(path, marker)):
            return True
    return False


def excluded_dirs(config):
    return set(DEFAULT_EXCLUDE_DIRS) | set(config.get("exclude_dirs", []))


def is_path_excluded(filepath, config, base_dir=None):
    """True if filepath matches any exclude_paths glob."""
    patterns = config.get("exclude_paths") or []
    if not patterns:
        return False
    normalized = os.path.abspath(filepath).replace("\\", "/")
    candidates = [normalized]
    if base_dir:
        try:
            candidates.append(
                os.path.relpath(filepath, base_dir).replace("\\", "/")
            )
        except Exception:
            pass
    for pattern in patterns:
        for candidate in candidates:
            if fnmatch.fnmatch(candidate, pattern) or fnmatch.fnmatch(candidate, f"*/{pattern.lstrip('/')}"):
                return True
    return False

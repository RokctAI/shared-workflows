# Copyright (c) 2026 ROKCT INTELLIGENCE (PTY) LTD
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

# compliance-ignore-file: structural-special-dirs
import os
import sys
import json
import re
import hashlib
import subprocess
import urllib.request
from datetime import datetime, timezone

PROTOCOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.getcwd()
ROKCT_DIR = os.path.join(PROJECT_ROOT, ".rokct")
CONFIG_PATH = os.path.join(ROKCT_DIR, ".workspace_config.json")

# Pinned by tools/gen_protocol_lock.py - do not edit these constants by hand.
# maintenance.yml is installed as a GitHub workflow (i.e. it is code), so the
# fetch is pinned to a commit and SHA-256 verified before it is written.
PROTOCOL_REF = "48bac4e33877de630148876f6f3e88c34ce208d7"
MAINTENANCE_PATH = "workflows/maintenance.yml"
MAINTENANCE_SHA256 = "df37cf18061299ce6d413f3f9f5017882a7bd044e56e15bad24a13b03cff473d"
MAINTENANCE_URL = f"https://raw.githubusercontent.com/RokctAI/The-Rokct-Protocol/{PROTOCOL_REF}/{MAINTENANCE_PATH}"


def fetch_maintenance_verified():
    """Fetch maintenance.yml pinned to PROTOCOL_REF and verify its SHA-256
    before returning the bytes. Returns None on fetch failure; a hash
    mismatch aborts outright - the file becomes a GitHub workflow."""
    try:
        req = urllib.request.Request(
            MAINTENANCE_URL,
            headers={"User-Agent": "Mozilla/5.0", "X-Trace-Id": "agent-http"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            content = r.read()
    except Exception as e:
        print(f"[sync] Failed to fetch maintenance workflow: {e}")
        return None
    digest = hashlib.sha256(content).hexdigest()
    if digest != MAINTENANCE_SHA256:
        print(
            f"[sync] Integrity check failed for {MAINTENANCE_PATH} (ref {PROTOCOL_REF}):",
            file=sys.stderr,
        )
        print(f"[sync]   expected sha256 {MAINTENANCE_SHA256}", file=sys.stderr)
        print(f"[sync]   actual   sha256 {digest}", file=sys.stderr)
        print("[sync] Refusing to install unverified workflow.", file=sys.stderr)
        sys.exit(1)
    return content


HEADER = "<!-- ROKCT-SYNC-START: {repo}/{session}/{ts} -->\n"
FOOTER = "<!-- ROKCT-SYNC-END: {repo}/{session}/{ts} -->\n"


def load_config():
    # Load the workspace configuration to identify parent repo and working files
    if not os.path.exists(CONFIG_PATH):
        print("[sync] No .workspace_config.json found")
        return None
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def file_hash(path):
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


def extract_new_sections(child_path, parent_path, repo, session):
    # Extract only the unique content from child that isn't already in parent
    # to prevent duplication during additive sync
    if not os.path.exists(child_path):
        return None
    child_content = open(child_path, "r", encoding="utf-8").read().strip()
    if not child_content:
        return None

    already_synced = ""
    if os.path.exists(parent_path):
        parent_content = open(parent_path, "r", encoding="utf-8").read()
        # Find all synced blocks for this specific repository
        escaped_repo = re.escape(repo)
        pattern = (
            r"<!-- ROKCT-SYNC-START: "
            + escaped_repo
            + r"/.*? -->\n(.*?)\n<!-- ROKCT-SYNC-END: "
            + escaped_repo
            + r"/.*? -->"
        )
        matches = re.findall(pattern, parent_content, re.DOTALL)
        if matches:
            already_synced = "\n".join(m.strip() for m in matches).strip()

    if already_synced and child_content.startswith(already_synced):
        new_content = child_content[len(already_synced) :].strip()
    else:
        # Fallback if child has no synced prefix
        child_lines = child_content.splitlines()
        if os.path.exists(parent_path):
            parent_content = open(parent_path, "r", encoding="utf-8").read()
            if child_content in parent_content:
                return None
            new_lines = []
            for line in reversed(child_lines):
                if line in parent_content:
                    break
                new_lines.insert(0, line)
            new_content = "\n".join(new_lines).strip()
        else:
            new_content = child_content

    if not new_content:
        return None

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return (
        HEADER.format(repo=repo, session=session, ts=ts)
        + new_content
        + "\n"
        + FOOTER.format(repo=repo, session=session, ts=ts)
    )


def get_child_repo():
    try:
        url = subprocess.check_output(
            ["git", "remote", "get-url", "origin"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        # Extract 'owner/repo' from git url
        if "github.com" in url:
            parts = url.split("github.com/")[-1].replace(".git", "").split("/")
            return f"{parts[0]}/{parts[1]}"
    except Exception:
        pass
    return "unknown-child"


def fetch_maintenance_workflow(dest_path):
    """Fetch maintenance.yml (pinned + verified) from the protocol repository."""
    content = fetch_maintenance_verified()
    if content is None:
        return False
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with open(dest_path, "wb") as f:
        f.write(content)
    return True


def check_and_update_maintenance(parent_clone):
    """Ensure parent has the maintenance workflow. Only installs if missing to avoid overriding custom cron."""
    maintenance_path = os.path.join(
        parent_clone, ".github", "workflows", "maintenance.yml"
    )

    if os.path.exists(maintenance_path):
        # If it exists, we assume developers may have customized the cron or logic.
        # We do not overwrite it to avoid losing those customizations.
        return False

    print("[sync] Parent is missing maintenance workflow. Installing...")
    remote_content = fetch_maintenance_verified()
    if remote_content is None:
        print("[sync] Failed to install maintenance workflow")
        return False
    os.makedirs(os.path.dirname(maintenance_path), exist_ok=True)
    with open(maintenance_path, "wb") as f:
        f.write(remote_content)
    return True


def sync_to_parent(config):
    """Sync working files to the parent repo. Returns True when the sync
    completed (including the no-op cases), False on clone/push failure so
    main() can keep the .sync_ready marker and exit non-zero."""
    parent_repo = config.get("parent_repo")
    working_files = config.get(
        "working_files",
        ["memory.md", "decision_log.md", "project_map.md", "active_session.txt"],
    )
    if not parent_repo:
        print("[sync] No parent_repo in config")
        return True

    session = config.get("session_id", "unknown")
    child_repo = get_child_repo()

    parent_clone = os.path.join(ROKCT_DIR, ".parent_clone")

    if os.path.isdir(parent_clone):
        subprocess.run(
            ["git", "-C", parent_clone, "fetch", "origin"], capture_output=True
        )
        subprocess.run(
            [
                "git",
                "-C",
                parent_clone,
                "reset",
                "--hard",
                f"origin/{config.get('parent_branch', 'main')}",
            ],
            capture_output=True,
        )
    else:
        os.makedirs(parent_clone, exist_ok=True)
        clone_url = f"https://github.com/{parent_repo}.git"
        if config.get("parent_token"):
            clone_url = f"https://{config['parent_token']}@github.com/{parent_repo}.git"
        result = subprocess.run(
            [
                "git",
                "clone",
                "--branch",
                config.get("parent_branch", "main"),
                clone_url,
                parent_clone,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"[sync] Clone failed: {result.stderr}")
            return False

    parent_rokct = os.path.join(parent_clone, ".rokct")
    os.makedirs(parent_rokct, exist_ok=True)

    # Guard: Ensure parent has the LATEST maintenance workflow
    any_changes = check_and_update_maintenance(parent_clone)

    for rel_file in working_files:
        child_path = os.path.join(ROKCT_DIR, rel_file)
        parent_path = os.path.join(parent_rokct, rel_file)

        section = extract_new_sections(child_path, parent_path, child_repo, session)
        if section:
            os.makedirs(os.path.dirname(parent_path), exist_ok=True)
            existing = ""
            if os.path.exists(parent_path):
                existing = open(parent_path, "r", encoding="utf-8").read()
            with open(parent_path, "w", encoding="utf-8") as f:
                f.write(existing.rstrip() + "\n\n" + section + "\n")
            print(f"[sync] Appended new sections to parent .rokct/{rel_file}")
            any_changes = True
        else:
            print(f"[sync] No new content for .rokct/{rel_file}")

    if not any_changes:
        print("[sync] No changes to push")
        return True

    subprocess.run(
        [
            "git",
            "-C",
            parent_clone,
            "config",
            "user.email",
            "rokct-bot@users.noreply.github.com",
        ],
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", parent_clone, "config", "user.name", "rokct-bot"],
        capture_output=True,
    )
    subprocess.run(["git", "-C", parent_clone, "add", ".rokct/"], capture_output=True)
    subprocess.run(
        ["git", "-C", parent_clone, "add", ".github/workflows/maintenance.yml"],
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            parent_clone,
            "commit",
            "-m",
            f"chore(workspace): sync working files from {child_repo} and update maintenance [skip ci]",
        ],
        capture_output=True,
    )
    result = subprocess.run(
        ["git", "-C", parent_clone, "push"], capture_output=True, text=True
    )
    if result.returncode == 0:
        print("[sync] Pushed to parent repo")
        return True
    print(f"[sync] Push failed: {result.stderr}", file=sys.stderr)
    return False


def main():
    config = load_config()
    if not config:
        return
    ok = sync_to_parent(config)
    if not ok:
        # Keep the .sync_ready marker so the next run retries the sync, and
        # exit non-zero so CI surfaces the failure instead of swallowing it.
        print(
            "[sync] Sync failed - keeping .sync_ready marker for retry", file=sys.stderr
        )
        sys.exit(1)

    # Remove the sync marker only after a successful sync
    sync_marker = os.path.join(ROKCT_DIR, ".sync_ready")
    if os.path.exists(sync_marker):
        os.remove(sync_marker)
        print("[sync] Removed .sync_ready marker")


if __name__ == "__main__":
    main()

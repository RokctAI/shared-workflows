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

# compliance-ignore-file: structural-special-dirs
import os
import hashlib
import shutil
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
PROJECT_ROOT = Path.cwd()
ROKCT_DIR = PROJECT_ROOT / ".rokct"
# Pinned by tools/gen_protocol_lock.py - do not edit these constants by hand.
# Manifest fetches are data-only, but pinning keeps them immutable too.
PROTOCOL_REF = "48bac4e33877de630148876f6f3e88c34ce208d7"
GITHUB_RAW_BASE = (
    f"https://raw.githubusercontent.com/RokctAI/The-Rokct-Protocol/{PROTOCOL_REF}"
)


def dir_hash(d: Path):
    if not d.is_dir():
        return None
    h = hashlib.sha256()
    for path in sorted(p for p in d.rglob("*") if p.is_file()):
        rel = path.relative_to(d)
        h.update(str(rel).encode())
        h.update(path.read_bytes())
    return h.hexdigest()[:16]


def file_hash(path: Path):
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


_PINNED_HASH_CACHE = {}


def pinned_file_hash(rel: str):
    """Full SHA-256 of the protocol's pinned copy of rel: the local checkout
    when available, else the raw file at PROTOCOL_REF (data-only fetch).
    Returns None when the pinned copy cannot be read - callers then keep the
    working file, the safe default. Replaces the old advisory
    core/templates/manifest.json lookups; protocol.lock.json is the single
    enforcing integrity mechanism for pinned content."""
    if rel in _PINNED_HASH_CACHE:
        return _PINNED_HASH_CACHE[rel]
    digest = None
    p = BASE / rel
    if p.exists():
        digest = file_hash(p)
    else:
        url = f"{GITHUB_RAW_BASE}/{rel}"
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0", "X-Trace-Id": "agent-http"}
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                digest = hashlib.sha256(r.read()).hexdigest()
        except Exception:
            digest = None
    _PINNED_HASH_CACHE[rel] = digest
    return digest


def touch(path: Path):
    path.write_text("", encoding="utf-8")


def main():
    if not ROKCT_DIR.is_dir():
        print("[end] .rokct/ not found, nothing to do")
        return

    pristine_skills = "86400b7a6e267879"

    skills_dir = ROKCT_DIR / "skills"
    if skills_dir.is_dir():
        shutil.rmtree(skills_dir)
        print("[end] Deleted skills/ (unconditional cleanup)")

    # compose.py's wrapper fetches this into .rokct/ at runtime and deletes it
    # in its finally block; clean up any copy a crashed run left behind.
    installer_base = ROKCT_DIR / "sdk_installer_base.py"
    if installer_base.is_file():
        installer_base.unlink()
        print("[end] Deleted sdk_installer_base.py (transient compose runtime fetch)")

    workflows_dir = ROKCT_DIR / "workflows"
    if workflows_dir.is_dir():
        for f in workflows_dir.iterdir():
            if f.is_file() and f.name != "init_protocol.md":
                f.unlink()
                print(f"[end] Deleted workflow: {f.name}")
        print("[end] Cleaned workflows/ (kept init_protocol.md)")

    for item_path in ROKCT_DIR.iterdir():
        # install_state.json now lives at .rokct/cache/install_state.json
        # (cache/ is keep-whitelisted below); a legacy copy at .rokct/'s own
        # root is kept explicitly until the composer migrates it there.
        if item_path.name in (
            "active_session.txt",
            "initiate.py",
            "install_state.json",
        ):
            print(f"[end] Kept {item_path.name} (protocol tool)")
            continue
        if item_path.name == ".sync_ready":
            continue
        if item_path.is_dir():
            if item_path.name in (
                "workflows",
                "agent",
                "evidence",
                "images",
                "templates",
                "types",
                "config",
                "cache",
            ):
                continue
            shutil.rmtree(item_path)
            print(f"[end] Deleted directory: {item_path.name}")
            continue
        core_key = f"core/templates/{item_path.name}"
        local_rel = f"profiles/local/{item_path.name}"
        if item_path.name == "profiles.md":
            local_rel = "profiles/local/rules.md"
        item_digest = file_hash(item_path)
        if item_digest is not None and item_digest in (
            pinned_file_hash(core_key),
            pinned_file_hash(local_rel),
        ):
            item_path.unlink()
            print(f"[end] Deleted pristine {item_path.name}")
        else:
            print(f"[end] Kept modified {item_path.name}")

    touch(ROKCT_DIR / ".sync_ready")
    print(
        "[end] Created .sync_ready marker — CI will pick this up when active session ends"
    )
    print("[end] End protocol cleanup complete.")


if __name__ == "__main__":
    main()

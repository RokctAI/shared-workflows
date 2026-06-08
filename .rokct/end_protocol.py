import os
import hashlib
import json
import shutil
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
PROJECT_ROOT = Path.cwd()
ROKCT_DIR = PROJECT_ROOT / ".rokct"
GITHUB_RAW_BASE = "https://raw.githubusercontent.com/RokctAI/The-Rokct-Protocol/main"

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
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]

def load_json_remote(name: str) -> dict:
    url = f"{GITHUB_RAW_BASE}/{name}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode())
    except Exception:
        return {}

def load_json(name: str) -> dict:
    p = BASE / name
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return load_json_remote(name)

def touch(path: Path):
    path.write_text("", encoding="utf-8")

def main():
    if not ROKCT_DIR.is_dir():
        print("[end] .rokct/ not found, nothing to do")
        return

    core_manifest = load_json("core/templates/manifest.json")
    local_manifest = load_json("profiles/local/manifest.json")

    pristine_skills = "86400b7a6e267879"

    skills_dir = ROKCT_DIR / "skills"
    if skills_dir.is_dir():
        shutil.rmtree(skills_dir)
        print("[end] Deleted skills/ (unconditional cleanup)")

    workflows_dir = ROKCT_DIR / "workflows"
    if workflows_dir.is_dir():
        for f in workflows_dir.iterdir():
            if f.is_file() and f.name != "reinit_protocol.md":
                f.unlink()
                print(f"[end] Deleted workflow: {f.name}")
        print("[end] Cleaned workflows/ (kept reinit_protocol.md)")

    for item_path in ROKCT_DIR.iterdir():
        if item_path.name in ("active_session.txt", "initiate.py"):
            print(f"[end] Kept {item_path.name} (protocol tool)")
            continue
        if item_path.name == ".sync_ready":
            continue
        if item_path.is_dir():
            continue
        core_key = f"core/templates/{item_path.name}"
        local_rel = f"profiles/local/{item_path.name}"
        if item_path.name == "profiles.md":
            local_rel = "profiles/local/rules.md"
        if file_hash(item_path) in (
            core_manifest.get("files", {}).get(core_key, {}).get("hash"),
            local_manifest.get("files", {}).get(local_rel, {}).get("hash"),
        ):
            item_path.unlink()
            print(f"[end] Deleted pristine {item_path.name}")
        else:
            print(f"[end] Kept modified {item_path.name}")

    touch(ROKCT_DIR / ".sync_ready")
    print("[end] Created .sync_ready marker — CI will pick this up when active session ends")
    print("[end] End protocol cleanup complete.")

if __name__ == "__main__":
    main()

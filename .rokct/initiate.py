# compliance-silent
import os
import sys
import shutil
import subprocess
import hashlib
import json
import urllib.request

import io
import zipfile

GITHUB_RAW_BASE = "https://raw.githubusercontent.com/RokctAI/The-Rokct-Protocol/main"
GITHUB_ZIP_BASE = "https://github.com/RokctAI/The-Rokct-Protocol/archive/refs/heads/main.zip"
PROTOCOL_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) if "profiles" in os.path.abspath(__file__) else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.getcwd()
ROKCT_DIR = os.path.join(PROJECT_ROOT, ".rokct")

def check_self_update():
    dest_initiate = os.path.join(ROKCT_DIR, "initiate.py")
    if os.path.exists(dest_initiate) and os.path.abspath(__file__) == os.path.abspath(dest_initiate):
        url = f"{GITHUB_RAW_BASE}/profiles/local/initiate.py"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req) as r:
                remote_data = r.read()
            remote_hash = hashlib.sha256(remote_data).hexdigest()[:16]
            if remote_hash != file_hash(dest_initiate):
                print("[init] GitHub has a newer initiate.py (local profile). Self-updating...")
                with open(dest_initiate, "wb") as f:
                    f.write(remote_data)
                print("[init] Reloading initiate.py...")
                os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception as e:
            print(f"[init] Self-update check failed: {e}", file=sys.stderr)

def fetch_from_github(rel_path, dest_path):
    url = f"{GITHUB_RAW_BASE}/{rel_path}"
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as r:
            with open(dest_path, "wb") as f:
                f.write(r.read())
        print(f"[init] Fetched {rel_path}")
    except Exception as e:
        print(f"[init] Failed to fetch {rel_path}: {e}", file=sys.stderr)
        sys.exit(1)

def ensure_file(rel_path, dest_path):
    src = os.path.join(PROTOCOL_DIR, rel_path)
    if os.path.exists(dest_path):
        if os.path.exists(src) and file_hash(src) == file_hash(dest_path):
            return
    if os.path.exists(src):
        shutil.copy2(src, dest_path)
        print(f"[init] Updated {rel_path}")
    else:
        fetch_from_github(rel_path, dest_path)

def file_hash(path):
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]

def copy_versioned(src_rel, dst_abs):
    src = os.path.join(PROTOCOL_DIR, src_rel)
    manifest_path = os.path.join(PROTOCOL_DIR, "core", "templates", "manifest.json")
    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as mf:
            manifest = json.load(mf)
    else:
        try:
            req = urllib.request.Request(f"{GITHUB_RAW_BASE}/core/templates/manifest.json", headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req) as r:
                manifest = json.loads(r.read().decode())
        except Exception:
            manifest = {}
    entry = manifest.get("files", {}).get(src_rel.split("core/templates/")[-1] if "core/templates/" in src_rel else src_rel.split("profiles/local/")[-1])
    if not entry or not os.path.exists(src):
        fetch_from_github(src_rel, dst_abs)
        return
    current_hash = file_hash(dst_abs)
    if current_hash and current_hash == entry.get("hash"):
        return
    shutil.copy2(src, dst_abs)

def copy_dir(rel_src, dst):
    src = os.path.join(PROTOCOL_DIR, rel_src)
    if not os.path.isdir(src):
        fetch_dir_from_github(rel_src, dst)
        return
    os.makedirs(dst, exist_ok=True)
    for item in os.listdir(src):
        # Skip sync files, maintenance, and the init guide - handled separately or not needed in .rokct
        if item in ("sync_workspace.py", "sync_workspace.yml", "maintenance.yml", "init_protocol.md", ".rok"):
            continue
        s = os.path.join(src, item)
        d = os.path.join(dst, item)
        if os.path.isdir(s):
            copy_dir(os.path.relpath(s, PROTOCOL_DIR), d)
        else:
            rel = os.path.relpath(s, PROTOCOL_DIR)
            ensure_file(rel, d)

def fetch_dir_from_github(rel_src, dst):
    prefix = f"The-Rokct-Protocol-main/{rel_src}/"
    try:
        print(f"[init] Fetching directory from GitHub: {rel_src}")
        req = urllib.request.Request(GITHUB_ZIP_BASE, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as r:
            z = zipfile.ZipFile(io.BytesIO(r.read()))
        os.makedirs(dst, exist_ok=True)
        count = 0
        for name in z.namelist():
            if name.startswith(prefix) and not name.endswith("/"):
                rel = name[len(prefix):]
                if rel_src == "workflows" and (rel in ("sync_workspace.py", "sync_workspace.yml", "maintenance.yml") or rel.startswith(".rok/")):
                    continue
                dest = os.path.join(dst, rel)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "wb") as f:
                    f.write(z.read(name))
                count += 1
        print(f"[init] Fetched {count} files from {rel_src}")
    except Exception as e:
        print(f"[init] Failed to fetch directory {rel_src}: {e}", file=sys.stderr)

def main():
    check_self_update()
    os.makedirs(ROKCT_DIR, exist_ok=True)

    templates = ["memory.md", "decision_log.md", "project_map.md", "active_session.txt"]
    for t in templates:
        dest_t = os.path.join(ROKCT_DIR, t)
        if not os.path.exists(dest_t):
            ensure_file(f"core/templates/{t}", dest_t)

    ensure_file(".cursorrules", os.path.join(PROJECT_ROOT, ".cursorrules"))

    copy_dir("core/skills", os.path.join(ROKCT_DIR, "skills"))
    try:
        origin_url = subprocess.check_output(["git", "config", "--get", "remote.origin.url"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        origin_url = ""
    if "RokctAI/" in origin_url:
        copy_dir("profiles/local/skills", os.path.join(ROKCT_DIR, "skills"))
        # For RokctAI repos, we already copied .rok via copy_dir("core/skills")
    else:
        # For non-RokctAI repos, remove .rok from skills
        rok_path = os.path.join(ROKCT_DIR, "skills", ".rok")
        if os.path.isdir(rok_path):
            shutil.rmtree(rok_path)
            print("[init] Removed .rok skill (non-RokctAI repo)")

    # Distribution of Protocol-only (RokctAI) workflows
    if "RokctAI/" in origin_url:
        rok_workflows_src = os.path.join(PROTOCOL_DIR, "workflows", ".rok")
        temp_rok_workflows = os.path.join(ROKCT_DIR, "workflows", ".rok")
        if not os.path.isdir(rok_workflows_src):
            fetch_dir_from_github("workflows/.rok", temp_rok_workflows)
            src_dir = temp_rok_workflows
        else:
            src_dir = rok_workflows_src

        if os.path.isdir(src_dir):
            dst_workflows = os.path.join(PROJECT_ROOT, ".github", "workflows")
            os.makedirs(dst_workflows, exist_ok=True)
            for item in os.listdir(src_dir):
                src_file = os.path.join(src_dir, item)
                if os.path.isfile(src_file):
                    shutil.copy2(src_file, os.path.join(dst_workflows, item))
                    print(f"[init] Deployed Protocol workflow: {item}")
            if src_dir == temp_rok_workflows and os.path.isdir(temp_rok_workflows):
                shutil.rmtree(temp_rok_workflows)
                print("[init] Cleaned up temporary workflows/.rok directory")

    ensure_file("profiles/local/rules.md", os.path.join(ROKCT_DIR, "profiles.md"))

    copy_dir("profiles/local/workflows", os.path.join(ROKCT_DIR, "workflows"))
    copy_dir("workflows", os.path.join(ROKCT_DIR, "workflows"))
    # Removed ensure_file("workflows/reinit_protocol.md", ...) as it was deleted and replaced by init_protocol.md


    try:
        email = subprocess.check_output(["git", "config", "user.email"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        email = ""
    if email:
        prefix = email.split("@")[0].replace(".", "").lower()
        domain = email.split("@")[1].lower()
        domain_hash = hashlib.md5(domain.encode()).hexdigest()[:6]
        safe_id = f"{prefix}.{domain_hash}"
        mem = os.path.join(ROKCT_DIR, "memory.md")
        existing_mem_content = ""
        if os.path.exists(mem):
            with open(mem, "r", encoding="utf-8") as f:
                existing_mem_content = f.read()
        if safe_id not in existing_mem_content:
            with open(mem, "a", encoding="utf-8") as f:
                f.write(f"\n\n## Safe ID\n{safe_id}\n")
            print(f"[init] Registered safe identity: {safe_id}")

    ignore = os.path.join(ROKCT_DIR, ".gitignore")
    if not os.path.exists(ignore):
        with open(ignore, "w", encoding="utf-8") as f:
            f.write("skills/\n")
        print("[init] Created .gitignore")
    else:
        txt = open(ignore, "r", encoding="utf-8").read()
        if "skills/" not in txt:
            with open(ignore, "a", encoding="utf-8") as f:
                f.write("skills/\n")
            print("[init] Updated .gitignore")

    ensure_file("workflows/sync_workspace.py", os.path.join(ROKCT_DIR, "sync_workspace.py"))
    ensure_file("workflows/sync_workspace.yml", os.path.join(PROJECT_ROOT, ".github", "workflows", "sync_workspace.yml"))
    ensure_file("profiles/local/end_protocol.py", os.path.join(ROKCT_DIR, "end_protocol.py"))
    # Don't copy initiate.py to itself if already running from .rokct/
    dest_initiate = os.path.join(ROKCT_DIR, "initiate.py")
    src_initiate = "profiles/local/initiate.py"
    if os.path.abspath(__file__) != dest_initiate:
        ensure_file(src_initiate, dest_initiate)
    print("[init] Copied initiate.py -> .rokct/initiate.py")
    
    cfg = os.path.join(ROKCT_DIR, ".workspace_config.json")
    if not os.path.exists(cfg):
        try:
            url = subprocess.check_output(["git", "config", "--get", "remote.origin.url"], text=True, stderr=subprocess.DEVNULL).strip()
        except Exception:
            url = ""
        if "RokctAI/" in url:
            parent = "RokctAI/occultation"
            print(f"[init] Auto-detected RokctAI repo, routing to {parent}")
        else:
            parent = input("[init] Enter parent workspace repo (owner/repo) or press Enter for standalone: ").strip()
        if parent:
            with open(cfg, "w", encoding="utf-8") as f:
                json.dump({"parent_repo": parent, "parent_branch": "main", "working_files": templates}, f, indent=2)
            print(f"[init] Created .workspace_config.json -> {parent}")
        else:
            print("[init] Standalone mode (no workspace sync)")
            # Only standalone or parent repos get the maintenance workflow (children don't need it)
            ensure_file("workflows/maintenance.yml", os.path.join(PROJECT_ROOT, ".github", "workflows", "maintenance.yml"))
            print("[init] Installed maintenance workflow for parent/standalone repo")
    else:
        # If config already exists, check if it's a parent (no parent_repo set)
        with open(cfg, "r", encoding="utf-8") as f:
            config_data = json.load(f)
            if not config_data.get("parent_repo"):
                ensure_file("workflows/maintenance.yml", os.path.join(PROJECT_ROOT, ".github", "workflows", "maintenance.yml"))
                print("[init] Verified maintenance workflow for parent/standalone repo")


    print("[init] Local profile init complete.")

if __name__ == "__main__":
    main()



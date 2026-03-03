import os
import re
import subprocess
import sys

def fix_workflow_permissions(content):
    if '# rokct-ignore' in content: return content
    
    # In open-source context, write-all is the most compatible way to 
    # request all permissions enabled in the repository settings.
    if 'permissions:' not in content:
        perms_block = '\npermissions: write-all\n'
        # Insert after the name: line at the top to be safe
        if 'name:' in content:
            content = re.sub(r'^(name:.*?\n)', r'\1' + perms_block, content)
        else:
            content = perms_block + content
    elif 'permissions: write-all' not in content:
        # If there's already a complex block, we don't force write-all to avoid breaking custom setups
        pass
    return content

def fix_workflow_triggers(content, file_name):
    if '# rokct-ignore' in content: return content
    
    # We want to ensure linter.yml has schedule and workflow_dispatch
    if file_name == "linter.yml":
        if 'schedule:' not in content or 'workflow_dispatch:' not in content:
            # Case 1: Short [push, pull_request] format
            if re.search(r'on:\s*\[.*?\]', content):
                content = re.sub(r'on:\s*\[(.*?)\]', r'on:\n  push:\n  pull_request:\n  schedule:\n    - cron: "0 0 * * *"\n  workflow_dispatch:', content)
            elif 'on:' in content:
                # Case 2: Structured 'on:' - add missing ones once
                new_triggers = ""
                if 'workflow_dispatch:' not in content:
                    new_triggers += "  workflow_dispatch:\n"
                if 'schedule:' not in content:
                    new_triggers += "  schedule:\n    - cron: \"0 0 * * *\"\n"
                
                if new_triggers:
                    content = re.sub(r'(on:.*?\n)', r'\1' + new_triggers, content)
    return content

def fix_workflow_inputs(content):
    if '# rokct-ignore' in content: return content
    
    # 1. workflow_dispatch inputs (additive only)
    if 'workflow_dispatch:' in content and 'backfill_ai_notes_cutoff_version:' not in content:
        input_block = """      backfill_ai_notes_cutoff_version:
        type: string
        default: ""
        description: "Regenerate AI release notes starting from this version (use 'all' for full history)"
"""
        # More robust regex to find the inputs: line under workflow_dispatch
        match = re.search(r'(workflow_dispatch:.*?\n\s+inputs:)', content, re.DOTALL)
        if match:
            content = content.replace(match.group(1), match.group(1) + "\n" + input_block)
        else:
            # Fallback for when inputs: is missing
            content = content.replace('workflow_dispatch:', 'workflow_dispatch:\n    inputs:\n' + input_block)

    # 2. universal-pipeline mapping (additive only)
    if 'uses: RokctAI/shared-workflows/.github/workflows/universal-pipeline.yml' in content:
        if 'backfill_ai_notes_cutoff_version: ${{ inputs.backfill_ai_notes_cutoff_version }}' not in content:
            # Look for with: block following the uses line
            pattern = r'(uses: RokctAI/shared-workflows/\.github/workflows/universal-pipeline\.yml.*?with:)'
            match = re.search(pattern, content, re.DOTALL)
            if match:
                content = content.replace(match.group(1), match.group(1) + "\n      backfill_ai_notes_cutoff_version: ${{ inputs.backfill_ai_notes_cutoff_version }}")
    
    return content

def fix_merge_workflow(content):
    if '# rokct-ignore' in content: return content
    
    # Get bot name from env or default to rokctbot
    # This allows external devs to use their own app name
    main_bot = os.environ.get('BOT_NAME', 'rokctbot')
    bot_variants = [main_bot, f"{main_bot}[bot]"]
    
    # Ensure bots are in the allowed_users list
    match = re.search(r'allowed_users:\s*[\'"](.*?)[\'"]', content)
    if match:
        raw_allowed = match.group(1)
        allowed = [u.strip() for u in raw_allowed.split(',')]
        
        needs_update = False
        for bot in bot_variants:
            if bot not in allowed:
                allowed.append(bot)
                needs_update = True
        
        if needs_update:
            new_allowed = ", ".join(allowed)
            content = content.replace(match.group(0), f"allowed_users: '{new_allowed}'")
            
    return content

def fix_release_strategy(workflow_dir):
    """Ensure release_strategy is aligned between build.yml and release.yml.
    release.yml is the canonical source. If both exist and differ, align build.yml to release.yml.
    If only build.yml exists, enforce 'weekly' as the fleet default."""
    build_path = os.path.join(workflow_dir, "build.yml")
    release_path = os.path.join(workflow_dir, "release.yml")

    if not os.path.exists(build_path):
        return None  # Nothing to fix

    with open(build_path, 'r', encoding='utf-8') as f:
        build_content = f.read()

    if '# rokct-ignore' in build_content:
        return None

    # Determine the canonical strategy
    canonical = 'weekly'  # Fleet default
    if os.path.exists(release_path):
        with open(release_path, 'r', encoding='utf-8') as f:
            release_content = f.read()
        match = re.search(r"release_strategy:\s*['\"]?(\w+)['\"]?", release_content)
        if match:
            canonical = match.group(1)

    # Check build.yml's current strategy
    match = re.search(r"release_strategy:\s*['\"]?(\w+)['\"]?", build_content)
    if match and match.group(1) != canonical:
        new_content = build_content.replace(match.group(0), f"release_strategy: '{canonical}'")
        return new_content

    return None

def fix_release_push_dedup(workflow_dir):
    """When both build.yml and release.yml exist, remove push triggers from release.yml.
    build.yml handles pushes (CI on every commit). release.yml handles weekly cron + manual dispatch.
    Having push in both causes duplicate CI runs."""
    build_path = os.path.join(workflow_dir, "build.yml")
    release_path = os.path.join(workflow_dir, "release.yml")

    if not os.path.exists(build_path) or not os.path.exists(release_path):
        return None

    with open(release_path, 'r', encoding='utf-8') as f:
        content = f.read()

    if '# rokct-ignore' in content:
        return None

    # Remove push: branches: [main, develop] block from release.yml
    # Match the push block with its branches sub-key
    new_content = re.sub(
        r'\n\s*push:\s*\n\s*branches:\s*\[.*?\]\s*\n',
        '\n',
        content
    )

    if new_content != content:
        return new_content
    return None


def fix_dependabot(path, check_only=False):
    if not os.path.exists(path): return False
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    if '# rokct-ignore' in content: return False
    
    # Only standardise if it's explicitly weekly or daily and lacks a keep flag
    new_content = re.sub(r'interval:\s*["\']?(weekly|daily)["\']?\s*(?!# rokct-keep)', 'interval: "monthly"', content)
    if new_content != content:
        if not check_only:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(new_content)
        return True
    return False

def sync_submodules(check_only=False):
    if os.path.exists('.gitmodules'):
        if check_only:
            # In check mode we just see if submodules are out of sync without updating
            # This is complex to do accurately without network, so we skip check for now
            return False

        with open('.gitmodules', 'r') as f:
            modules = f.read()
            
        if 'The-Rokct-Protocol' in modules:
            print("📦 Syncing The-Rokct-Protocol...")
            try:
                subprocess.run(['git', 'submodule', 'update', '--remote', '--merge', 'The-Rokct-Protocol'], check=True)
                return True
            except Exception as e:
                print(f"❌ Submodule sync failed: {e}")
    return False

def main():
    check_only = "--check" in sys.argv
    changed = False
    
    # Fix Workflows
    workflow_dir = ".github/workflows"
    if os.path.exists(workflow_dir):
        # Scan for standard and custom workflows
        for file in ["build.yml", "release.yml", "merge.yml", "linter.yml"]:
            path = os.path.join(workflow_dir, file)
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                new_content = fix_workflow_permissions(content)
                new_content = fix_workflow_inputs(new_content)
                new_content = fix_workflow_triggers(new_content, file)
                
                if file == "merge.yml":
                    new_content = fix_merge_workflow(new_content)
                
                if new_content != content:
                    if not check_only:
                        with open(path, 'w', encoding='utf-8') as f:
                            f.write(new_content)
                        print(f"✅ Updated {path}")
                    else:
                        print(f"⚠️ {path} needs standardization")
                    changed = True

        # Align release_strategy between build.yml and release.yml
        updated_build = fix_release_strategy(workflow_dir)
        if updated_build is not None:
            build_path = os.path.join(workflow_dir, "build.yml")
            if not check_only:
                with open(build_path, 'w', encoding='utf-8') as f:
                    f.write(updated_build)
                print(f"✅ Aligned release_strategy in build.yml")
            else:
                print(f"⚠️ build.yml release_strategy is misaligned")
            changed = True

        # Remove push triggers from release.yml when build.yml exists
        updated_release = fix_release_push_dedup(workflow_dir)
        if updated_release is not None:
            release_path = os.path.join(workflow_dir, "release.yml")
            if not check_only:
                with open(release_path, 'w', encoding='utf-8') as f:
                    f.write(updated_release)
                print(f"✅ Removed push trigger from release.yml (build.yml handles pushes)")
            else:
                print(f"⚠️ release.yml has duplicate push trigger")
            changed = True

    # Fix Dependabot
    if fix_dependabot(".github/dependabot.yml", check_only):
        if not check_only:
            print("✅ Updated .github/dependabot.yml")
        else:
            print("⚠️ .github/dependabot.yml needs standardization")
        changed = True

    # Sync Submodules
    if sync_submodules(check_only):
        if not check_only:
            print("✅ Submodules synced")
        changed = True

    if changed:
        if check_only:
            print("❌ Repository is NOT standardized.")
            sys.exit(1)
        else:
            print("🛠️ Repository standardization complete.")
    else:
        print("🙌 Repository is already standardized.")

if __name__ == "__main__":
    main()

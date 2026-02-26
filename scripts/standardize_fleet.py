import os
import re
import subprocess

def fix_workflow_permissions(content):
    if '# rokct-ignore' in content: return content
    
    required = ['contents: write', 'issues: write', 'pull-requests: write', 'workflows: write']
    
    if 'permissions:' not in content:
        # Use simple string insertion after name/concurrency
        perms_block = 'permissions:\n' + '\n'.join(f'  {p}' for p in required) + '\n'
        if 'concurrency:' in content:
            content = re.sub(r'(concurrency:.*?\n)', r'\1' + perms_block, content, flags=re.DOTALL)
        else:
            content = re.sub(r'^(name:.*?\n)', r'\1' + perms_block, content)
    else:
        for perm in required:
            key = perm.split(':')[0]
            # Precise matching for the key at the start of a line inside a permissions block is hard with regex,
            # so we use a simpler check that respects the yaml structure.
            if f'{key}:' not in content:
                content = content.replace('permissions:', f'permissions:\n  {perm}')
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

def fix_dependabot(path):
    if not os.path.exists(path): return False
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    if '# rokct-ignore' in content: return False
    
    # Only standardise if it's explicitly weekly or daily and lacks a keep flag
    # Pattern looks for interval followed by weekly/daily, ensuring it's not already monthly
    # and doesn't have a comment like # rokct-keep on the same line
    new_content = re.sub(r'interval:\s*["\']?(weekly|daily)["\']?\s*(?!# rokct-keep)', 'interval: "monthly"', content)
    if new_content != content:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        return True
    return False

def sync_submodules():
    if os.path.exists('.gitmodules'):
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
    changed = False
    
    # Fix Workflows
    workflow_dir = ".github/workflows"
    if os.path.exists(workflow_dir):
        for file in ["build.yml", "release.yml"]:
            path = os.path.join(workflow_dir, file)
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                new_content = fix_workflow_permissions(content)
                new_content = fix_workflow_inputs(new_content)
                
                if new_content != content:
                    with open(path, 'w', encoding='utf-8') as f:
                        f.write(new_content)
                    print(f"✅ Updated {path}")
                    changed = True

    # Fix Dependabot
    if fix_dependabot(".github/dependabot.yml"):
        print("✅ Updated .github/dependabot.yml")
        changed = True

    # Sync Submodules
    if sync_submodules():
        print("✅ Submodules synced")
        changed = True

    if not changed:
        print("🙌 Repository is already standardized.")

if __name__ == "__main__":
    main()

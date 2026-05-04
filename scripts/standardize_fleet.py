# Copyright (c) 2024, Rokct Intelligence (pty) Ltd.
# For license information, please see license.txt

import os
import re
import subprocess
import sys


def fix_workflow_permissions(content):
    if "# rokct-ignore" in content:
        return content

    # 1. Force top-level permissions to write-all
    if re.search(r"^permissions:", content, re.MULTILINE):
        # Replace existing top-level permissions block
        content = re.sub(
            r"^permissions:.*?(?=\n\S|\Z)",
            "permissions: write-all",
            content,
            flags=re.MULTILINE | re.DOTALL,
        )
    else:
        # Inject top-level permissions: write-all
        perms_block = "permissions: write-all\n"
        if "name:" in content:
            content = re.sub(
                r"^(name:.*?\n)", r"\1" + perms_block + "\n", content, count=1
            )
        else:
            content = perms_block + "\n" + content

    # 2. Force job-level permissions to write-all if they exist
    # Matches lines starting with whitespace followed by permissions:
    # We use a non-greedy match that stops at the next line with the same or less indentation.
    def job_perms_repl(match):
        indent = match.group(1)
        return f"{indent}permissions: write-all"

    content = re.sub(
        r"^([ \t]+)permissions:.*?(?=\n\1\S|\n\S|\Z)",
        job_perms_repl,
        content,
        flags=re.MULTILINE | re.DOTALL,
    )

    return content


def fix_workflow_triggers(content, file_name):
    if "# rokct-ignore" in content:
        return content

    # We want to ensure linter.yml has schedule and workflow_dispatch
    if file_name == "linter.yml":
        if "schedule:" not in content or "workflow_dispatch:" not in content:
            # Case 1: Short [push, pull_request] format
            if re.search(r"on:\s*\[.*?\]", content):
                content = re.sub(
                    r"on:\s*\[(.*?)\]",
                    r'on:\n  push:\n  pull_request:\n  schedule:\n    - cron: "0 0 * * *"\n  workflow_dispatch:',
                    content,
                )
            elif "on:" in content:
                # Case 2: Structured 'on:' - add missing ones once
                new_triggers = ""
                if "workflow_dispatch:" not in content:
                    new_triggers += "  workflow_dispatch:\n"
                if "schedule:" not in content:
                    new_triggers += '  schedule:\n    - cron: "0 0 * * *"\n'

                if new_triggers:
                    content = re.sub(r"(on:.*?\n)", r"\1" + new_triggers, content)
    return content


def fix_workflow_inputs(content):
    if "# rokct-ignore" in content:
        return content

    # 0. Ensure MONOREPO_PAT is in secrets if we are fetching env or google-services
    if "production.env" in content or "google-services.json" in content or "GoogleService-Info.plist" in content:
        if "MONOREPO_PAT:" not in content:
            # Inject into secrets block
            if "secrets:" in content:
                content = re.sub(
                    r"(secrets:.*?\n)",
                    r"\1      MONOREPO_PAT:\n        required: false\n",
                    content,
                    count=1,
                    flags=re.DOTALL,
                )

    # 1. workflow_dispatch inputs (additive only)
    if "workflow_dispatch:" in content:
        # backfill_ai_notes_cutoff_version
        if "backfill_ai_notes_cutoff_version:" not in content:
            input_block = """      backfill_ai_notes_cutoff_version:
        type: string
        default: ""
        description: "Regenerate AI release notes starting from this version (use 'all' for full history)"
"""
            match = re.search(r"(workflow_dispatch:.*?\n\s+inputs:)", content, re.DOTALL)
            if match:
                content = content.replace(match.group(1), match.group(1) + "\n" + input_block)
            else:
                content = content.replace(
                    "workflow_dispatch:", "workflow_dispatch:\n    inputs:\n" + input_block
                )

        # run_verify
        if "run_verify:" not in content:
            input_block = """      run_verify:
        type: boolean
        default: true
        description: "Run continuous verification on Android emulator"
"""
            match = re.search(r"(workflow_dispatch:.*?\n\s+inputs:)", content, re.DOTALL)
            if match:
                content = content.replace(match.group(1), match.group(1) + "\n" + input_block)
            else:
                content = content.replace(
                    "workflow_dispatch:", "workflow_dispatch:\n    inputs:\n" + input_block
                )

    # 2. universal-pipeline mapping (additive only)
    if "uses: RokctAI/shared-workflows/.github/workflows/universal-pipeline.yml" in content:
        # backfill_ai_notes_cutoff_version
        if (
            "backfill_ai_notes_cutoff_version: ${{ inputs.backfill_ai_notes_cutoff_version }}"
            not in content
        ):
            # Look for with: block following the uses line
            pattern = r"(uses: RokctAI/shared-workflows/\.github/workflows/universal-pipeline\.yml.*?with:)"
            match = re.search(pattern, content, re.DOTALL)
            if match:
                content = content.replace(
                    match.group(1),
                    match.group(1)
                    + "\n      backfill_ai_notes_cutoff_version: ${{ inputs.backfill_ai_notes_cutoff_version }}",
                )

        # run_verify
        if "run_verify: ${{ inputs.run_verify" not in content:
            pattern = r"(uses: RokctAI/shared-workflows/\.github/workflows/universal-pipeline\.yml.*?with:)"
            match = re.search(pattern, content, re.DOTALL)
            if match:
                content = content.replace(
                    match.group(1),
                    match.group(1)
                    + "\n      run_verify: ${{ inputs.run_verify != false }}",
                )

    return content


def fix_bot_identity(content):
    if "# rokct-ignore" in content:
        return content

    # Get bot name from env or default to RokctBOT
    main_bot = os.environ.get("BOT_NAME", "RokctBOT")

    if main_bot != "RokctBOT":
        return content

    # 1. Update specific bot emails if found (do this before global rename)
    content = content.replace(
        "2956274+rokctbot[bot]@users.noreply.github.com",
        "rokctbot[bot]@users.noreply.github.com",
    )

    # 2. Global rename of legacy bot to new bot identity
    # We target both 'rokctbot' and 'rokctbot[bot]'
    content = re.sub(r"\bROK\[bot\]", "RokctBOT[bot]", content)
    content = re.sub(r"\bROK\b", "RokctBOT", content)
    content = re.sub(r"\brokct-maintainer\[bot\]", "RokctBOT[bot]", content)
    content = re.sub(r"\brokct-maintainer\b", "RokctBOT", content)

    return content


def fix_git_identity(content):
    """Ensure any workflow job that runs git commit sets --global identity
    immediately after its first checkout step. This prevents 'Author identity
    unknown' failures in scripts that commit (linters, healers, sync jobs)."""
    if "# rokct-ignore" in content:
        return content

    # Only touch workflows that actually commit
    if "git commit" not in content and "git push" not in content:
        return content

    BOT_NAME = os.environ.get("BOT_NAME", "RokctBOT")
    BOT_EMAIL_PREFIX = os.environ.get("BOT_EMAIL_PREFIX", "2956274")
    BOT_EMAIL = f"{BOT_EMAIL_PREFIX}+{BOT_NAME}[bot]@users.noreply.github.com"

    IDENTITY_STEP = (
        "\n      - name: Setup Bot Identity\n"
        "        run: |\n"
        f'          git config --global user.name "{BOT_NAME}[bot]"\n'
        f'          git config --global user.email "{BOT_EMAIL}"\n'
    )

    IDENTITY_MARKER = "git config --global user.name"

    # Already has identity setup — skip
    if IDENTITY_MARKER in content:
        return content

    # Insert after the first `actions/checkout` step block
    # Match the checkout step and inject our identity step immediately after
    pattern = r"(- name:.*?uses: actions/checkout@[^\n]+(?:\n[ \t]+[^\n]+)*)"
    match = re.search(pattern, content)
    if match:
        insert_after = match.end()
        content = content[:insert_after] + IDENTITY_STEP + content[insert_after:]

    return content


def fix_merge_workflow(content):
    if "# rokct-ignore" in content:
        return content

    # Get bot name from env or default to RokctBOT
    # This allows external devs to use their own app name
    main_bot = os.environ.get("BOT_NAME", "RokctBOT")
    bot_variants = [main_bot, f"{main_bot}[bot]"]

    # Ensure bots are in the allowed_users list
    match = re.search(r'allowed_users:\s*[\'"](.*?)[\'"]', content)
    if match:
        raw_allowed = match.group(1)
        # Split, strip, and filter out 'ROK' variants if we are migrating to 'rokct-maintainer'
        allowed = [u.strip() for u in raw_allowed.split(",")]

        if main_bot == "RokctBOT":
            # Remove legacy bot entries to keep it clean
            allowed = [u for u in allowed if u not in ["ROK", "RokctBOT[bot]"]]

        needs_update = False
        for bot in bot_variants:
            if bot not in allowed:
                allowed.append(bot)
                needs_update = True

        # Unique entries only
        allowed = sorted(list(set(allowed)))

        if needs_update or main_bot == "ROK":
            new_allowed = ", ".join(allowed)
            content = content.replace(match.group(0), f'allowed_users: "{new_allowed}"')
    return content


def fix_action_versions(content):
    if "# rokct-ignore" in content:
        return content

    # Mapping of actions to their Node 24-compatible major versions as of April 2026
    updates = {
        r"actions/checkout@v[0-5]": "actions/checkout@v6",
        r"actions/create-github-app-token@v[1-2]": "actions/create-github-app-token@v3",
        r"actions/github-script@v[0-7]": "actions/github-script@v8",
        r"actions/setup-node@v[0-5]": "actions/setup-node@v6",
        r"actions/setup-python@v[0-5]": "actions/setup-python@v6",
        r"actions/upload-artifact@v[0-5]": "actions/upload-artifact@v6",
        r"actions/download-artifact@v[0-5]": "actions/download-artifact@v6",
        r"actions/setup-java@v[0-4]": "actions/setup-java@v5",
        r"actions/stale@v[0-9]+": "actions/stale@v9",
        r"actions/first-interaction@v1": "actions/first-interaction@v2",
    }

    for pattern, replacement in updates.items():
        content = re.sub(pattern, replacement, content)

    return content


def fix_workflow_node_version(content):
    if "# rokct-ignore" in content:
        return content

    # 1. Bump node-version to 24
    # Handles: node-version: 20, node-version: '18', node-version: "16", node-version: [20], etc.
    content = re.sub(
        r"node-version:\s*([\'\"]?(?:1[0-9]|2[0-3])[\'\"]?|\[\s*[\'\" ]?(?:1[0-9]|2[0-3])[\'\" ]?\s*\])",
        "node-version: 24",
        content,
    )

    # 2. Inject FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true
    if "FORCE_JAVASCRIPT_ACTIONS_TO_NODE24" not in content:
        env_line = "  FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true"

        # Check if env: block already exists at top level (no leading whitespace)
        if re.search(r"^env:", content, re.MULTILINE):
            # Append to existing env: block. We look for the env: line and insert after it.
            content = re.sub(
                r"(^env:.*?\n)",
                r"\1" + env_line + "\n",
                content,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            # Create env: block
            env_block = f"env:\n{env_line}\n"

            # Insert after name: line (safest place for top-level env)
            if re.search(r"^name:", content, re.MULTILINE):
                content = re.sub(
                    r"(^name:.*?\n)",
                    r"\1\n" + env_block,
                    content,
                    flags=re.MULTILINE,
                    count=1,
                )
            else:
                # Fallback to top of file
                content = env_block + "\n" + content

    return content


def fix_release_strategy(workflow_dir):
    """Ensure release_strategy is aligned between build.yml and release.yml.
    release.yml is the canonical source. If both exist and differ, align build.yml to release.yml.
    If only build.yml exists, enforce 'weekly' as the fleet default."""
    build_path = os.path.join(workflow_dir, "build.yml")
    release_path = os.path.join(workflow_dir, "release.yml")

    if not os.path.exists(build_path):
        return None  # Nothing to fix

    with open(build_path, "r", encoding="utf-8") as f:
        build_content = f.read()

    if "# rokct-ignore" in build_content:
        return None

    # Determine the canonical strategy
    canonical = "weekly"  # Fleet default
    if os.path.exists(release_path):
        with open(release_path, "r", encoding="utf-8") as f:
            release_content = f.read()
        match = re.search(r"release_strategy:\s*['\"]?(\w+)['\"]?", release_content)
        if match:
            canonical = match.group(1)

    # Check build.yml's current strategy
    match = re.search(r"release_strategy:\s*['\"]?(\w+)['\"]?", build_content)
    if match and match.group(1) != canonical:
        new_content = build_content.replace(
            match.group(0), f"release_strategy: '{canonical}'"
        )
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

    with open(release_path, "r", encoding="utf-8") as f:
        content = f.read()

    if "# rokct-ignore" in content:
        return None

    # Remove push: branches: [main, develop] block from release.yml
    # Match the push block with its branches sub-key
    new_content = re.sub(r"\n\s*push:\s*\n\s*branches:\s*\[.*?\]\s*\n", "\n", content)

    if new_content != content:
        return new_content
    return None


def fix_dependabot(path, check_only=False):
    if not os.path.exists(path):
        return False
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    if "# rokct-ignore" in content:
        return False

    # Only standardise if it's explicitly weekly or daily and lacks a keep flag
    new_content = re.sub(
        r'interval:\s*["\']?(weekly|daily)["\']?\s*(?!# rokct-keep)',
        'interval: "monthly"',
        content,
    )
    if new_content != content:
        if not check_only:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
        return True
    return False


def sync_submodules(check_only=False):
    if os.path.exists(".gitmodules"):
        if check_only:
            # In check mode we just see if submodules are out of sync without updating
            # This is complex to do accurately without network, so we skip check for now
            return False

        with open(".gitmodules", "r") as f:
            modules = f.read()

        if "The-Rokct-Protocol" in modules:
            print("📦 Syncing The-Rokct-Protocol...")
            try:
                subprocess.run(
                    [
                        "git",
                        "submodule",
                        "update",
                        "--remote",
                        "--merge",
                        "The-Rokct-Protocol",
                    ],
                    check=True,
                )
                return True
            except Exception as e:
                print(f"❌ Submodule sync failed: {e}")
    return False


def fix_monorepo_secrets(content):
    if "# rokct-ignore" in content:
        return content

    # 1. Inject Monorepo fetch into Node CI if it's missing (legacy secret-only mode)
    if "universal-node-ci.yml" in content or "package.json" in content:
        if "gh api /repos/RokctAI/Monorepo/contents/.env/" not in content:
            # We look for the step that decodes the production environment
            pattern = r"(- name: Decode Production Environment.*?run: \|.*?\n)(.*?)(?=\n\s*- name:|\Z)"
            def repl(m):
                header = m.group(1)
                indent = re.match(r"^(\s*)", m.group(2)).group(1) if m.group(2).strip() else "          "
                new_step = f"""{header}{indent}FILE_NAME="production.env"
{indent}# 1. Try Monorepo
{indent}if [ ! -z "$GH_TOKEN" ] && gh api /repos/RokctAI/Monorepo/contents/.env/$FILE_NAME -H "Accept: application/vnd.github.v3.raw" > .env.raw 2>/dev/null; then
{indent}   echo "✅ Successfully synced $FILE_NAME from Monorepo."
{indent}else
{indent}   # 2. Try Secrets Fallback...
"""
                return new_step

            # This is a bit risky to do via regex on every repo's custom workflow,
            # so we only do it if we are sure it's the standard RokctAI pattern.
            if "secrets.PRODUCTION_ENV" in content:
                # We don't actually modify the content here yet,
                # we prefer to let the universal workflows themselves handle the logic
                # and just ensure they HAVE the secrets passed.
                pass

    return content


def fix_android_debug_buildtype(check_only=False):
    """Ensure android/app/build.gradle has an explicit debug buildType.
    Without it, debug builds in CI fall back to Gradle defaults which can
    fail due to missing signing config or inherited release config."""
    gradle_path = "android/app/build.gradle"

    if not os.path.exists(gradle_path):
        return False

    with open(gradle_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Already has a debug block — nothing to do
    if re.search(r"buildTypes\s*\{[^}]*\bdebug\s*\{", content, re.DOTALL):
        return False

    debug_block = (
        "\n        debug {\n"
        "            signingConfig signingConfigs.debug\n"
        "            minifyEnabled false\n"
        "            debuggable true\n"
        "        }\n"
    )

    new_content = re.sub(
        r"(buildTypes\s*\{)",
        r"\1" + debug_block,
        content,
        count=1,
    )

    if new_content == content:
        return False

    if not check_only:
        with open(gradle_path, "w", encoding="utf-8") as f:
            f.write(new_content)

    return True


def fix_android_gradle_properties(check_only=False):
    """Ensure android/gradle.properties has a sensible baseline JVM heap.
    Debug builds process large Flutter engine JARs via JetifyTransform and
    will OOM on Gradle's default heap. The workflow retry logic will bump
    further if needed, but a 4g baseline avoids the first OOM entirely."""
    if not os.path.exists("android"):
        return False

    props_path = "android/gradle.properties"

    baseline = "org.gradle.jvmargs=-Xmx4g -XX:MaxMetaspaceSize=512m -XX:+HeapDumpOnOutOfMemoryError"

    if not os.path.exists(props_path):
        if not check_only:
            os.makedirs("android", exist_ok=True)
            with open(props_path, "w", encoding="utf-8") as f:
                f.write(baseline + "\n")
        return True

    with open(props_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Already has a jvmargs line — check if heap is at least 4g
    match = re.search(r"org\.gradle\.jvmargs=.*-Xmx(\d+)([gGmM])", content)
    if match:
        value, unit = int(match.group(1)), match.group(2).lower()
        heap_mb = value * 1024 if unit == "g" else value
        if heap_mb >= 4096:
            return False  # Already sufficient
        # Heap is set but too low — replace the whole jvmargs line
        new_content = re.sub(
            r"org\.gradle\.jvmargs=.*",
            baseline,
            content,
        )
    elif "org.gradle.jvmargs" in content:
        # Has jvmargs but no -Xmx — replace it
        new_content = re.sub(
            r"org\.gradle\.jvmargs=.*",
            baseline,
            content,
        )
    else:
        # No jvmargs at all — append
        new_content = content.rstrip() + "\n" + baseline + "\n"

    if new_content == content:
        return False

    if not check_only:
        with open(props_path, "w", encoding="utf-8") as f:
            f.write(new_content)

    return True


def main():
    check_only = "--check" in sys.argv
    changed = False

    # Fix Workflows & Actions
    # We scan .github/workflows, examples/workflows and .github/actions
    target_dirs = [".github/workflows", "examples/workflows"]
    action_dirs = [".github/actions"]

    for workflow_dir in target_dirs:
        if os.path.exists(workflow_dir):
            # Scan ALL workflows in the directory for standardization
            for file in os.listdir(workflow_dir):
                if not file.endswith(".yml"):
                    continue

                path = os.path.join(workflow_dir, file)
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()

                new_content = fix_workflow_permissions(content)
                new_content = fix_workflow_node_version(new_content)
                new_content = fix_workflow_inputs(new_content)
                new_content = fix_monorepo_secrets(new_content)
                new_content = fix_workflow_triggers(new_content, file)
                new_content = fix_bot_identity(new_content)
                new_content = fix_git_identity(new_content)
                new_content = fix_action_versions(new_content)

                if file == "merge.yml":
                    new_content = fix_merge_workflow(new_content)

                if new_content != content:
                    if not check_only:
                        with open(path, "w", encoding="utf-8") as f:
                            f.write(new_content)
                        print(f"✅ Updated {path}")
                    else:
                        print(f"⚠️ {path} needs standardization")
                    changed = True

    # Secondary fixes (alignment between files)
    for workflow_dir in target_dirs:
        if os.path.exists(workflow_dir):
            # Align release_strategy between build.yml and release.yml
            updated_build = fix_release_strategy(workflow_dir)
            if updated_build is not None:
                build_path = os.path.join(workflow_dir, "build.yml")
                if not check_only:
                    with open(build_path, "w", encoding="utf-8") as f:
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
                    with open(release_path, "w", encoding="utf-8") as f:
                        f.write(updated_release)
                    print(
                        f"✅ Removed push trigger from release.yml (build.yml handles pushes)"
                    )
                else:
                    print(f"⚠️ release.yml has duplicate push trigger")
                changed = True

    # Fix Actions
    for action_dir in action_dirs:
        if os.path.exists(action_dir):
            for root, _, files in os.walk(action_dir):
                for file in files:
                    if file.endswith((".yml", ".yaml")):
                        path = os.path.join(root, file)
                        with open(path, "r", encoding="utf-8") as f:
                            content = f.read()

                        new_content = fix_bot_identity(content)

                        if new_content != content:
                            if not check_only:
                                with open(path, "w", encoding="utf-8") as f:
                                    f.write(new_content)
                                print(f"✅ Updated {path} bot identity")
                            else:
                                print(f"⚠️ {path} needs bot identity standardization")
                            changed = True

    # Fix Android debug buildType
    if fix_android_debug_buildtype(check_only):
        if not check_only:
            print("✅ Added debug buildType to android/app/build.gradle")
        else:
            print("⚠️ android/app/build.gradle missing debug buildType")
        changed = True

    # Fix Android Gradle JVM heap
    if fix_android_gradle_properties(check_only):
        if not check_only:
            print("✅ Set baseline JVM heap in android/gradle.properties")
        else:
            print("⚠️ android/gradle.properties missing or insufficient JVM heap")
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
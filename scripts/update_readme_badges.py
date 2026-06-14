# Copyright (c) 2024, Rokct Intelligence (pty) Ltd.
# For license information, please see license.txt

import json
import os
import re
import subprocess
import sys
import urllib.request

STATE_FILE = ".usage_state.json"


def format_count(n):
    if n >= 1_000_000:
        # e.g., 1.2M
        val = f"{n/1_000_000:.1f}M".replace(".0", "")
    elif n >= 1_000:
        # e.g., 5k, 10k
        val = f"{n // 1000}k"
    else:
        val = str(n)

    if n >= 5000:
        val = f"^{val}"
    return val


def get_current_count():
    try:
        req = urllib.request.Request(
            "https://api.counterapi.dev/v2/rokctai/usage/stats",
            headers={
                "User-Agent": "Mozilla/5.0",
                "x-trace-id": "gh-badges-run"
            },
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            return data.get("data", {}).get("up_count", 0)
    except Exception as e:
        print(f"⚠️ Failed to fetch usage stats: {e}")
        return None


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def fix_usage_badge(path, check_only=False):
    if not os.path.exists(path):
        return False

    count = get_current_count()
    if count is None:
        return False

    state = load_state()
    last_bucket = state.get("last_thousand_bucket", 0)
    current_bucket = count // 1000

    # Only update if the bucket has increased
    if current_bucket <= last_bucket and last_bucket != 0:
        # Check if README actually has the right content
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        formatted_value = format_count(count)
        if f"Total%20Builds-{formatted_value}-blue" in content or f"Total%20Builds-{formatted_value.replace('^', '%5E')}-blue" in content:
             return False

    formatted_value = format_count(count)
    new_badge = f"![Total Builds](https://img.shields.io/badge/Total%20Builds-{formatted_value}-blue)"

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    if "usage-badge-start" not in content:
        return False

    # Replace the badge within the <!-- usage-badge-start --> block
    pattern = r"(!\[Total Builds\]\(.*?\))"
    new_content = re.sub(pattern, new_badge, content, count=1)

    if new_content != content:
        if not check_only:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
            state["last_thousand_bucket"] = current_bucket
            state["last_count"] = count
            save_state(state)
        return True
    return False


def fix_candidate_badge(path, check_only=False):
    if not os.path.exists(path):
        return False

    latest_rc = None
    try:
        # Get latest tag containing -rc
        cmd = ["git", "tag", "-l", "*-rc*", "--sort=-v:refname"]
        tags = subprocess.check_output(cmd).decode().splitlines()
        if tags:
            latest_rc = tags[0]
    except Exception as e:
        print(f"⚠️ Failed to fetch candidate tag: {e}")

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    if "usage-badge-start" not in content:
        return False

    new_content = content
    candidate_pattern = r"\s*!\[Candidate\]\(.*?\)\n?"

    if latest_rc:
        # Update or Insert
        formatted_rc = latest_rc.replace("-", "--")
        new_badge = f"![Candidate](https://img.shields.io/badge/Candidate-{formatted_rc}-e67e22)"

        if "![Candidate]" in content:
            new_content = re.sub(r"!\[Candidate\]\(.*?\)", new_badge, content, count=1)
        else:
            # Insert before usage-badge-end
            new_content = content.replace("<!-- usage-badge-end -->", f"{new_badge}\n<!-- usage-badge-end -->")
    else:
        # Hide/Remove if exists
        if "![Candidate]" in content:
            new_content = re.sub(candidate_pattern, "\n", content, count=1)
            # Clean up potential double newlines
            new_content = new_content.replace("\n\n\n", "\n\n")

    if new_content != content:
        if not check_only:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
        return True
    return False


def fix_readme_version_reference(path, check_only=False):
    if not os.path.exists(path) or not os.path.exists("version.json"):
        return False

    try:
        with open("version.json", "r") as f:
            version_data = json.load(f)
            current_version = version_data.get("version")
    except Exception as e:
        print(f"⚠️ Failed to read version.json: {e}")
        return False

    if not current_version:
        return False

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Regex targeting: | **`@vX.Y.Z`** | Mission Critical
    # Or more generally: | **`@vX.Y.Z`** | in the stable strategy table
    pattern = r"(\|\s*\*\*`@v)\d+\.\d+\.\d+(`\*\*\s*\|\s*Mission Critical)"
    replacement = rf"\g<1>{current_version}\g<2>"
    
    new_content = re.sub(pattern, replacement, content)

    if new_content != content:
        if not check_only:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
        return True
    return False


def main():
    check_only = "--check" in sys.argv
    changed = False

    if fix_usage_badge("README.md", check_only):
        if not check_only:
            print("✅ Updated Total Builds badge in README.md")
        else:
            print("⚠️ README.md Total Builds badge needs update.")
        changed = True

    if fix_candidate_badge("README.md", check_only):
        if not check_only:
            print("✅ Updated/Hidden Candidate badge in README.md")
        else:
            print("⚠️ README.md Candidate badge needs update.")
        changed = True

    if fix_readme_version_reference("README.md", check_only):
        if not check_only:
            print("✅ Synchronized README.md version reference with version.json")
        else:
            print("⚠️ README.md version reference is out of sync with version.json.")
        changed = True

    if changed:
        if check_only:
            sys.exit(1)
    else:
        print("🙌 All badges and version references are already up to date.")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    main()

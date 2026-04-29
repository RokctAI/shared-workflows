# Copyright (c) 2024, Rokct Intelligence (pty) Ltd.
# For license information, please see license.txt

import json
import os
import re
import sys
import urllib.request

STATE_FILE = ".usage_state.json"


def format_count(n):
    if n >= 1_000_000:
        # e.g., 1.2M
        val = f"{n/1_000_000:.1f}M".replace(".0", "")
    elif n >= 1_000:
        # e.g., 5k, 10k
        # User specified: 5000-5999 = 5k. This implies floor division.
        val = f"{n // 1000}k"
    else:
        val = str(n)
    return val


def get_current_count():
    try:
        req = urllib.request.Request(
            "https://api.counterapi.dev/v2/rokctai/usage/stats",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req) as response:
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


def main():
    check_only = "--check" in sys.argv
    if fix_usage_badge("README.md", check_only):
        if not check_only:
            print("✅ Updated Total Builds badge in README.md and saved state.")
        else:
            print("⚠️ README.md Total Builds badge needs update.")
            sys.exit(1)
    else:
        print("🙌 Usage bucket is already up to date. No changes made.")


if __name__ == "__main__":
    main()

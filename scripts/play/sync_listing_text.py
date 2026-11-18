#!/usr/bin/env python3
"""Keep the Play listing text and the repo About in step with the README.

Run by universal-release on a release, never by a deploy. The README is the
source. Its @generated-store-description block (the copy written for the store)
feeds everything:

  * Repo About (GitHub repo description): the block, cut to GitHub's 350-character
    limit, set with the API. Needs Administration write on the repo.
  * full_description.txt: the block as-is, plain text (no AI).
  * short_description.txt: written by the brain endpoint (AI), with a sentence cut
    as the fallback.
  * title.txt: the Android app_name in strings.xml, the store name. The repo name
    is never used.

A listing file is written only when it already exists and is still a template
(empty or comment-only) or still carries this script's marker. A hand edit removes
the marker, so the sync never overwrites it. Deploy does not run this: it reads the
listing files as they are on main.

Writes listing_changed to $GITHUB_OUTPUT for the workflow that opens the PR.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request

MARKER = (
    "# Generated from the README store-description block by universal-release. "
    "Edit the README block, or edit this file by hand to stop the sync."
)
README = "README.md"
README_START = "<!-- @generated-store-description-start -->"
README_END = "<!-- @generated-store-description-end -->"
STRINGS = os.path.join("android", "app", "src", "main", "res", "values", "strings.xml")
LISTING = os.path.join("marketing", "store", "listing", "en-US")
LIMITS = {"title": 30, "short": 80, "full": 4000, "about": 350}


def log(message):
    print(f"[listing-text] {message}", flush=True)


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def is_template(path):
    """Empty or comment-only: nothing a person wrote."""
    return all(not line.strip() or line.lstrip().startswith("#") for line in read(path).splitlines())


def is_generated(path):
    """Carries this script's marker as its first line."""
    lines = read(path).splitlines()
    return bool(lines) and lines[0].strip() == MARKER


def writable(path):
    """Only an existing listing file is touched. The sync never creates one: a
    missing file means the app does not take listing text from the repo."""
    return os.path.isfile(path) and (is_template(path) or is_generated(path))


def readme_block(app_dir):
    path = os.path.join(app_dir, README)
    if not os.path.isfile(path):
        return ""
    match = re.search(re.escape(README_START) + r"(.*?)" + re.escape(README_END), read(path), re.S)
    return match.group(1).strip() if match else ""


def to_plain(markdown):
    """Plain text for a store listing: no HTML comments, links, emphasis or headings."""
    text = re.sub(r"<!--.*?-->", "", markdown, flags=re.S)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_`]+", "", text)
    text = re.sub(r"(?m)^\s*#+\s*", "", text)
    text = re.sub(r"(?m)^\s*[-*]\s+", "- ", text)
    lines = [line.rstrip() for line in text.splitlines()]
    collapsed = []
    for line in lines:
        if line == "" and (not collapsed or collapsed[-1] == ""):
            continue
        collapsed.append(line)
    return "\n".join(collapsed).strip()


def fit(text, limit):
    """Cut to limit at a sentence end when there is one, else at a word boundary."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    window = text[:limit]
    sentence = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
    if sentence > limit // 2:
        return window[: sentence + 1].strip()
    return window.rsplit(" ", 1)[0].rstrip(" ,;:-")


def brain_short(endpoint, token, version, text, limit):
    """Ask the brain endpoint for a short description. None when it cannot answer."""
    if not endpoint or not token:
        return None
    instruction = (
        "Write a one-line store short description for this app. Plain text, no "
        f"markdown, no links, at most {limit} characters. Keep the facts."
    )
    payload = {
        "repo_url": os.environ.get("GITHUB_SERVER_URL", "https://github.com")
        + "/" + os.environ.get("GITHUB_REPOSITORY", ""),
        "version_name": version,
        "commit_log": text,
        "diff_summary": instruction,
    }
    if endpoint.endswith("rokct.platform.api"):
        payload = {
            "cmd": "api.brain.generate_release_notes",
            "payload": {k: payload[k] for k in ("repo_url", "version_name", "commit_log", "diff_summary")},
        }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": token},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception as error:  # best-effort: the fallback always ships
        log(f"brain endpoint failed for the short description: {error}")
        return None
    message = body.get("message") if isinstance(body, dict) else None
    if not isinstance(message, str) or not message.strip():
        return None
    message = to_plain(message)
    return message if 0 < len(message) <= limit else None


def app_name(app_dir):
    path = os.path.join(app_dir, STRINGS)
    if not os.path.isfile(path):
        return ""
    match = re.search(r'<string name="app_name">([^<]+)</string>', read(path))
    return match.group(1).strip() if match else ""


def set_repo_about(description):
    """Set the GitHub repo description. Returns True when it changed."""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        return False
    try:
        current = subprocess.run(
            ["gh", "api", f"repos/{repo}", "--jq", ".description // empty"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as error:
        log(f"could not read the repo About: {error}")
        return False
    if current == description:
        log("repo About already matches the README")
        return False
    try:
        subprocess.run(
            ["gh", "api", "-X", "PATCH", f"repos/{repo}", "-f", f"description={description}"],
            capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        log(f"could not update the repo About (needs Administration write): {error}")
        return False
    log(f"repo About updated from the README ({len(description)} characters)")
    return True


def write_listing(app_dir, name, text):
    path = os.path.join(app_dir, LISTING, name)
    before = read(path) if os.path.isfile(path) else None
    after = MARKER + "\n" + text + "\n"
    if before == after:
        return False
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(after)
    log(f"wrote {os.path.join(LISTING, name)} ({len(text)} characters)")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--app-dir", default=".")
    parser.add_argument("--version", default="")
    parser.add_argument("--brain-endpoint", default=os.environ.get("BRAIN_ENDPOINT", ""))
    parser.add_argument("--no-about", action="store_true", help="do not change the repo About")
    args = parser.parse_args()
    token = os.environ.get("BRAIN_TOKEN", "")

    changed = False
    source = to_plain(readme_block(args.app_dir))
    if not source:
        log("README has no store-description block; nothing to sync")
    else:
        if not args.no_about:
            set_repo_about(fit(source, LIMITS["about"]))

        full_path = os.path.join(args.app_dir, LISTING, "full_description.txt")
        if writable(full_path):
            changed |= write_listing(args.app_dir, "full_description.txt", fit(source, LIMITS["full"]))
        else:
            log("full_description.txt is absent or edited by hand; left as it is")

        short_path = os.path.join(args.app_dir, LISTING, "short_description.txt")
        if writable(short_path):
            short = brain_short(args.brain_endpoint, token, args.version, source, LIMITS["short"]) \
                or fit(source, LIMITS["short"])
            changed |= write_listing(args.app_dir, "short_description.txt", short)
        else:
            log("short_description.txt is absent or edited by hand; left as it is")

    name = app_name(args.app_dir)
    title_path = os.path.join(args.app_dir, LISTING, "title.txt")
    if not name:
        log("no app_name in strings.xml; title left as it is")
    elif writable(title_path):
        changed |= write_listing(args.app_dir, "title.txt", fit(name, LIMITS["title"]))
    else:
        log("title.txt is absent or edited by hand; left as it is")

    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"listing_changed={'true' if changed else 'false'}\n")
    log("listing text changed" if changed else "listing text already current")
    return 0


if __name__ == "__main__":
    sys.exit(main())

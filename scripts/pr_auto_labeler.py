#!/usr/bin/env python3
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

# Copyright (c) 2026, Rokct Intelligence (pty) Ltd.
# For license information, please see license.txt

import os
import re
import sys
import json
import subprocess
import urllib.request

CONVENTIONAL_LABELS = ['feat', 'fix', 'chore', 'docs', 'refactor', 'perf', 'test', 'ci', 'style']

def get_git_commits():
    """Fetch recent commit messages on the current branch."""
    try:
        # Try fetching base ref from git to compare diff
        base_ref = os.environ.get("GITHUB_BASE_REF", "")
        if base_ref:
            subprocess.run(["git", "fetch", "origin", base_ref], capture_output=True)
            cmd = ["git", "log", "--pretty=format:%s", f"origin/{base_ref}..HEAD"]
        else:
            cmd = ["git", "log", "-n", "15", "--pretty=format:%s"]

        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            return res.stdout.splitlines()
    except Exception as e:
        print(f"⚠️ Failed to get git commit logs: {e}")
    return []

def match_conventional(text):
    """Scan a line of text for standard conventional commits pattern."""
    match = re.match(r"^(feat|fix|chore|docs|refactor|perf|test|ci|style|cleanup)(?:\(.*\))?!?:", text.lower().strip())
    if match:
        tag = match.group(1)
        if tag == "cleanup":
            return "style"
        return tag
    return None

def rule_based_labeling(title, body, commits):
    """Determine labels based on regex rules on PR title, description, and commit messages."""
    tags = set()
    
    # 1. Check PR Title
    pr_tag = match_conventional(title)
    if pr_tag:
        tags.add(pr_tag)
        
    # 2. Check Commits
    for commit in commits:
        commit_tag = match_conventional(commit)
        if commit_tag:
            tags.add(commit_tag)
            
    # 3. Text search fallbacks in title/body
    combined_text = (title + " " + body).lower()
    if not tags:
        if any(x in combined_text for x in ["fix", "bug", "issue", "crash", "resolve"]):
            tags.add("fix")
        if any(x in combined_text for x in ["feature", "implement", "add", "new"]):
            tags.add("feat")
        if any(x in combined_text for x in ["docs", "documentation", "readme"]):
            tags.add("docs")
        if any(x in combined_text for x in ["refactor", "clean", "rewrite"]):
            tags.add("refactor")
        if any(x in combined_text for x in ["test", "jest", "unittest"]):
            tags.add("test")
        if any(x in combined_text for x in ["ci", "github action", "pipeline"]):
            tags.add("ci")

    return list(tags)

def ai_labeling(title, body, groq_api_key):
    """Use Groq Llama 3 to classify the PR and return tags."""
    if not groq_api_key:
        return []
    
    print("🧠 Requesting AI PR Classification from Groq...")
    prompt = f"""You are a Conventional Commits classifier. Analyze the following Pull Request Title and Description:
Title: {title}
Description: {body}

Choose a list of tags from: {CONVENTIONAL_LABELS}.
Return ONLY a JSON array of strings containing the selected tags. Do not explain your choice.
Example Output: ["feat", "docs"]
"""
    
    payload = {
        "model": "llama-3.3-70b-specdec",
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "max_tokens": 50,
        "response_format": {"type": "json_object"}
    }
    
    try:
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {groq_api_key}"
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            content = res_data["choices"][0]["message"]["content"]
            data = json.loads(content)
            # Support both direct array response or dict with key
            if isinstance(data, dict):
                tags = data.get("tags", data.get("labels", list(data.values())[0] if data.values() else []))
            else:
                tags = data
            if isinstance(tags, list):
                return [t for t in tags if t in CONVENTIONAL_LABELS]
    except Exception as e:
        print(f"⚠️ Groq AI classification failed: {e}")
    return []

def apply_labels(repo, pr_number, labels, token):
    """Apply labels to PR via GitHub REST API."""
    if not labels:
        print("ℹ️ No labels resolved to apply.")
        return
        
    print(f"🏷️ Applying labels to PR #{pr_number}: {labels}")
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/labels"
    payload = {"labels": labels}
    
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "x-trace-id": "gh-labeler-run"
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status in [200, 201]:
                print("✅ Successfully applied labels.")
            else:
                print(f"⚠️ Failed to apply labels, response status: {response.status}")
    except Exception as e:
        print(f"⚠️ Error applying labels: {e}")

def main():
    print("=" * 80)
    print("ROKCT FLEET STANDARD - COMMIT & PR AUTO-LABELER")
    print("=" * 80)

    # 1. Resolve PR environment details
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    pr_number = os.environ.get("PR_NUMBER", "")
    pr_title = os.environ.get("PR_TITLE", "")
    pr_body = os.environ.get("PR_BODY", "")
    github_token = os.environ.get("GITHUB_TOKEN", "")
    groq_api_key = os.environ.get("GROQ_API", "")

    if not repo or not pr_number or not github_token:
        print("SUCCESS: Outside PR pipeline environment. Skipping auto-labeling.")
        sys.exit(0)

    print(f"Auditing PR #{pr_number} on {repo}")
    print(f"PR Title: {pr_title}")

    # 2. Rule-Based analysis
    commits = get_git_commits()
    resolved_labels = rule_based_labeling(pr_title, pr_body, commits)
    print(f"Rule-based labels detected: {resolved_labels}")

    # 3. AI analysis
    ai_labels = ai_labeling(pr_title, pr_body, groq_api_key)
    if ai_labels:
        print(f"AI-based labels detected: {ai_labels}")
        resolved_labels = list(set(resolved_labels + ai_labels))

    # 4. Apply Labels
    apply_labels(repo, pr_number, resolved_labels, github_token)
    
    print("=" * 80)
    print("PR AUTO-LABELER COMPLETE.")
    print("=" * 80)

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    main()

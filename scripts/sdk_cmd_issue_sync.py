#!/usr/bin/env python3
# Copyright (c) 2026 ROKCT INTELLIGENCE (PTY) LTD
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
#
# Syncs the sdk_validator.py gateway cmd check (--cmd-report JSON) into ONE
# issue per SDK in the central repo (RokctAI/platformstack by default):
#   - unresolved cmds > 0, no issue   -> open one
#   - unresolved cmds > 0, issue open -> update its body in place
#   - unresolved cmds > 0, issue closed -> reopen + update (never a 2nd issue)
#   - unresolved cmds == 0, issue open -> close it
# An issue is identified by the hidden marker `<!-- cmd-check:<sdk> -->` in
# its body (among issues carrying the `sdk-cmd-check` label), so title edits
# never cause duplicates. SDKs absent from the report (no frappe half in this
# workspace) are left untouched.
#
# Best effort by design: missing token/report or any API error is logged and
# the script exits 0, so it can never fail a build.
# Usage: python3 sdk_cmd_issue_sync.py <cmd_report.json> [--repo OWNER/NAME]
#        [--dry-run]. Token: GH_TOKEN (the MONOREPO_PAT secret in CI).

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

LABEL = "sdk-cmd-check"
API = os.environ.get("GITHUB_API_URL", "https://api.github.com")


def marker(sdk):
    return f"<!-- cmd-check:{sdk} -->"


def issue_title(sdk):
    return f"{sdk}: unresolved gateway cmds"


def render_body(sdk, entries, run_url=None, source_repo=None):
    """Markdown body for one SDK's issue. Deterministic for a given input."""
    lines = [
        marker(sdk),
        f"## {issue_title(sdk)}",
        "",
        f"`sdk_validator.py` found **{len(entries)}** gateway cmd(s) used by "
        f"the `{sdk}` dart half that its own frappe half (or declared deps) "
        "does not whitelist. Each one will fail at runtime against "
        "`rokct.platform.api`.",
        "",
        "| cmd | first used at |",
        "|---|---|",
    ]
    for e in sorted(entries, key=lambda x: x["cmd"]):
        lines.append(f"| `{e['cmd']}` | `{e['file']}` |")
    lines.append("")
    if source_repo:
        lines.append(f"- **Source repo:** `{source_repo}`")
    if run_url:
        lines.append(f"- **Last checked by:** {run_url}")
    lines += [
        "",
        "This issue is updated on every validator run and closes itself once "
        "this SDK has zero unresolved cmds. The check is warn-only and does "
        "not fail builds.",
        "",
    ]
    return "\n".join(lines)


def find_issue(issues, sdk):
    """Picks the tracking issue for `sdk` (open preferred, then lowest #)."""
    m = marker(sdk)
    hits = [i for i in issues
            if "pull_request" not in i and m in (i.get("body") or "")]
    if not hits:
        return None
    hits.sort(key=lambda i: (i.get("state") != "open", i["number"]))
    return hits[0]


def plan(report, issues):
    """Returns [(action, sdk, issue_number|None, entries)].

    action: 'open' | 'update' | 'reopen' | 'close' | 'noop'.
    """
    actions = []
    for sdk in sorted(report):
        entries = report[sdk] or []
        issue = find_issue(issues, sdk)
        if entries:
            if issue is None:
                actions.append(("open", sdk, None, entries))
            elif issue.get("state") == "open":
                actions.append(("update", sdk, issue["number"], entries))
            else:
                actions.append(("reopen", sdk, issue["number"], entries))
        elif issue is not None and issue.get("state") == "open":
            actions.append(("close", sdk, issue["number"], entries))
        else:
            actions.append(("noop", sdk, None, entries))
    return actions


def _api(method, path, token, payload=None):
    req = urllib.request.Request(
        f"{API}{path}", method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "User-Agent": "rokct-sdk-cmd-check"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read()
        return json.loads(body) if body else None


def list_tracked_issues(repo, token):
    issues, page = [], 1
    while True:
        batch = _api("GET", f"/repos/{repo}/issues?labels={LABEL}&state=all"
                     f"&per_page=100&page={page}", token)
        issues += batch
        if len(batch) < 100:
            return issues
        page += 1


def ensure_label(repo, token):
    try:
        _api("POST", f"/repos/{repo}/labels", token,
             {"name": LABEL, "color": "FBCA04",
              "description": "Automated: SDK dart cmds its frappe half does not whitelist"})
    except urllib.error.HTTPError as e:
        if e.code != 422:  # 422 = already exists
            raise


def apply(actions, repo, token, run_url, source_repo, dry_run=False):
    failures = 0
    for action, sdk, number, entries in actions:
        print(f"[{sdk}] {action}" + (f" #{number}" if number else "")
              + f" ({len(entries)} unresolved)")
        if action == "noop" or dry_run:
            continue
        body = render_body(sdk, entries, run_url, source_repo)
        try:
            if action == "open":
                _api("POST", f"/repos/{repo}/issues", token,
                     {"title": issue_title(sdk), "body": body, "labels": [LABEL]})
            elif action in ("update", "reopen"):
                _api("PATCH", f"/repos/{repo}/issues/{number}", token,
                     {"title": issue_title(sdk), "body": body, "state": "open"})
            elif action == "close":
                _api("POST", f"/repos/{repo}/issues/{number}/comments", token,
                     {"body": f"All gateway cmds of `{sdk}` now resolve"
                      + (f" ({run_url})" if run_url else "") + ". Closing."})
                _api("PATCH", f"/repos/{repo}/issues/{number}", token,
                     {"state": "closed", "state_reason": "completed"})
        except (urllib.error.URLError, OSError, ValueError) as e:
            failures += 1
            print(f"::warning::cmd-check issue sync failed for {sdk} ({action}): {e}")
    return failures


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("report")
    p.add_argument("--repo", default=os.environ.get("CENTRAL_REPO", "RokctAI/platformstack"))
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    try:
        with open(a.report, encoding="utf-8") as f:
            report = json.load(f)
    except (OSError, ValueError) as e:
        print(f"::warning::No usable cmd report ({e}); skipping issue sync.")
        return 0
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token and not a.dry_run:
        print("GH_TOKEN (MONOREPO_PAT) not available - skipping cmd-check issue sync.")
        return 0
    server = os.environ.get("GITHUB_SERVER_URL")
    run_url = (f"{server}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/"
               f"{os.environ['GITHUB_RUN_ID']}"
               if server and os.environ.get("GITHUB_RUN_ID") else None)
    try:
        issues = list_tracked_issues(a.repo, token) if token else []
        if not a.dry_run:
            ensure_label(a.repo, token)
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f"::warning::cmd-check issue sync could not reach {a.repo}: {e}")
        return 0
    apply(plan(report, issues), a.repo, token, run_url,
          os.environ.get("GITHUB_REPOSITORY"), a.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())

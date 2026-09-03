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
"""Store deadline radar: file central issues when the fleet is behind a store deadline.

Reads deadlines.json (a small maintained table of app-store deadlines such as
Google Play's annual target-API bump), fetches each fleet app repo's Android
Gradle config and CI Flutter pin via the GitHub contents API, and computes a
per-repo status per deadline:

  OK       - compliant, or non-compliant but more than 60 days from the deadline
  AT RISK  - not compliant and within 60 days of the base deadline
  BEHIND   - not compliant and on or past the base deadline (the extension
             date, where one exists, is the hard edge and is called out in
             the body)

For every deadline with an AT RISK or BEHIND repo it opens ONE issue in the
central report repo (RokctAI/platformstack), mirroring the report-build-status
/ central-report conventions: stable exact title (`deadline-radar: <title>`)
as the dedupe key among open `deadline-radar`-labelled issues, body updated
plus a comment when the status changes, no-op when unchanged, auto-close with
a recovery comment once every repo is compliant. It also files a
`deadline-radar: deadline table needs review` issue when any entry's
review_by date has passed, so the table itself cannot silently go stale.

Runs on a weekly cron in shared-workflows (public repo, free minutes) with
MONOREPO_PAT - see .github/workflows/deadline-radar.yml. Degrades to a log
line when the token is unavailable. Use --dry-run to print every planned
issue operation instead of performing it.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request

API_ROOT = "https://api.github.com"
AT_RISK_WINDOW_DAYS = 60
RADAR_LABEL = "deadline-radar"
REVIEW_TITLE = "deadline-radar: deadline table needs review"
STATE_MARKER = "<!-- deadline-radar-state: {} -->"
STATE_MARKER_RE = re.compile(r"<!-- deadline-radar-state: ([0-9a-f]+) -->")

TARGET_SDK_RE = re.compile(r"^\s*targetSdk(?:Version)?\s*=?\s*(\S+)", re.MULTILINE)
FLUTTER_VERSION_RE = re.compile(r"flutter-version[^0-9\n]*(\d+\.\d+\.\d+)")


def log(message):
    print(message, flush=True)


def warn(message):
    # ::warning:: renders in the Actions annotations; plain prefix elsewhere.
    print(f"::warning::{message}" if os.environ.get("GITHUB_ACTIONS") else f"WARNING: {message}", flush=True)


class GitHub:
    """Minimal stdlib GitHub API client (no third-party dependencies)."""

    def __init__(self, token):
        self.token = token

    def _request(self, method, url, body=None, accept="application/vnd.github+json"):
        headers = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError) as error:
            return 0, str(error)

    def fetch_raw_file(self, repo, path, ref=None):
        """Return (http_status, text) for a repo file via the contents API."""
        url = f"{API_ROOT}/repos/{repo}/contents/{path}"
        if ref:
            url += f"?ref={ref}"
        return self._request("GET", url, accept="application/vnd.github.raw")

    def get_json(self, url):
        status, text = self._request("GET", url)
        if status != 200:
            raise RuntimeError(f"GET {url} -> HTTP {status}: {text[:200]}")
        return json.loads(text)

    def post_json(self, url, body, ok=(200, 201)):
        status, text = self._request("POST", url, body=body)
        if status not in ok:
            raise RuntimeError(f"POST {url} -> HTTP {status}: {text[:200]}")
        return json.loads(text) if text else {}

    def patch_json(self, url, body):
        status, text = self._request("PATCH", url, body=body)
        if status != 200:
            raise RuntimeError(f"PATCH {url} -> HTTP {status}: {text[:200]}")
        return json.loads(text)

    def ensure_label(self, repo, name, color, description):
        status, text = self._request(
            "POST",
            f"{API_ROOT}/repos/{repo}/labels",
            body={"name": name, "color": color, "description": description},
        )
        if status not in (201, 422):  # 422 = already exists
            warn(f"Could not ensure label '{name}' on {repo} (HTTP {status}): {text[:200]}")


def parse_version(version):
    return tuple(int(part) for part in version.split("."))


def parse_target_sdk(gradle_text):
    """Extract the targetSdk value from a build.gradle; int when numeric."""
    match = TARGET_SDK_RE.search(gradle_text)
    if not match:
        return None
    raw = match.group(1).strip().strip("\"'")
    return int(raw) if raw.isdigit() else raw  # e.g. 'flutter.targetSdkVersion'


def parse_flutter_pin(workflow_text):
    match = FLUTTER_VERSION_RE.search(workflow_text)
    return match.group(1) if match else None


def shared_default_flutter_version(github):
    """The fleet-wide fallback Flutter pin from universal-pipeline.yml.

    Prefer the local checkout (the radar workflow runs inside shared-workflows);
    fall back to the GitHub API so the script also works standalone.
    """
    local = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", ".github", "workflows", "universal-pipeline.yml",
    )
    if os.path.isfile(local):
        with open(local, encoding="utf-8") as handle:
            text = handle.read()
    else:
        status, text = github.fetch_raw_file("RokctAI/shared-workflows", ".github/workflows/universal-pipeline.yml")
        if status != 200:
            warn(f"Could not read universal-pipeline.yml (HTTP {status}); no shared Flutter fallback available.")
            return None
    return parse_flutter_pin(text)


def collect_repo_facts(github, org, repo_entries, shared_flutter):
    """Fetch targetSdk + Flutter pin for every configured repo."""
    facts = []
    for entry in repo_entries:
        name = entry["repo"]
        display = entry.get("display", name)
        fact = {
            "display": display,
            "template": bool(entry.get("template")),
            "target_sdk": None,
            "flutter_version": None,
            "readable": True,
        }

        status, gradle = github.fetch_raw_file(f"{org}/{name}", entry["gradle_path"])
        if status == 200:
            fact["target_sdk"] = parse_target_sdk(gradle)
            if fact["target_sdk"] is None:
                warn(f"{display}: no targetSdk found in {entry['gradle_path']}.")
        else:
            fact["readable"] = False
            warn(f"{display}: could not read {entry['gradle_path']} (HTTP {status}).")

        if not fact["template"]:
            status, workflow = github.fetch_raw_file(f"{org}/{name}", ".github/workflows/build.yml")
            if status == 200:
                fact["flutter_version"] = parse_flutter_pin(workflow) or shared_flutter
            else:
                fact["flutter_version"] = shared_flutter

        facts.append(fact)
        log(f"  {display}: targetSdk={fact['target_sdk']} flutter={fact['flutter_version']}"
            + ("" if fact["readable"] else " (UNREADABLE)"))
    return facts


def repo_value_and_compliance(deadline, fact):
    """Return (display_value, compliant_or_None) for one repo against one deadline."""
    check = deadline["check"]
    if check == "target_sdk":
        if not fact["readable"]:
            return "unreadable", None
        value = fact["target_sdk"]
        if isinstance(value, int):
            return str(value), value >= int(deadline["threshold"])
        return "not found" if value is None else str(value), None  # missing / symbolic value
    if check == "flutter_min_version":
        if fact["template"]:
            return "n/a (template)", True  # templates carry no CI Flutter pin
        value = fact["flutter_version"]
        if value:
            try:
                return value, parse_version(value) >= parse_version(deadline["threshold"])
            except ValueError:
                return value, None
        return "unknown", None
    return "n/a", None


def status_for(compliant, deadline, today):
    """OK / AT RISK / BEHIND / UNKNOWN per the radar's rules."""
    if compliant is None:
        return "UNKNOWN"
    if compliant:
        return "OK"
    base = dt.date.fromisoformat(deadline["deadline"])
    if today >= base:
        return "BEHIND"
    if (base - today).days <= AT_RISK_WINDOW_DAYS:
        return "AT RISK"
    return "OK"


def evaluate_deadline(deadline, facts, today):
    """Compute per-repo rows and the aggregate action for one deadline entry."""
    rows = []
    behind = at_risk = unknown = 0
    for fact in facts:
        value, compliant = repo_value_and_compliance(deadline, fact)
        status = status_for(compliant, deadline, today)
        if status == "BEHIND":
            behind += 1
        elif status == "AT RISK":
            at_risk += 1
        elif status == "UNKNOWN":
            unknown += 1
        rows.append({"repo": fact["display"], "value": value, "status": status})
    return {"rows": rows, "behind": behind, "at_risk": at_risk, "unknown": unknown}


def state_hash(deadline_id, rows):
    payload = json.dumps({"id": deadline_id, "rows": rows}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def build_issue_body(deadline, result, today):
    base = dt.date.fromisoformat(deadline["deadline"])
    extension = dt.date.fromisoformat(deadline["extension"]) if deadline.get("extension") else None
    hard_edge = extension or base
    days_to_base = (base - today).days
    days_to_edge = (hard_edge - today).days

    lines = [
        f"## \U0001F4E1 {deadline['title']}",
        "",
        deadline["description"],
        "",
        "| | |",
        "|---|---|",
        f"| **Requirement** | `{deadline['check']} >= {deadline['threshold']}` |",
        f"| **Deadline** | {deadline['deadline']} ({days_to_base} days) |",
    ]
    if extension:
        lines.append(f"| **Extension (hard edge)** | {deadline['extension']} ({days_to_edge} days) |")
    lines += [
        f"| **Checked** | {today.isoformat()} |",
        "",
        "### Fleet status",
        "",
        "| Repo | Value | Status |",
        "|---|---|---|",
    ]
    icons = {"OK": "✅", "AT RISK": "⚠️", "BEHIND": "\U0001F6A8", "UNKNOWN": "❓"}
    for row in result["rows"]:
        lines.append(f"| {row['repo']} | `{row['value']}` | {icons[row['status']]} {row['status']} |")
    lines += [
        "",
        f"**{result['behind']} repo(s) BEHIND, {result['at_risk']} at risk.**",
    ]
    if result["unknown"]:
        lines.append(f"{result['unknown']} repo(s) could not be checked (unreadable or non-numeric config) - "
                     "verify those by hand.")
    if extension and today >= base and today <= extension:
        lines += [
            "",
            f"⚠️ The base deadline has passed. Updates from non-compliant apps are blocked "
            f"unless the per-app extension (available until {deadline['extension']}) is requested in the store console.",
        ]
    lines += [
        "",
        "This issue is maintained by the [deadline radar]"
        "(https://github.com/RokctAI/shared-workflows/blob/main/.github/workflows/deadline-radar.yml) "
        "and closes automatically once every repo is compliant.",
        "",
        STATE_MARKER.format(state_hash(deadline["id"], result["rows"])),
    ]
    return "\n".join(lines)


def run_url():
    if os.environ.get("GITHUB_RUN_ID"):
        return (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
                f"{os.environ.get('GITHUB_REPOSITORY', 'RokctAI/shared-workflows')}/"
                f"actions/runs/{os.environ['GITHUB_RUN_ID']}")
    return None


class IssueFiler:
    """Open / update / close radar issues in the central repo, with dry-run."""

    def __init__(self, github, central_repo, dry_run):
        self.github = github
        self.central = central_repo
        self.dry_run = dry_run
        self._open_issues = None

    def open_issues(self):
        # Exact-title dedupe among OPEN radar-labelled issues, mirroring central-report.
        if self._open_issues is None:
            url = (f"{API_ROOT}/repos/{self.central}/issues"
                   f"?state=open&labels={RADAR_LABEL}&per_page=100")
            self._open_issues = self.github.get_json(url)
        return self._open_issues

    def find(self, title):
        for issue in self.open_issues():
            if issue.get("title") == title:
                return issue
        return None

    def ensure_labels(self):
        if self.dry_run:
            log(f"DRY RUN: would ensure label '{RADAR_LABEL}' exists on {self.central}.")
            return
        self.github.ensure_label(
            self.central, RADAR_LABEL, "D93F0B",
            "Automated report: fleet behind or approaching an app-store deadline",
        )

    def comment(self, issue, body):
        if self.dry_run:
            log(f"DRY RUN: would comment on {self.central}#{issue['number']}:\n{body}\n")
            return
        self.github.post_json(
            f"{API_ROOT}/repos/{self.central}/issues/{issue['number']}/comments",
            {"body": body},
        )

    def file_or_update(self, title, body, change_note):
        existing = self.find(title)
        if existing is None:
            if self.dry_run:
                log(f"DRY RUN: would open issue in {self.central}: '{title}'\n---\n{body}\n---\n")
                return
            issue = self.github.post_json(
                f"{API_ROOT}/repos/{self.central}/issues",
                {"title": title, "body": body, "labels": [RADAR_LABEL]},
            )
            log(f"Opened {self.central}#{issue['number']}: {title}")
            return

        old_marker = STATE_MARKER_RE.search(existing.get("body") or "")
        new_marker = STATE_MARKER_RE.search(body)
        if old_marker and new_marker and old_marker.group(1) == new_marker.group(1):
            log(f"No change for '{title}' ({self.central}#{existing['number']}); leaving it as is.")
            return
        if self.dry_run:
            log(f"DRY RUN: would update body of {self.central}#{existing['number']} ('{title}') "
                f"and comment: {change_note}")
            return
        self.github.patch_json(
            f"{API_ROOT}/repos/{self.central}/issues/{existing['number']}",
            {"body": body},
        )
        self.comment(existing, change_note)
        log(f"Updated {self.central}#{existing['number']}: {title}")

    def close_if_open(self, title, recovery_note):
        existing = self.find(title)
        if existing is None:
            log(f"'{title}' is clean and no open issue to close. Nothing to do.")
            return
        if self.dry_run:
            log(f"DRY RUN: would close {self.central}#{existing['number']} ('{title}') "
                f"with comment: {recovery_note}")
            return
        self.comment(existing, recovery_note)
        self.github.patch_json(
            f"{API_ROOT}/repos/{self.central}/issues/{existing['number']}",
            {"state": "closed"},
        )
        log(f"Closed {self.central}#{existing['number']}: {title}")


def review_table(config, today):
    """Entries whose review_by has passed - the radar flagging its OWN staleness."""
    return [entry for entry in config["deadlines"]
            if entry.get("review_by") and today > dt.date.fromisoformat(entry["review_by"])]


def build_review_body(stale_entries, today):
    lines = [
        "## \U0001F9ED Deadline table needs review",
        "",
        "The deadline radar's own table "
        "([scripts/deadline-radar/deadlines.json]"
        "(https://github.com/RokctAI/shared-workflows/blob/main/scripts/deadline-radar/deadlines.json)) "
        "has entries past their `review_by` date. Store requirements change every year - "
        "re-verify these against the official Google Play / App Store announcements, update "
        "the dates and thresholds, and bump `review_by`:",
        "",
    ]
    rows = []
    for entry in stale_entries:
        lines.append(f"- **{entry['title']}** (`{entry['id']}`) - review was due {entry['review_by']}")
        rows.append({"repo": entry["id"], "value": entry["review_by"], "status": "STALE"})
    lines += [
        "",
        f"Checked {today.isoformat()}. This issue closes automatically once every entry's "
        "`review_by` is in the future again.",
        "",
        STATE_MARKER.format(state_hash("table-review", rows)),
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Store deadline radar (see module docstring).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print every planned issue operation instead of performing it.")
    parser.add_argument("--config", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "deadlines.json"),
                        help="Path to deadlines.json.")
    parser.add_argument("--org", default="RokctAI", help="GitHub org that hosts the fleet repos.")
    parser.add_argument("--central-repo", default="RokctAI/platformstack",
                        help="Central repo that receives radar issues.")
    args = parser.parse_args()

    token = os.environ.get("GH_TOKEN") or os.environ.get("MONOREPO_PAT") or os.environ.get("GITHUB_TOKEN")
    if not token:
        if args.dry_run:
            warn("No token available; continuing unauthenticated (private repos will show as unreadable).")
        else:
            # Mirror central-report's graceful degrade: never fail the caller over a missing PAT.
            log("MONOREPO_PAT is not available - skipping the deadline radar.")
            return 0

    with open(args.config, encoding="utf-8") as handle:
        config = json.load(handle)

    github = GitHub(token)
    today = dt.date.today()
    log(f"Deadline radar - {today.isoformat()}{' (DRY RUN)' if args.dry_run else ''}")

    shared_flutter = shared_default_flutter_version(github)
    log(f"Shared fallback Flutter pin (universal-pipeline.yml): {shared_flutter}")
    log("Fleet facts:")
    facts = collect_repo_facts(github, args.org, config["repos"], shared_flutter)

    filer = IssueFiler(github, args.central_repo, args.dry_run)
    needs_label = False
    actions = []

    for deadline in config["deadlines"]:
        if deadline["check"] == "manual":
            log(f"'{deadline['title']}': manual/awareness-only entry - never files an issue.")
            continue
        result = evaluate_deadline(deadline, facts, today)
        title = f"deadline-radar: {deadline['title']}"
        summary = (f"{deadline['id']}: {result['behind']} behind, {result['at_risk']} at risk, "
                   f"{result['unknown']} unknown")
        log(summary)
        if result["behind"] or result["at_risk"]:
            needs_label = True
            note_lines = [f"Deadline radar update: {result['behind']} repo(s) BEHIND and "
                          f"{result['at_risk']} at risk for **{deadline['title']}**."]
            url = run_url()
            if url:
                note_lines.append(f"\n- **Run:** {url}")
            actions.append(("file", title, build_issue_body(deadline, result, today),
                            "\n".join(note_lines)))
        else:
            recovery = (f"✅ Recovered: every tracked repo is compliant with "
                        f"**{deadline['title']}**.")
            url = run_url()
            if url:
                recovery += f"\n\n- **Run:** {url}"
            actions.append(("close", title, None, recovery))

    stale = review_table(config, today)
    if stale:
        needs_label = True
        actions.append(("file", REVIEW_TITLE, build_review_body(stale, today),
                        "Deadline radar update: the deadline table still has entries past `review_by`."))
    else:
        actions.append(("close", REVIEW_TITLE,
                        None, "✅ Recovered: every deadline-table entry's `review_by` is in the future."))

    if needs_label:
        filer.ensure_labels()
    for kind, title, body, note in actions:
        if kind == "file":
            filer.file_or_update(title, body, note)
        else:
            filer.close_if_open(title, note)

    return 0


if __name__ == "__main__":
    sys.exit(main())

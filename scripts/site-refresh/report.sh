#!/usr/bin/env bash
# Copyright 2026 ROKCT INTELLIGENCE (PTY) LTD
#
# Run summary + central issues for the weekly site refresh.
#
# Usage: report.sh <results dir>
#   <results dir>/refresh-<repo>/  status, detail, [pr], [mode], [versions.md]
#   <results dir>/health-<repo>/   status (healthy|unhealthy|no-url|error),
#                                  url, [health.json]
#
# Writes the per-site table to $GITHUB_STEP_SUMMARY (or stdout), then keeps
# ONE live issue per site and failure kind in $CENTRAL_REPO, in the same
# format, labels and dedupe as the Flutter builds' central report
# (universal-flutter-build.yml, report-build-status):
#   "<repo>: site refresh failed"  labels build-failure, app:<repo>
#   "<repo>: live site unhealthy"  labels site-health,   app:<repo>
# Dedupe is an exact-title match among OPEN issues with that label; a still
# failing site gets a comment, a recovered one gets its issue closed.
# DRY_RUN=true (or no GH_TOKEN) prints the issue actions instead.
#
# Environment: GH_TOKEN, CENTRAL_REPO (default RokctAI/platformstack), ORG,
# DRY_RUN, RUN_URL.
set -euo pipefail

RESULTS="${1:?usage: report.sh <results dir>}"
CENTRAL_REPO="${CENTRAL_REPO:-RokctAI/platformstack}"
ORG="${ORG:-RokctAI}"
DRY_RUN="${DRY_RUN:-false}"
RUN_URL="${RUN_URL:-}"
SUMMARY="${GITHUB_STEP_SUMMARY:-/dev/stdout}"
NOW_UTC="$(date -u +'%Y-%m-%d %H:%M:%S UTC')"
WRITE=true
if [ "$DRY_RUN" = "true" ] || [ -z "${GH_TOKEN:-}" ]; then
  WRITE=false
fi

field() {
  if [ -s "$1" ]; then
    head -1 "$1"
  else
    printf '%s' "${2:-}"
  fi
}
# Table cells: no pipes or line breaks.
cell() {
  tr '\n|' '  ' <<<"$1" | cut -c1-300
}

REPOS="$(find "$RESULTS" -mindepth 1 -maxdepth 1 -type d \( -name 'refresh-*' -o -name 'health-*' \) -printf '%f\n' |
  sed -E 's/^(refresh|health)-//' | sort -u)"

refresh_label() {
  case "$1" in
  up-to-date) echo "Up to date" ;;
  merged) echo "Refreshed and merged (build green)" ;;
  auto-merge-armed) echo "PR opened, auto-merge armed" ;;
  pr-open) echo "PR opened, not merged yet" ;;
  dry-run) echo "Dry run" ;;
  skipped) echo "Skipped" ;;
  failed) echo "FAILED" ;;
  *) echo "$1" ;;
  esac
}

{
  echo "## Weekly site refresh$([ "$DRY_RUN" = "true" ] && echo " (dry run)")"
  echo ""
  if [ -z "$REPOS" ]; then
    echo "No sites were found."
  else
    echo "| Site | Refresh | Why | Pull request | Live site |"
    echo "| --- | --- | --- | --- | --- |"
    while read -r R; do
      [ -n "$R" ] || continue
      RD="$RESULTS/refresh-$R"
      HD="$RESULTS/health-$R"
      if [ -d "$RD" ]; then
        RS="$(field "$RD/status" failed)"
        REFRESH="$(refresh_label "$RS")"
        WHY="$(cell "$(field "$RD/detail" "no result was recorded (the job stopped early)")")"
        PR="$(field "$RD/pr" "-")"
      else
        REFRESH="not refreshed (no compose shell)"
        WHY="-"
        PR="-"
      fi
      if [ -d "$HD" ]; then
        HS="$(field "$HD/status" error)"
        URL="$(field "$HD/url")"
        case "$HS" in
        healthy) LIVE="healthy ($URL)" ;;
        unhealthy) LIVE="UNHEALTHY ($URL): $(cell "$(jq -r '.problems[0] // ""' "$HD/health.json" 2>/dev/null || true)")" ;;
        no-url) LIVE="no live URL known (.rokct/showcase.json url or repo homepage)" ;;
        *) LIVE="check did not run: $(cell "$(field "$HD/detail" "$HS")")" ;;
        esac
      else
        LIVE="-"
      fi
      echo "| \`$R\` | $REFRESH | $WHY | $PR | $LIVE |"
    done <<<"$REPOS"
  fi
  echo ""
  if [ "$WRITE" = "true" ]; then
    echo "Failures are tracked as issues in \`$CENTRAL_REPO\` (one per site and kind; closed automatically on recovery)."
  else
    echo "Issues in \`$CENTRAL_REPO\` were not touched (dry run or no token); the log lists what would have been filed or closed."
  fi
} >>"$SUMMARY"

[ -n "$REPOS" ] || exit 0

find_open_issue() { # <label> <title>
  gh issue list -R "$CENTRAL_REPO" --state open --label "$1" --json number,title --limit 200 2>/dev/null |
    jq -r --arg t "$2" '[.[] | select(.title == $t)][0].number // empty'
}

# report_issue <fail|ok> <label> <label description> <title> <repo> <body file>
report_issue() {
  local action="$1" label="$2" label_desc="$3" title="$4" repo="$5" body="$6" existing=""
  if [ "$WRITE" != "true" ]; then
    echo "[dry run] $CENTRAL_REPO: would $([ "$action" = fail ] && echo "open or comment on" || echo "close (if open)") '$title'"
    return 0
  fi
  existing="$(find_open_issue "$label" "$title" || true)"
  if [ "$action" = "fail" ]; then
    gh label create "$label" -R "$CENTRAL_REPO" --color "$([ "$label" = build-failure ] && echo B60205 || echo D93F0B)" \
      --description "$label_desc" 2>/dev/null || true
    gh label create "app:${repo}" -R "$CENTRAL_REPO" --color "1D76DB" \
      --description "Build reports for ${repo}" 2>/dev/null || true
    if [ -n "$existing" ]; then
      echo "Open issue #$existing already tracks '$title'; adding a comment."
      {
        echo "Still failing (weekly site refresh, ${NOW_UTC})."
        echo ""
        sed -n '/^### What failed$/,$p' "$body"
      } >"$body.comment"
      gh issue comment "$existing" -R "$CENTRAL_REPO" --body-file "$body.comment" ||
        echo "::warning::Failed to comment on issue #$existing."
    else
      gh issue create -R "$CENTRAL_REPO" --title "$title" --label "$label" --label "app:${repo}" --body-file "$body" ||
        gh issue create -R "$CENTRAL_REPO" --title "$title" --body-file "$body" ||
        echo "::warning::Failed to open '$title'."
    fi
  elif [ -n "$existing" ]; then
    echo "Recovered: closing #$existing ('$title')."
    gh issue close "$existing" -R "$CENTRAL_REPO" --comment "$(cat "$body")" ||
      echo "::warning::Failed to close issue #$existing."
  fi
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
footer() {
  printf '\n---\n_Generated by [Claude Code](https://claude.ai/code)_\n'
}

while read -r R; do
  RD="$RESULTS/refresh-$R"
  HD="$RESULTS/health-$R"

  # (1) The refresh: compose refresh, the offline zero-drift pre-gate, or the
  # PR's build (compose + `npm run build`) failed.
  if [ -d "$RD" ]; then
    RS="$(field "$RD/status" failed)"
    TITLE="${R}: site refresh failed"
    B="$TMP/refresh-$R.md"
    if [ "$RS" = "failed" ]; then
      {
        echo "## 🚨 ${TITLE}"
        echo ""
        echo "| | |"
        echo "|---|---|"
        echo "| **Repository** | \`${ORG}/${R}\` |"
        echo "| **Platform** | \`nextjs site refresh\` |"
        echo "| **Failing run** | ${RUN_URL} |"
        echo "| **Pull request** | $(field "$RD/pr" "none (nothing was pushed)") |"
        echo "| **Failed at** | ${NOW_UTC} |"
        echo ""
        echo "### What failed"
        echo ""
        field "$RD/detail" "no result was recorded (the job stopped early)"
        echo ""
        if [ -s "$RD/versions.md" ] && [ "$(wc -l <"$RD/versions.md")" -gt 2 ]; then
          echo ""
          echo "### Building blocks this refresh tried to move"
          echo ""
          cat "$RD/versions.md"
        fi
        echo ""
        echo "Nothing red is ever merged: the live site keeps its current pins. This issue stays open until a weekly refresh of ${R} succeeds (or finds it already up to date), which closes it automatically."
        footer
      } >"$B"
      report_issue fail build-failure "Automated report: an app build is failing on mainline" "$TITLE" "$R" "$B"
    elif [ "$RS" = "up-to-date" ] || [ "$RS" = "merged" ]; then
      {
        echo "✅ Recovered: the weekly site refresh of \`${R}\` is green again ($(field "$RD/status"))."
        echo ""
        echo "- **Run:** ${RUN_URL}"
        echo "- **Time:** ${NOW_UTC}"
        footer
      } >"$B"
      report_issue ok build-failure "" "$TITLE" "$R" "$B"
    fi
  fi

  # (2) The LIVE site is unhealthy, whatever Vercel built.
  if [ -d "$HD" ]; then
    HS="$(field "$HD/status" error)"
    URL="$(field "$HD/url")"
    TITLE="${R}: live site unhealthy"
    B="$TMP/health-$R.md"
    if [ "$HS" = "unhealthy" ]; then
      {
        echo "## 🚨 ${TITLE}"
        echo ""
        echo "| | |"
        echo "|---|---|"
        echo "| **Repository** | \`${ORG}/${R}\` |"
        echo "| **Live URL** | ${URL} |"
        echo "| **Checked by** | ${RUN_URL} |"
        echo "| **Checked at** | ${NOW_UTC} |"
        echo ""
        echo "### What failed"
        echo ""
        echo "The site-shots health gate (real Chromium, 1440 and 390 wide, light and dark) against the live site:"
        echo ""
        jq -r '.problems[] | "- " + .' "$HD/health.json" 2>/dev/null | cut -c1-600 | head -20
        FAILED_REQ="$(jq -r '[.checks[].failedRequests[]?] | unique | .[:10][] | "- " + .' "$HD/health.json" 2>/dev/null || true)"
        if [ -n "$FAILED_REQ" ]; then
          echo ""
          echo "Failed requests:"
          echo ""
          echo "$FAILED_REQ"
        fi
        echo ""
        echo "Screenshots and the full report: the \`site-health-${R}\` artifact of the run above."
        echo ""
        echo "This issue stays open until a weekly check finds ${URL} healthy, which closes it automatically."
        footer
      } >"$B"
      report_issue fail site-health "Automated report: a live website fails the health gate" "$TITLE" "$R" "$B"
    elif [ "$HS" = "healthy" ]; then
      {
        echo "✅ Recovered: ${URL} passes the health gate again."
        echo ""
        echo "- **Run:** ${RUN_URL}"
        echo "- **Time:** ${NOW_UTC}"
        footer
      } >"$B"
      report_issue ok site-health "" "$TITLE" "$R" "$B"
    fi
  fi
done <<<"$REPOS"

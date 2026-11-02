#!/usr/bin/env bash
# Copyright 2026 ROKCT INTELLIGENCE (PTY) LTD
#
# Find the Next.js site shells in an org: active (not archived), not a fork,
# owned by the org itself, and carrying all three of
#   scripts/compose.sh, .rokct/lock.json, and a package.json that depends on
#   next (dependencies or devDependencies).
#
# It also lists the org's live SITES for the weekly health check: every
# shell above plus any other active repo with a .rokct/showcase.json card.
# A site's live URL is the card's `url`, else the repo's homepage.
#
# Usage: discover.sh <shells.json> <sites.json> [<skipped.tsv>]
#   <shells.json>  [{"repo":"name","branch":"main"}, ...]
#   <sites.json>   [{"repo":"name","url":"https://..."}, ...] (url may be "")
#   <skipped.tsv>  one "name<TAB>reason" line per repo that is not a shell
#
# Environment:
#   ORG        org to scan (default RokctAI)
#   GH_TOKEN   token for the API (optional for public repos)
#   ONLY_REPO  optional: check just this one repo name (or owner/name)
#   REPOS_TSV  optional: a file of repo names (one per line) to check instead
#              of listing the org (local dry runs)
#   API_URL    default https://api.github.com
set -euo pipefail

USAGE="usage: discover.sh <shells.json> <sites.json> [<skipped.tsv>]"
OUT="${1:?$USAGE}"
SITES_OUT="${2:?$USAGE}"
SKIPPED="${3:-/dev/null}"
ORG="${ORG:-RokctAI}"
API_URL="${API_URL:-https://api.github.com}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

: >"$SKIPPED"
REPOS="$WORK/repos.tsv"
BASE_CURL=(curl -sS --retry 3 --retry-delay 2)
if [ -n "${GH_TOKEN:-}" ]; then
  BASE_CURL+=(-H "Authorization: Bearer $GH_TOKEN")
fi
CURL=("${BASE_CURL[@]}" -H "Accept: application/vnd.github+json")
RAW_CURL=("${BASE_CURL[@]}" -H "Accept: application/vnd.github.raw")

ROW='.[] | [.name, (.default_branch // "main"), (.archived|tostring), (.fork|tostring), .owner.login, (.homepage // "")] | @tsv'
: >"$WORK/all.tsv"

# One repo's metadata appended to all.tsv; fails loudly when unreadable.
add_repo() {
  "${CURL[@]}" -o "$WORK/one.json" "$API_URL/repos/$ORG/$1"
  if ! jq -e '.name' "$WORK/one.json" >/dev/null 2>&1; then
    echo "::error::cannot read $ORG/$1: $(jq -r '.message // "unknown error"' "$WORK/one.json" 2>/dev/null)" >&2
    return 1
  fi
  jq -r "[.] | $ROW" "$WORK/one.json" >>"$WORK/all.tsv"
}

if [ -n "${ONLY_REPO:-}" ]; then
  NAME="${ONLY_REPO#*/}"
  if [ "$NAME" != "$ONLY_REPO" ] && [ "${ONLY_REPO%%/*}" != "$ORG" ]; then
    echo "::error::repo '$ONLY_REPO' is not in $ORG; only $ORG repos are refreshed." >&2
    exit 1
  fi
  add_repo "$NAME"
elif [ -n "${REPOS_TSV:-}" ]; then
  while IFS=$'\t' read -r NAME _; do
    [ -n "$NAME" ] || continue
    add_repo "$NAME" || printf '%s\tunreadable\n' "$NAME" >>"$SKIPPED"
  done <"$REPOS_TSV"
else
  PAGE=1
  while :; do
    "${CURL[@]}" -o "$WORK/page.json" "$API_URL/orgs/$ORG/repos?per_page=100&page=$PAGE"
    COUNT="$(jq 'if type == "array" then length else -1 end' "$WORK/page.json" 2>/dev/null || echo -1)"
    if [ "$COUNT" -lt 0 ]; then
      echo "::error::could not list $ORG repositories: $(jq -r '.message // "unknown error"' "$WORK/page.json" 2>/dev/null)" >&2
      exit 1
    fi
    [ "$COUNT" -eq 0 ] && break
    jq -r "$ROW" "$WORK/page.json" >>"$WORK/all.tsv"
    [ "$COUNT" -lt 100 ] && break
    PAGE=$((PAGE + 1))
  done
fi

# Never touch archived repos, forks, or anything not owned by the org itself
# (frappenize/* forks included).
: >"$REPOS"
while IFS=$'\t' read -r NAME BRANCH ARCHIVED FORK OWNER HOMEPAGE; do
  [ -n "$NAME" ] || continue
  if [ "$OWNER" != "$ORG" ]; then
    printf '%s\tnot owned by %s\n' "$NAME" "$ORG" >>"$SKIPPED"
  elif [ "$ARCHIVED" = "true" ]; then
    printf '%s\tarchived\n' "$NAME" >>"$SKIPPED"
  elif [ "$FORK" = "true" ]; then
    printf '%s\tfork\n' "$NAME" >>"$SKIPPED"
  else
    printf '%s\t%s\t%s\n' "$NAME" "$BRANCH" "$HOMEPAGE" >>"$REPOS"
  fi
done <"$WORK/all.tsv"

# HTTP status of one file on a branch ("200" when it exists).
file_status() {
  "${RAW_CURL[@]}" -o "$WORK/file" -w '%{http_code}' \
    "$API_URL/repos/$ORG/$1/contents/$3?ref=$2" || echo 000
}

# 0 when the repo is a Next.js site shell; otherwise logs why to $SKIPPED.
is_shell() {
  local name="$1" branch="$2" code
  code="$(file_status "$name" "$branch" scripts/compose.sh)"
  if [ "$code" != "200" ]; then
    printf '%s\tno scripts/compose.sh (HTTP %s)\n' "$name" "$code" >>"$SKIPPED"
    return 1
  fi
  code="$(file_status "$name" "$branch" .rokct/lock.json)"
  if [ "$code" != "200" ]; then
    printf '%s\tno .rokct/lock.json (HTTP %s)\n' "$name" "$code" >>"$SKIPPED"
    return 1
  fi
  code="$(file_status "$name" "$branch" package.json)"
  if [ "$code" != "200" ]; then
    printf '%s\tno package.json (HTTP %s)\n' "$name" "$code" >>"$SKIPPED"
    return 1
  fi
  if ! jq -e '((.dependencies // {}) + (.devDependencies // {})) | has("next")' "$WORK/file" >/dev/null 2>&1; then
    printf '%s\tpackage.json does not depend on next\n' "$name" >>"$SKIPPED"
    return 1
  fi
}

: >"$WORK/shells.tsv"
: >"$WORK/sites.tsv"
while IFS=$'\t' read -r NAME BRANCH HOMEPAGE; do
  # Live URL: the showcase card's url, else the repo homepage.
  URL=""
  HAS_CARD=false
  if [ "$(file_status "$NAME" "$BRANCH" .rokct/showcase.json)" = "200" ]; then
    HAS_CARD=true
    URL="$(jq -r '.url // empty | select(type == "string")' "$WORK/file" 2>/dev/null || true)"
  fi
  [ -n "$URL" ] || URL="$HOMEPAGE"
  case "$URL" in https://* | http://*) ;; *) URL="" ;; esac

  if ! is_shell "$NAME" "$BRANCH"; then
    if [ "$HAS_CARD" = "true" ]; then
      printf '%s\t%s\n' "$NAME" "$URL" >>"$WORK/sites.tsv"
    fi
    continue
  fi
  printf '%s\t%s\n' "$NAME" "$BRANCH" >>"$WORK/shells.tsv"
  printf '%s\t%s\n' "$NAME" "$URL" >>"$WORK/sites.tsv"
done <"$REPOS"

jq -R -s -c 'split("\n") | map(select(length > 0) | split("\t") | {repo: .[0], branch: .[1]})' \
  "$WORK/shells.tsv" >"$OUT"
echo "Site shells in $ORG: $(jq -r 'map(.repo) | join(", ") | if . == "" then "(none)" else . end' "$OUT")"
jq -R -s -c 'split("\n") | map(select(length > 0) | split("\t") | {repo: .[0], url: (.[1] // "")})' \
  "$WORK/sites.tsv" >"$SITES_OUT"
echo "Live sites to health-check: $(jq -r 'map(.repo + " " + (if .url == "" then "(no URL)" else .url end)) | join(", ") | if . == "" then "(none)" else . end' "$SITES_OUT")"

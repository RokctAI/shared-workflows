#!/usr/bin/env bash
# Copyright 2026 ROKCT INTELLIGENCE (PTY) LTD
#
# Publish one shell's refresh (made by refresh.sh) as ONE pull request from
# the robot's own branch, and merge it only on a green build.
#
# Usage: publish.sh <shell checkout> <result dir>
#
# Branch: $BRANCH (default rokct/site-refresh). It is only ever appended to,
# never force-pushed: the new commit carries the refreshed tree and has the
# branch's previous head AND the base branch's head as parents (main merged
# in), so the push is always a fast-forward and the PR diff is exactly
# "main + this refresh". If an open PR's branch carries a commit from a
# person, the branch is left alone and reported.
#
# Merge safety, per repo:
#   armed  - the base branch REQUIRES the "Compose Offline + Build (Vercel
#            parity)" check (branch protection or a ruleset) and the repo
#            allows auto-merge: the PR is opened ready and GitHub auto-merge
#            is armed, so GitHub itself merges only once required checks pass.
#   gated  - anything else (no protection, or parity not among the required
#            checks). Auto-merge there would merge at once, and some shells'
#            merge.yml arms it for any ready PR, so the PR is opened as a
#            DRAFT (GitHub refuses to merge or auto-merge a draft). This
#            script then waits for the shell's build workflow run on the PR's
#            head commit; only if that run succeeded AND its parity job
#            succeeded does it mark the PR ready and merge it, pinned to that
#            exact head commit (--match-head-commit). Red, missing or slow
#            builds leave the draft open and are reported. Never merges red.
#
# Writes status/detail/pr into <result dir> (status: dry-run, pr-open,
# auto-merge-armed, merged, failed, skipped).
#
# Environment:
#   GH_TOKEN        token that can push and open/merge PRs (MONOREPO_PAT)
#   REPO            owner/name
#   BASE            base branch (the repo's default branch)
#   BRANCH          default rokct/site-refresh
#   DRY_RUN         true: read-only, report what would happen
#   WAIT_MINUTES    gated mode: how long to wait for the build (default 90)
#   NO_RUN_MINUTES  gated mode: give up if no build run appears (default 20)
#   BUILD_WORKFLOW  default build.yml
#   PARITY_JOB      regex for the parity job name (default "Vercel parity")
#   RUN_URL         link to this Actions run, for the PR body
set -euo pipefail

SITE="$(cd "${1:?usage: publish.sh <shell checkout> <result dir>}" && pwd)"
OUT="$(cd "${2:?usage: publish.sh <shell checkout> <result dir>}" && pwd)"
: "${REPO:?REPO is required}" "${BASE:?BASE is required}"
BRANCH="${BRANCH:-rokct/site-refresh}"
DRY_RUN="${DRY_RUN:-false}"
WAIT_MINUTES="${WAIT_MINUTES:-90}"
NO_RUN_MINUTES="${NO_RUN_MINUTES:-20}"
BUILD_WORKFLOW="${BUILD_WORKFLOW:-build.yml}"
PARITY_JOB="${PARITY_JOB:-Vercel parity}"
TITLE="Refresh site building blocks"
OWNER="${REPO%%/*}"

finish() {
  printf '%s\n' "$1" >"$OUT/status"
  printf '%s\n' "$2" >"$OUT/detail"
  echo "[$1] $2"
  exit 0
}
say() {
  echo "[*] $*"
}
# shellcheck disable=SC2329 # invoked by the EXIT trap
on_exit() {
  local rc=$?
  if [ "$rc" -ne 0 ]; then
    echo failed >"$OUT/status"
    echo "publishing stopped unexpectedly (exit $rc); see the job log. Nothing was merged." >"$OUT/detail"
  fi
}
trap on_exit EXIT

CANDIDATE="$(cat "$OUT/candidate")"
cd "$SITE"
TREE="$(git rev-parse "$CANDIDATE^{tree}")"
BASE_SHA="$(git rev-parse "$CANDIDATE^")"
MESSAGE="$(git log -1 --format=%B "$CANDIDATE")"

# --- repo settings and the merge mode -------------------------------------
gh api "repos/$REPO" >"$OUT/repo.json"
METHOD=rebase
if jq -e '.allow_squash_merge' "$OUT/repo.json" >/dev/null; then
  METHOD=squash
elif jq -e '.allow_merge_commit' "$OUT/repo.json" >/dev/null; then
  METHOD=merge
fi

REQUIRED="$({
  gh api "repos/$REPO/branches/$BASE" \
    --jq '(.protection.required_status_checks.contexts // [])[], ((.protection.required_status_checks.checks // [])[] | .context)' 2>/dev/null || true
  gh api "repos/$REPO/rules/branches/$BASE" \
    --jq '.[] | select(.type == "required_status_checks") | .parameters.required_status_checks[].context' 2>/dev/null || true
} | sort -u)"
MODE=gated
if grep -qE "$PARITY_JOB" <<<"$REQUIRED" && jq -e '.allow_auto_merge' "$OUT/repo.json" >/dev/null; then
  MODE=armed
fi
say "$REPO: merge mode $MODE (required checks on $BASE: ${REQUIRED:-none}; merge method $METHOD)"
printf '%s\n' "$MODE" >"$OUT/mode"

# --- the open PR and the branch -------------------------------------------
PR_JSON="$(gh api "repos/$REPO/pulls?state=open&head=$OWNER:$BRANCH&per_page=10" --jq 'map(select(.head.repo.full_name == "'"$REPO"'")) | first // empty')"
PR_NUM=""
PR_DRAFT=""
PR_ARMED=""
if [ -n "$PR_JSON" ]; then
  PR_NUM="$(jq -r .number <<<"$PR_JSON")"
  PR_DRAFT="$(jq -r .draft <<<"$PR_JSON")"
  PR_ARMED="$(jq -r '.auto_merge != null' <<<"$PR_JSON")"
  if [ "$(jq -r .base.ref <<<"$PR_JSON")" != "$BASE" ]; then
    finish skipped "open PR #$PR_NUM from $BRANCH targets $(jq -r .base.ref <<<"$PR_JSON"), not $BASE; left alone"
  fi
  printf '%s\n' "$(jq -r .html_url <<<"$PR_JSON")" >"$OUT/pr"
  say "open PR #$PR_NUM (draft=$PR_DRAFT, auto-merge armed=$PR_ARMED)"
fi

BRANCH_SHA="$(git ls-remote --heads origin "refs/heads/$BRANCH" | cut -f1)"
NEW_SHA=""
if [ -n "$BRANCH_SHA" ]; then
  COMPARE="$(gh api "repos/$REPO/compare/$BASE_SHA...$BRANCH_SHA")"
  if [ -n "$PR_NUM" ]; then
    HUMANS="$(jq -r '[.commits[] | select(((.author.login // "") | endswith("[bot]") | not)
        and ((.commit.author.email // "") | endswith("[bot]@users.noreply.github.com") | not))
      | (.author.login // .commit.author.name)] | unique | join(", ")' <<<"$COMPARE")"
    if [ -n "$HUMANS" ]; then
      finish skipped "PR #$PR_NUM's branch has commits from $HUMANS; the robot does not overwrite a person's work"
    fi
  fi
  git fetch -q --depth 1 origin "refs/heads/$BRANCH"
  BEHIND="$(jq -r .behind_by <<<"$COMPARE")"
  if [ "$(git rev-parse "$BRANCH_SHA^{tree}")" = "$TREE" ] && [ "$BEHIND" = "0" ]; then
    NEW_SHA="$BRANCH_SHA"
    say "$BRANCH already carries this refresh on top of $BASE; nothing to push"
  else
    case "$(jq -r .status <<<"$COMPARE")" in
    behind | identical) PARENTS=(-p "$BASE_SHA") ;;
    *) PARENTS=(-p "$BRANCH_SHA" -p "$BASE_SHA") ;;
    esac
    NEW_SHA="$(git commit-tree "$TREE" "${PARENTS[@]}" -m "$MESSAGE")"
  fi
else
  NEW_SHA="$CANDIDATE"
fi

BODY="$OUT/pr-body.md"
{
  echo "**Before:** the live site builds from the building blocks (SDKs) pinned in \`.rokct/lock.json\` and \`.rokct/cache/\`, some of which have newer versions upstream."
  echo ""
  echo "**After:** merging this pins the latest versions; the next deploy uses them."
  echo ""
  if [ "$(wc -l <"$OUT/versions.md")" -gt 2 ]; then
    cat "$OUT/versions.md"
  else
    echo "No building block changed version; the refresh updated supporting files (cache contents, lockfile or ignore list)."
  fi
  echo ""
  if [ -s "$OUT/repaired" ]; then
    echo "Also commits the composed copy of $(cat "$OUT/repaired"): the new building blocks install a different version of these tracked files, so the composed copy is committed byte-identical (the same fix as hosting 8759bf2)."
    echo ""
  fi
  echo "**How:** opened by the weekly site refresh (\`site-refresh.yml\` in RokctAI/shared-workflows), which ran this repo's own \`scripts/compose.sh refresh\` and then proved the result composes offline from the committed cache with zero drift."
  if [ "$MODE" = armed ]; then
    echo "Auto-merge is armed: GitHub merges this only after the required checks, including **Compose Offline + Build (Vercel parity)**, pass."
  else
    echo "This repo does not require the parity check, so this PR starts as a draft. The robot merges it only after this repo's \`$BUILD_WORKFLOW\` run on the PR's exact head commit succeeds, including **Compose Offline + Build (Vercel parity)**. A red build is never merged; the draft stays open and the run summary says why."
  fi
  echo ""
  echo "One PR per site: next week's refresh updates this one. ${RUN_URL:+Run: $RUN_URL}"
} >"$BODY"

if [ "$DRY_RUN" = "true" ]; then
  WHAT="open a draft PR"
  if [ -n "$PR_NUM" ]; then
    WHAT="update PR #$PR_NUM"
  elif [ "$MODE" = armed ]; then
    WHAT="open a ready PR"
  fi
  finish dry-run "would push $BRANCH and $WHAT ($MODE); $(cat "$OUT/detail" 2>/dev/null || true)"
fi

# --- make sure nothing merges early, then push ----------------------------
if [ -n "$PR_NUM" ] && [ "$MODE" = gated ]; then
  if [ "$PR_ARMED" = "true" ]; then
    gh pr merge "$PR_NUM" --repo "$REPO" --disable-auto
    say "disarmed auto-merge on PR #$PR_NUM (this repo does not require the parity check)"
  fi
  if [ "$PR_DRAFT" != "true" ]; then
    gh pr ready "$PR_NUM" --repo "$REPO" --undo
    say "PR #$PR_NUM back to draft until its build is green"
  fi
fi

if [ "$NEW_SHA" != "$BRANCH_SHA" ]; then
  git push -q origin "$NEW_SHA:refs/heads/$BRANCH"
  say "pushed $NEW_SHA to $BRANCH"
fi

if [ -n "$PR_NUM" ]; then
  gh pr edit "$PR_NUM" --repo "$REPO" --title "$TITLE" --body-file "$BODY" >/dev/null
  PR_URL="$(cat "$OUT/pr")"
else
  DRAFT_FLAG=()
  [ "$MODE" = gated ] && DRAFT_FLAG=(--draft)
  PR_URL="$(gh pr create --repo "$REPO" --base "$BASE" --head "$BRANCH" --title "$TITLE" --body-file "$BODY" "${DRAFT_FLAG[@]}")"
  PR_NUM="${PR_URL##*/}"
  printf '%s\n' "$PR_URL" >"$OUT/pr"
fi
say "PR: $PR_URL"

if [ "$MODE" = armed ]; then
  gh pr merge "$PR_NUM" --repo "$REPO" --auto "--$METHOD" --match-head-commit "$NEW_SHA"
  finish auto-merge-armed "auto-merge armed; GitHub merges once the required checks pass"
fi

# --- gated: wait for this repo's build on the exact head, merge on green ---
START="$(date +%s)"
SEEN_AT="$START"
LAST_HEAD=""
while :; do
  NOW="$(date +%s)"
  PR_NOW="$(gh api "repos/$REPO/pulls/$PR_NUM" --jq '"\(.head.sha) \(.state) \(.merged)"')"
  read -r HEAD STATE MERGED <<<"$PR_NOW"
  if [ "$STATE" != "open" ]; then
    if [ "$MERGED" = "true" ]; then
      finish merged "PR #$PR_NUM was merged while the robot waited"
    fi
    finish skipped "PR #$PR_NUM was closed while the robot waited"
  fi
  if [ "$HEAD" != "$LAST_HEAD" ]; then
    [ -n "$LAST_HEAD" ] && say "PR head moved to $HEAD; waiting for its build instead"
    LAST_HEAD="$HEAD"
    SEEN_AT="$NOW"
  fi
  RUN="$(gh api "repos/$REPO/actions/workflows/$BUILD_WORKFLOW/runs?head_sha=$HEAD&per_page=20" \
    --jq '[.workflow_runs[] | select(.event == "pull_request")] | sort_by(.created_at) | last // empty | "\(.id)\t\(.status)\t\(.conclusion // "")\t\(.html_url)"' 2>/dev/null || true)"
  if [ -z "$RUN" ]; then
    if [ $((NOW - SEEN_AT)) -ge $((NO_RUN_MINUTES * 60)) ]; then
      finish pr-open "no $BUILD_WORKFLOW run started for ${HEAD:0:7} within ${NO_RUN_MINUTES}m; left as a draft (not merged)"
    fi
  else
    IFS=$'\t' read -r RUN_ID RUN_STATUS RUN_CONCLUSION RUN_URL_B <<<"$RUN"
    if [ "$RUN_STATUS" = "completed" ]; then
      if [ "$RUN_CONCLUSION" != "success" ]; then
        finish failed "build $RUN_CONCLUSION on ${HEAD:0:7} ($RUN_URL_B); PR left as a draft, not merged"
      fi
      PARITY="$(gh api --paginate "repos/$REPO/actions/runs/$RUN_ID/jobs?per_page=100" \
        --jq ".jobs[] | select(.name | test(\"$PARITY_JOB\")) | .conclusion")"
      if [ -z "$PARITY" ]; then
        finish pr-open "build passed but has no \"$PARITY_JOB\" job ($RUN_URL_B); left as a draft (not merged)"
      fi
      if grep -qvx success <<<"$PARITY"; then
        finish failed "parity job did not succeed ($(tr '\n' ' ' <<<"$PARITY")) on ${HEAD:0:7} ($RUN_URL_B); not merged"
      fi
      say "build and parity green on ${HEAD:0:7} ($RUN_URL_B); merging"
      gh pr ready "$PR_NUM" --repo "$REPO"
      if gh pr merge "$PR_NUM" --repo "$REPO" "--$METHOD" --match-head-commit "$HEAD"; then
        finish merged "build green ($RUN_URL_B); merged"
      fi
      finish failed "build green but the merge was refused (conflict or head moved?); PR #$PR_NUM left open"
    fi
  fi
  if [ $((NOW - START)) -ge $((WAIT_MINUTES * 60)) ]; then
    finish pr-open "build still running after ${WAIT_MINUTES}m; left as a draft (the next run merges it once green)"
  fi
  sleep 60
done

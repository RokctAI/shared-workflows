#!/usr/bin/env bash
# Copyright 2026 ROKCT INTELLIGENCE (PTY) LTD
#
# Refresh one Next.js site shell's committed SDK pins, locally. Never pushes.
#
# Usage: refresh.sh <shell checkout> <result dir>
#
# In <shell checkout> (a clean checkout of the base branch) this runs the
# shell's own `scripts/compose.sh refresh`, stages exactly what that refresh
# says to commit, and decides whether anything meaningful moved. When it did,
# it records a candidate commit (parent: the checked-out HEAD) and proves it
# the way the shell's "Compose Offline + Build (Vercel parity)" job starts:
# a fresh worktree of that commit must compose OFFLINE from the committed
# cache and leave `git status` empty (zero drift). The build itself is left
# to the shell's own build.yml on the pull request.
#
# Writes into <result dir>:
#   status         up-to-date | changed | failed
#   detail         one line for the run summary
#   candidate      candidate commit sha (status=changed only)
#   versions.md    Before/After SDK table (markdown)
#   refresh.log    output of compose.sh refresh
#   verify.log     output of the offline compose
#
# Environment: MONOREPO_PAT (read by compose.sh refresh for the SDK clones).
set -euo pipefail

SITE="$(cd "${1:?usage: refresh.sh <shell checkout> <result dir>}" && pwd)"
OUT="${2:?usage: refresh.sh <shell checkout> <result dir>}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
STATE_REL=".rokct/cache/install_state.json"

finish() {
  printf '%s\n' "$1" >"$OUT/status"
  printf '%s\n' "$2" >"$OUT/detail"
  echo "[$1] $2"
  exit 0
}

# Any unexpected error still leaves a result behind for the run summary.
# shellcheck disable=SC2329 # invoked by the EXIT trap
on_exit() {
  local rc=$?
  if [ "$rc" -ne 0 ] && [ ! -s "$OUT/status" ]; then
    echo failed >"$OUT/status"
    echo "refresh.sh stopped unexpectedly (exit $rc)" >"$OUT/detail"
  fi
}
trap on_exit EXIT

cd "$SITE"
BASE_SHA="$(git rev-parse HEAD)"
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  finish failed "checkout was not clean before the refresh"
fi
cp .rokct/lock.json "$OUT/lock.before.json"

echo "::group::compose.sh refresh"
set +e
bash scripts/compose.sh refresh 2>&1 | tee "$OUT/refresh.log"
RC="${PIPESTATUS[0]}"
set -e
echo "::endgroup::"
if [ "$RC" -ne 0 ]; then
  LAST="$(grep -E '^\[!\]' "$OUT/refresh.log" | tail -1 | cut -c1-200 || true)"
  finish failed "compose.sh refresh exited $RC${LAST:+: $LAST}"
fi
if ! jq empty .rokct/lock.json 2>/dev/null; then
  finish failed "compose.sh refresh left an invalid .rokct/lock.json"
fi
cp .rokct/lock.json "$OUT/lock.after.json"

# The refresh stages .rokct/cache and .rokct/lock.json itself (git add -f).
# Stage the other files it names in its "Review and commit" line, but only
# ones the shell already tracks: a refresh must not start committing new
# top-level files.
for f in package.json package-lock.json pnpm-lock.yaml .gitignore composer.json; do
  if git ls-files --error-unmatch -- "$f" >/dev/null 2>&1; then
    git add -- "$f"
  fi
done
# install_state.json is the installers' record of THIS working tree; it must
# never be committed (older compose.sh copies force-added it), and neither
# must bytecode.
git rm -r -q --cached --ignore-unmatch -- "$STATE_REL" >/dev/null
git ls-files -z --cached -- '.rokct/cache/' | grep -zE '(^|/)__pycache__/|\.pyc$' |
  xargs -0 -r git rm -q --cached -- >/dev/null || true
NOTE=""
if [ -e "$STATE_REL" ] && ! git check-ignore -q -- "$STATE_REL"; then
  NOTE=" (warning: $STATE_REL is not gitignored in this shell)"
fi

# Before/After table, by SDK name.
jq -r -n --slurpfile b "$OUT/lock.before.json" --slurpfile a "$OUT/lock.after.json" '
  def pins(l): (l.sdks // []) | map({key: .name, value: "\(.version // "?") (\((.commit // "?")[0:7]))"}) | from_entries;
  def vers(l): (l.sdks // []) | map({key: .name, value: ((.content_sha256 // "") + (.version // ""))}) | from_entries;
  (pins($b[0])) as $pb | (pins($a[0])) as $pa | (vers($b[0])) as $vb | (vers($a[0])) as $va |
  "| Building block | Before | After |",
  "| --- | --- | --- |",
  ( ([$pb, $pa] | map(keys) | add | unique)[] as $k
    | select($vb[$k] != $va[$k])
    | "| `\($k)` | \($pb[$k] // "(not used)") | \($pa[$k] // "(removed)") |" ),
  ( if ($b[0].protocol.files // {}) != ($a[0].protocol.files // {})
    then "| composer (The-Rokct-Protocol) | \(($b[0].protocol.ref // "?")[0:7]) | \(($a[0].protocol.ref // "?")[0:7]) |"
    else empty end )
' >"$OUT/versions.md"

if git diff --cached --quiet; then
  finish up-to-date "already on the latest building blocks$NOTE"
fi

# A lock.json whose only difference is bookkeeping (the protocol commit it
# was vendored from, or an SDK repo commit whose cached content and version
# did not change) is not worth a deploy. Everything else is.
normalize() {
  jq -S 'del(.protocol.ref) | .sdks = ((.sdks // []) | map(del(.commit)))' "$1"
}
OTHER="$(git diff --cached --name-only | grep -vxF '.rokct/lock.json' || true)"
if [ -z "$OTHER" ] && [ "$(normalize "$OUT/lock.before.json")" = "$(normalize "$OUT/lock.after.json")" ]; then
  finish up-to-date "already on the latest building blocks (only pin bookkeeping moved)$NOTE"
fi

CHANGES="$(jq -r -n --slurpfile b "$OUT/lock.before.json" --slurpfile a "$OUT/lock.after.json" '
  ($b[0].sdks // [] | map({key: .name, value: (.version // "?")}) | from_entries) as $vb |
  [ ($a[0].sdks // [])[] | select($vb[.name] != (.version // "?"))
    | "\(.name) \($vb[.name] // "new") -> \(.version // "?")" ] | join(", ")')"
TREE="$(git write-tree)"
CANDIDATE="$(git commit-tree "$TREE" -p "$BASE_SHA" \
  -m "chore: refresh site building blocks${CHANGES:+ ($CHANGES)}" \
  -m "Generated by scripts/compose.sh refresh (site-refresh.yml in RokctAI/shared-workflows).")"

# Pre-gate: compose the candidate offline, in a fresh worktree, exactly like
# the deploy does, and require zero drift.
#
# One kind of drift is repaired instead of failed: a tracked file that an
# installer writes (listed in that compose's install_state.json). When an SDK
# changes such a destination, the host's committed copy goes stale and every
# offline compose rewrites it. The accepted fix (hosting 8759bf2, hosting
# #36) is to commit the composed file byte-identical, so the refresh does
# exactly that and proves zero drift again. Anything else (an untracked or
# deleted path, a tracked file no installer wrote, or drift still there
# after the repair) fails, and nothing is pushed.
VERIFY="$(mktemp -d)"
cleanup_verify() {
  git worktree remove --force "$VERIFY/tree" 2>/dev/null || true
  rm -rf "$VERIFY"
}

# verify_offline <commit>: sets VRC (compose exit) and DRIFT (porcelain);
# leaves the composed worktree at $VERIFY/tree.
verify_offline() {
  git worktree remove --force "$VERIFY/tree" 2>/dev/null || true
  git worktree add -q --detach "$VERIFY/tree" "$1"
  set +e
  (
    cd "$VERIFY/tree" || exit 1
    env -u POSTGRES_URL -u POSTGRES_URL_NON_POOLING -u AUTH_SECRET \
      -u ROKCT_BASE_URL -u NEXT_PUBLIC_ROKCT_BASE_URL \
      -u MONOREPO_PAT -u GH_TOKEN -u GITHUB_TOKEN \
      bash scripts/compose.sh
  ) >>"$OUT/verify.log" 2>&1
  VRC=$?
  set -e
  DRIFT="$(git -C "$VERIFY/tree" status --porcelain)"
}

fail_verify() {
  cleanup_verify
  if [ "$VRC" -ne 0 ]; then
    LAST="$(grep -E '^\[!\]' "$OUT/verify.log" | tail -1 | cut -c1-200 || true)"
    finish failed "the refreshed pins do not compose offline (exit $VRC)${LAST:+: $LAST}"
  fi
  printf '%s\n' "$DRIFT" >>"$OUT/verify.log"
  finish failed "$1: $(head -3 <<<"$DRIFT" | tr '\n' ' ')"
}

: >"$OUT/verify.log"
verify_offline "$CANDIDATE"
if [ "$VRC" -ne 0 ]; then
  fail_verify "offline compose failed"
fi

REPAIRED=""
if [ -n "$DRIFT" ]; then
  DESTS="$(jq -r '(.packages // {}) | to_entries[] | (.value.files // {}) | keys[]' \
    "$VERIFY/tree/$STATE_REL" 2>/dev/null | sort -u || true)"
  PATHS=""
  while IFS= read -r LINE; do
    [ -n "$LINE" ] || continue
    REL="${LINE:3}"
    if [ "${LINE:0:2}" != " M" ] || ! grep -qxF -- "$REL" <<<"$DESTS"; then
      fail_verify "an offline compose of the refreshed pins changed files that are not installer destinations (zero-drift check)"
    fi
    PATHS+="$REL"$'\n'
  done <<<"$DRIFT"

  # Commit the composed copies byte-identical, then prove zero drift again.
  while IFS= read -r REL; do
    [ -n "$REL" ] || continue
    cp -p -- "$VERIFY/tree/$REL" "$SITE/$REL"
    git add -- "$REL"
    echo "[*] $REL: committing the composed copy (its installer destination changed upstream)."
  done <<<"$PATHS"
  REPAIRED="$(sed '/^$/d' <<<"$PATHS" | paste -sd ',' - | sed 's/,/, /g')"
  printf '%s\n' "$REPAIRED" >"$OUT/repaired"
  TREE="$(git write-tree)"
  CANDIDATE="$(git commit-tree "$TREE" -p "$BASE_SHA" \
    -m "chore: refresh site building blocks${CHANGES:+ ($CHANGES)}" \
    -m "Generated by scripts/compose.sh refresh (site-refresh.yml in RokctAI/shared-workflows). Composed copies committed for changed installer destinations: $REPAIRED.")"
  verify_offline "$CANDIDATE"
  if [ "$VRC" -ne 0 ]; then
    fail_verify "offline compose failed after committing the composed installer destinations"
  fi
  if [ -n "$DRIFT" ]; then
    fail_verify "drift remained after committing the composed installer destinations (zero-drift check)"
  fi
fi
cleanup_verify

printf '%s\n' "$CANDIDATE" >"$OUT/candidate"
finish changed "${CHANGES:-building blocks changed}${REPAIRED:+; committed the composed $REPAIRED}$NOTE"

#!/usr/bin/env bash
# Copyright (c) 2026, Rokct Intelligence (pty) Ltd.
# For license information, please see LICENSE.
#
# Render the repo's screens headlessly and compose the review strip.
#
# ONE implementation, called from two lanes, so the gate and the manual
# button can never drift apart:
#
#   * .github/workflows/universal-render-strip.yml - the standalone
#     workflow_dispatch lane (the manual button).
#   * .github/workflows/universal-guided-tour.yml - the gating step the tour
#     runs before it burns forty minutes of emulator time.
#
# It assumes the toolchain is already installed and the SDK modules are
# already composed: both callers run Setup Java -> Setup Flutter -> compose
# -> pub get -> build_runner BEFORE this, and that order is load-bearing (see
# the comment on universal-render-strip.yml's compose step). Nothing here
# clones, composes or commits - it renders what is on disk and writes one
# HTML file.
#
# Environment contract (every value has a default except the tools dir):
#
#   RENDER_TOOLS_DIR    required. Path to a shared-workflows checkout; the
#                       composer is read from
#                       $RENDER_TOOLS_DIR/scripts/render/compose_strip.py.
#   RENDER_TEST         the render widget test to run.
#   STRIP_CONFIG        strip config consumed by compose_strip.py.
#   RENDER_OUT_DIR      where the test writes its PNG + rect JSON.
#   RENDER_OUTPUT_FILE  path of the composed page to write. May name a
#                       directory that does not exist yet; it is created.
#   RENDER_SUFFIX       exported for the test, so two checkouts can be told
#                       apart.
#   DART_DEFINES        space-separated KEY=VALUE pairs, one --dart-define
#                       each. IS_DEMO=true is what makes the SDKs register
#                       their demo fixtures instead of real HTTP
#                       repositories - without it the render is of an empty,
#                       broken screen.
#   RENDER_LOG          where to tee the `flutter test` output.
#
# Callers decide whether a repo HAS a harness; this script fails loudly when
# asked to render one that is not there, because by then the caller has
# already claimed it exists.

set -uo pipefail

fail() {
  echo "::error::$*"
  exit 1
}

RENDER_TOOLS_DIR="${RENDER_TOOLS_DIR:-}"
RENDER_TEST="${RENDER_TEST:-test/render/render_screen_test.dart}"
STRIP_CONFIG="${STRIP_CONFIG:-test/render/strip.json}"
RENDER_OUT_DIR="${RENDER_OUT_DIR:-out}"
RENDER_OUTPUT_FILE="${RENDER_OUTPUT_FILE:-render-strip.html}"
# `-` not `:-`: an EXPLICITLY empty DART_DEFINES means "no defines", the
# same as passing an empty dart-defines input to the workflow. Only an
# UNSET variable falls back to the default.
DART_DEFINES="${DART_DEFINES-IS_DEMO=true}"
RENDER_LOG="${RENDER_LOG:-render_log.txt}"
# The test reads this itself; export it even when empty so a stale value from
# the runner environment cannot leak into the filenames.
export RENDER_SUFFIX="${RENDER_SUFFIX:-}"

[ -n "$RENDER_TOOLS_DIR" ] || fail "RENDER_TOOLS_DIR is not set - point it at a shared-workflows checkout."

COMPOSER="$RENDER_TOOLS_DIR/scripts/render/compose_strip.py"
[ -f "$COMPOSER" ] || fail "Composer not found at $COMPOSER - is $RENDER_TOOLS_DIR a shared-workflows checkout?"
[ -f "$RENDER_TEST" ] || fail "Render test not found at $RENDER_TEST (cwd: $PWD)."
[ -f "$STRIP_CONFIG" ] || fail "Strip config not found at $STRIP_CONFIG (see scripts/render/README.md for its shape)."

# `read -ra` rather than an unquoted `for pair in $DART_DEFINES`: the input is
# a space-separated list and word splitting is exactly what is wanted, but
# spelling it as a deliberate split keeps shellcheck honest instead of
# suppressed.
read -ra DEFINE_PAIRS <<<"$DART_DEFINES"
DEFINES=()
for pair in ${DEFINE_PAIRS[@]+"${DEFINE_PAIRS[@]}"}; do
  DEFINES+=(--dart-define="$pair")
done

echo "🖼️  Rendering $RENDER_TEST (${#DEFINES[@]} dart-define(s), suffix '${RENDER_SUFFIX}')..."
if ! flutter test ${DEFINES[@]+"${DEFINES[@]}"} "$RENDER_TEST" 2>&1 | tee "$RENDER_LOG"; then
  fail "The render test failed. This gates everything downstream: the screens do not compile or do not lay out."
fi

COUNT=$(find "$RENDER_OUT_DIR" -name '*.png' 2>/dev/null | wc -l)
[ "$COUNT" -gt 0 ] || fail "The render test produced no PNGs in $RENDER_OUT_DIR."
echo "✅ Rendered $COUNT frame(s)."

OUT_PARENT=$(dirname "$RENDER_OUTPUT_FILE")
[ "$OUT_PARENT" = "." ] || mkdir -p "$OUT_PARENT"

python3 "$COMPOSER" \
  --config "$STRIP_CONFIG" \
  --base-dir "$RENDER_OUT_DIR" \
  --out "$RENDER_OUTPUT_FILE" || fail "Composing the review strip failed."

[ -s "$RENDER_OUTPUT_FILE" ] || fail "The composer wrote no page at $RENDER_OUTPUT_FILE."
echo "✅ Review strip composed at $RENDER_OUTPUT_FILE ($(wc -c <"$RENDER_OUTPUT_FILE") bytes)."

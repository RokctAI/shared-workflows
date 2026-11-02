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
#   RENDER_SVG_DIR      where to write the per-frame SVG exports (one
#                       annotated + one clean file per frame, for dropping
#                       into a user guide or a deck). Empty disables them.
#   RENDER_SUFFIX       exported for the test, so two checkouts can be told
#                       apart.
#   DART_DEFINES        space-separated KEY=VALUE pairs, one --dart-define
#                       each. Empty by default: the render test activates
#                       the demo session itself and the SDKs' fixtures answer
#                       through DemoGatewayInterceptor.
#   RENDER_LOG          where to tee the `flutter test` output.
#   RENDER_VECTOR       `1` asks the harness for a true vector SVG of each
#                       frame too (out/<name>.vector.svg); the composer
#                       writes it as <slug>.vector.svg in RENDER_SVG_DIR with
#                       its fonts subset (needs fontTools, installed here
#                       best-effort). Default off.
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
# `-` not `:-`: an explicitly empty value turns the SVG export off.
RENDER_SVG_DIR="${RENDER_SVG_DIR-svg}"
# `-` not `:-`: an EXPLICITLY empty DART_DEFINES means "no defines", the
# same as passing an empty dart-defines input to the workflow. Only an
# UNSET variable falls back to the default.
DART_DEFINES="${DART_DEFINES-}"
RENDER_LOG="${RENDER_LOG:-render_log.txt}"
# The test reads this itself; export it even when empty so a stale value from
# the runner environment cannot leak into the filenames.
export RENDER_SUFFIX="${RENDER_SUFFIX:-}"
export RENDER_VECTOR="${RENDER_VECTOR:-0}"

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

# Screens the composed SDKs declare themselves (<sdk>/templates/render/*.render.yaml)
# become test/render/render_screens.g.dart for the shell's test to loop over.
# Nothing is generated when no SDK ships a fragment.
if [ -d "${RENDER_FRAGMENT_CACHE:-.rokct/cache}" ]; then
  python3 "$RENDER_TOOLS_DIR/scripts/render/merge_render_fragments.py" \
    --cache-dir "${RENDER_FRAGMENT_CACHE:-.rokct/cache}" \
    --out-dir "$(dirname "$RENDER_TEST")" || fail "Merging the SDK render fragments failed."
fi

echo "🖼️  Rendering $RENDER_TEST (${#DEFINES[@]} dart-define(s), suffix '${RENDER_SUFFIX}')..."
if ! flutter test ${DEFINES[@]+"${DEFINES[@]}"} "$RENDER_TEST" 2>&1 | tee "$RENDER_LOG"; then
  fail "The render test failed. This gates everything downstream: the screens do not compile or do not lay out."
fi

COUNT=$(find "$RENDER_OUT_DIR" -name '*.png' 2>/dev/null | wc -l)
[ "$COUNT" -gt 0 ] || fail "The render test produced no PNGs in $RENDER_OUT_DIR."
echo "✅ Rendered $COUNT frame(s)."

if [ "$RENDER_VECTOR" = "1" ]; then
  VECTOR_COUNT=$(find "$RENDER_OUT_DIR" -name '*.vector.svg' 2>/dev/null | wc -l)
  echo "🧭 $VECTOR_COUNT vector SVG(s) rendered."
  # Font subsetting shrinks each vector SVG ~15x. Best-effort: without
  # fontTools the SVGs keep their whole fonts and still render.
  if ! python3 -c 'import fontTools' 2>/dev/null; then
    python3 -m pip install --quiet --user fonttools 2>/dev/null ||
      python3 -m pip install --quiet --user --break-system-packages fonttools 2>/dev/null ||
      echo "::warning::fontTools unavailable; vector SVGs keep their full embedded fonts."
  fi
fi

OUT_PARENT=$(dirname "$RENDER_OUTPUT_FILE")
[ "$OUT_PARENT" = "." ] || mkdir -p "$OUT_PARENT"

COMPOSE_ARGS=(
  --config "$STRIP_CONFIG"
  --base-dir "$RENDER_OUT_DIR"
  --out "$RENDER_OUTPUT_FILE"
)
if [ -n "$RENDER_SVG_DIR" ]; then
  COMPOSE_ARGS+=(--emit-svg "$RENDER_SVG_DIR")
fi

# The composer runs the frame quality gate (frame_quality.py) before it
# writes anything: a frame that looks blank, still shows a loading spinner,
# or draws its text as block glyphs fails this step, so no page and no SVG
# is written and the tour bot has nothing broken to commit.
python3 "$COMPOSER" "${COMPOSE_ARGS[@]}" || fail "Composing the review strip failed (a refused frame is listed above: blank, loading or block-glyph renders are never written)."

[ -s "$RENDER_OUTPUT_FILE" ] || fail "The composer wrote no page at $RENDER_OUTPUT_FILE."
echo "✅ Review strip composed at $RENDER_OUTPUT_FILE ($(wc -c <"$RENDER_OUTPUT_FILE") bytes)."

if [ -n "$RENDER_SVG_DIR" ]; then
  SVG_COUNT=$(find "$RENDER_SVG_DIR" -name '*.svg' 2>/dev/null | wc -l)
  [ "$SVG_COUNT" -gt 0 ] || fail "No SVGs were written to $RENDER_SVG_DIR."
  echo "✅ $SVG_COUNT SVG(s) exported to $RENDER_SVG_DIR (annotated + clean per frame, plus <slug>.vector.svg when RENDER_VECTOR=1)."
fi

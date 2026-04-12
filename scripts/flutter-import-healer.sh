#!/usr/bin/env bash
# =============================================================================
# flutter-import-healer.sh
# Runs flutter analyze, finds undefined identifiers, locates their definitions
# inside lib/, adds missing imports, commits fixes, and exits 1 if it changed
# anything (so the pipeline reruns against clean code).
# =============================================================================
set -euo pipefail

LIB_DIR="${1:-lib}"
CHANGED=0
LOGFILE="import-healer.log"

echo "--- Import Healer ($(date)) ---" | tee "$LOGFILE"

# -----------------------------------------------------------------------------
# 1. Run flutter analyze and capture output
# -----------------------------------------------------------------------------
echo ""
echo "▶ Running flutter analyze..."
ANALYZE_OUT=$(flutter analyze --no-pub 2>&1 || true)
echo "$ANALYZE_OUT" >>"$LOGFILE"

# -----------------------------------------------------------------------------
# 2. Parse undefined identifier/class errors only
#    Format: error • Undefined class 'Foo' • lib/path/file.dart:10:5
#    We ignore errors in generated files (.g.dart, .freezed.dart, .gr.dart)
# -----------------------------------------------------------------------------
echo ""
echo "▶ Parsing errors..."

# Extract lines like:
#   error • Undefined class 'Foo' • lib/some/file.dart:12:3 • undefined_class
#   error • Undefined name 'foo' • lib/some/file.dart:12:3 • undefined_identifier
UNDEFINED_ERRORS=$(echo "$ANALYZE_OUT" | grep -E "^\s*error\s+•\s+Undefined (class|name|function|getter|setter|method|type|identifier)" || true)

if [ -z "$UNDEFINED_ERRORS" ]; then
  echo "✅ No undefined identifier errors found."
  exit 0
fi

# Use process substitution instead of a pipe so the loop runs in the current
# shell and assignments to CHANGED are visible after the loop exits.
while IFS= read -r line; do
  # Extract the identifier name (between single quotes)
  IDENTIFIER=$(echo "$line" | grep -oP "Undefined \w+ '\K[^']+")
  # Extract the file path (lib/...dart before the colon+line number)
  TARGET_FILE=$(echo "$line" | grep -oP "lib/[^\s:•]+\.dart" | head -1)

  # Skip generated files
  if echo "$TARGET_FILE" | grep -qE "\.(g|freezed|gr)\.dart$"; then
    continue
  fi

  if [ -z "$IDENTIFIER" ] || [ -z "$TARGET_FILE" ]; then
    continue
  fi

  # Skip if file doesn't exist
  if [ ! -f "$TARGET_FILE" ]; then
    continue
  fi

  echo ""
  echo "  ⚠ '$IDENTIFIER' undefined in $TARGET_FILE"

  # -------------------------------------------------------------------------
  # 3. Scan lib/ to find which file defines this identifier
  #    Looks for: class Foo, enum Foo, mixin Foo, typedef Foo,
  #               extension Foo, top-level functions/variables named foo
  # -------------------------------------------------------------------------
  MATCHES=()
  while IFS= read -r candidate; do
    # Skip generated files as definition sources too
    if echo "$candidate" | grep -qE "\.(g|freezed|gr)\.dart$"; then
      continue
    fi
    # Skip the file that has the error itself
    if [ "$candidate" = "$TARGET_FILE" ]; then
      continue
    fi

    # Check if identifier is defined in this candidate
    if grep -qE "^\s*(abstract\s+|final\s+|sealed\s+|base\s+|interface\s+)?(class|enum|mixin|typedef)\s+${IDENTIFIER}\b" "$candidate" 2>/dev/null; then
      MATCHES+=("$candidate")
    elif grep -qE "^extension\s+${IDENTIFIER}\b" "$candidate" 2>/dev/null; then
      MATCHES+=("$candidate")
    elif grep -qE "^\s*(const|final|var)\s+.*\b${IDENTIFIER}\b\s*=" "$candidate" 2>/dev/null; then
      MATCHES+=("$candidate")
    elif grep -qE "^[A-Za-z<>?,\s]+\s+${IDENTIFIER}\s*\(" "$candidate" 2>/dev/null; then
      MATCHES+=("$candidate")
    fi
  done < <(find "$LIB_DIR" -name "*.dart" -type f)

  MATCH_COUNT=${#MATCHES[@]}

  if [ "$MATCH_COUNT" -eq 0 ]; then
    echo "    [NO MATCH] No definition found for '$IDENTIFIER' — manual fix needed" | tee -a "$LOGFILE"
    continue
  fi

  if [ "$MATCH_COUNT" -gt 1 ]; then
    echo "    [AMBIGUOUS] Multiple definitions found for '$IDENTIFIER' — manual fix needed:" | tee -a "$LOGFILE"
    for m in "${MATCHES[@]}"; do
      echo "      - $m" | tee -a "$LOGFILE"
    done
    continue
  fi

  SOURCE_FILE="${MATCHES[0]}"

  # -------------------------------------------------------------------------
  # 4. Build the package import path from the source file path
  # -------------------------------------------------------------------------
  PACKAGE_NAME=$(grep -m1 "^name:" pubspec.yaml | sed 's/name:\s*//' | tr -d '[:space:]')
  # lib/some/path/file.dart -> package:myapp/some/path/file.dart
  IMPORT_PATH="package:${PACKAGE_NAME}/${SOURCE_FILE#lib/}"

  # -------------------------------------------------------------------------
  # 5. Check if this import already exists in the target file
  #    (plain, aliased, or with hide/show — any form)
  # -------------------------------------------------------------------------
  if grep -q "\"${IMPORT_PATH}\"\|'${IMPORT_PATH}'" "$TARGET_FILE"; then
    echo "    [SKIP] '$IMPORT_PATH' already imported in $TARGET_FILE — error may be due to hide/show/alias, manual fix needed" | tee -a "$LOGFILE"
    continue
  fi

  # -------------------------------------------------------------------------
  # 6. Insert the import after the last existing import line in the file
  # -------------------------------------------------------------------------
  LAST_IMPORT_LINE=$(grep -n "^import " "$TARGET_FILE" | tail -1 | cut -d: -f1)

  if [ -z "$LAST_IMPORT_LINE" ]; then
    # No imports at all — insert after any library/part-of line, or at top
    LAST_IMPORT_LINE=$(grep -n "^library\|^part of" "$TARGET_FILE" | tail -1 | cut -d: -f1)
    LAST_IMPORT_LINE="${LAST_IMPORT_LINE:-0}"
  fi

  INSERT_LINE=$((LAST_IMPORT_LINE + 1))
  NEW_IMPORT="import '${IMPORT_PATH}';"

  # Use awk to insert at exact line number
  awk -v n="$INSERT_LINE" -v s="$NEW_IMPORT" \
    'NR==n{print s} {print}' "$TARGET_FILE" >"${TARGET_FILE}.tmp" &&
    mv "${TARGET_FILE}.tmp" "$TARGET_FILE"

  echo "    [FIXED] Added: $NEW_IMPORT" | tee -a "$LOGFILE"
  echo "            in:   $TARGET_FILE (after line $LAST_IMPORT_LINE)" | tee -a "$LOGFILE"
  CHANGED=1

done < <(echo "$UNDEFINED_ERRORS")

# -----------------------------------------------------------------------------
# 7. If any file was changed, commit and exit 1 so the pipeline reruns
# -----------------------------------------------------------------------------
if [ "$CHANGED" -eq 1 ]; then
  echo ""
  echo "▶ Committing import fixes..."

  git add lib/
  git commit -m "fix: auto-heal missing imports [skip ci]"
  git push

  echo ""
  echo "❌ Imports were fixed and committed. Pipeline will rerun against clean code."
  echo "   See import-healer.log for details."
  exit 1
else
  echo ""
  echo "✅ No import fixes needed."
  exit 0
fi

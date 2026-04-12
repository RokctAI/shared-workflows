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

UNDEFINED_ERRORS=$(echo "$ANALYZE_OUT" | grep -E "^\s*error\s+•\s+Undefined (class|name|function|getter|setter|method|type|identifier)" || true)

if [ -z "$UNDEFINED_ERRORS" ]; then
  echo "✅ No undefined identifier errors found."
  exit 0
fi

# Use process substitution so loop runs in current shell and CHANGED persists
while IFS= read -r line; do
  IDENTIFIER=$(echo "$line" | grep -oP "Undefined \w+ '\K[^']+")
  TARGET_FILE=$(echo "$line" | grep -oP "lib/[^\s:•]+\.dart" | head -1)

  if echo "$TARGET_FILE" | grep -qE "\.(g|freezed|gr)\.dart$"; then
    continue
  fi

  if [ -z "$IDENTIFIER" ] || [ -z "$TARGET_FILE" ]; then
    continue
  fi

  if [ ! -f "$TARGET_FILE" ]; then
    continue
  fi

  echo ""
  echo "  ⚠ '$IDENTIFIER' undefined in $TARGET_FILE"

  # -------------------------------------------------------------------------
  # 3. Scan lib/ to find which file defines this identifier
  #    Covers: class/enum/mixin/typedef, extension, top-level variables,
  #    getters, functions, and DI registrations (getIt.registerX / final x =)
  # -------------------------------------------------------------------------
  MATCHES=()
  while IFS= read -r candidate; do
    if echo "$candidate" | grep -qE "\.(g|freezed|gr)\.dart$"; then
      continue
    fi
    if [ "$candidate" = "$TARGET_FILE" ]; then
      continue
    fi

    # class / enum / mixin / typedef
    if grep -qE "^\s*(abstract\s+|final\s+|sealed\s+|base\s+|interface\s+)?(class|enum|mixin|typedef)\s+${IDENTIFIER}\b" "$candidate" 2>/dev/null; then
      MATCHES+=("$candidate")
    # extension
    elif grep -qE "^extension\s+${IDENTIFIER}\b" "$candidate" 2>/dev/null; then
      MATCHES+=("$candidate")
    # const/final/var with type
    elif grep -qE "^\s*(const|final|var)\s+.*\b${IDENTIFIER}\b\s*=" "$candidate" 2>/dev/null; then
      MATCHES+=("$candidate")
    # getter: Type get identifierName
    elif grep -qE "\bget\s+${IDENTIFIER}\b" "$candidate" 2>/dev/null; then
      MATCHES+=("$candidate")
    # top-level function: ReturnType identifierName(
    elif grep -qE "^[A-Za-z<>?,\s]+\s+${IDENTIFIER}\s*\(" "$candidate" 2>/dev/null; then
      MATCHES+=("$candidate")
    # DI: final identifierName = getIt.get / getIt.registerX
    elif grep -qE "^\s*final\s+${IDENTIFIER}\s*=" "$candidate" 2>/dev/null; then
      MATCHES+=("$candidate")
    # DI: getIt.registerX<SomeType>(ConcreteImpl()) — find the file that registers
    # the concrete type used under this name
    elif grep -qE "getIt\.(registerSingleton|registerFactory|registerLazySingleton).*${IDENTIFIER}" "$candidate" 2>/dev/null; then
      MATCHES+=("$candidate")
    # Top-level variable with explicit capital type: SomeType identifierName =
    elif grep -qE "^[A-Z][A-Za-z<>?,\s]+\s+${IDENTIFIER}\s*=" "$candidate" 2>/dev/null; then
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
  IMPORT_PATH="package:${PACKAGE_NAME}/${SOURCE_FILE#lib/}"

  # -------------------------------------------------------------------------
  # 5. Check if this import already exists — inspect show/hide clauses
  # -------------------------------------------------------------------------
  if grep -q "\"${IMPORT_PATH}\"\|'${IMPORT_PATH}'" "$TARGET_FILE"; then
    EXISTING_IMPORT=$(grep "'${IMPORT_PATH}'\|\"${IMPORT_PATH}\"" "$TARGET_FILE" | head -1)

    # --- show clause: only listed identifiers are visible ---
    if echo "$EXISTING_IMPORT" | grep -qE "\bshow\b"; then
      if echo "$EXISTING_IMPORT" | grep -qE "\bshow\b.*\b${IDENTIFIER}\b"; then
        # Already shown — error is something else
        echo "    [SKIP] '$IMPORT_PATH' has show clause including '$IDENTIFIER' — error is unrelated, manual fix needed" | tee -a "$LOGFILE"
        continue
      else
        # Not in show list — add it
        # Use Python for safe in-place substitution (avoids sed escaping hell)
        python3 - "$TARGET_FILE" "$EXISTING_IMPORT" "$IDENTIFIER" <<'PYEOF'
import sys
path, existing, ident = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path, 'r') as f:
    content = f.read()
# Append identifier to show clause
import re
updated = re.sub(
    r'(show\s+[^;]+?)(\s*;)',
    lambda m: m.group(1).rstrip() + ', ' + ident + m.group(2),
    existing,
    count=1
)
content = content.replace(existing, updated, 1)
with open(path, 'w') as f:
    f.write(content)
PYEOF
        echo "    [FIXED] Extended show clause to include '$IDENTIFIER' in $TARGET_FILE" | tee -a "$LOGFILE"
        CHANGED=1
        continue
      fi

    # --- hide clause: listed identifiers are hidden, rest are visible ---
    elif echo "$EXISTING_IMPORT" | grep -qE "\bhide\b"; then
      if echo "$EXISTING_IMPORT" | grep -qE "\bhide\b.*\b${IDENTIFIER}\b"; then
        # Identifier is explicitly hidden — remove it from the hide list
        python3 - "$TARGET_FILE" "$EXISTING_IMPORT" "$IDENTIFIER" <<'PYEOF'
import sys, re
path, existing, ident = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path, 'r') as f:
    content = f.read()
# Remove identifier from hide clause; clean up trailing comma/space
updated = re.sub(r',?\s*\b' + re.escape(ident) + r'\b,?', '', existing)
# If hide clause is now empty (hide  ;), remove the whole hide clause
updated = re.sub(r'\s*hide\s*;', ';', updated)
# Clean up double commas or leading comma in hide list
updated = re.sub(r'hide\s*,\s*', 'hide ', updated)
updated = re.sub(r',\s*,', ',', updated)
content = content.replace(existing, updated, 1)
with open(path, 'w') as f:
    f.write(content)
PYEOF
        echo "    [FIXED] Removed '$IDENTIFIER' from hide clause in $TARGET_FILE" | tee -a "$LOGFILE"
        CHANGED=1
        continue
      else
        # Not in hide list — import exists and identifier is visible, error is unrelated
        echo "    [SKIP] '$IMPORT_PATH' imported with hide not covering '$IDENTIFIER' — error is unrelated, manual fix needed" | tee -a "$LOGFILE"
        continue
      fi

    # --- plain import exists, no show/hide — error is unrelated (alias, etc.) ---
    else
      echo "    [SKIP] '$IMPORT_PATH' already imported plainly in $TARGET_FILE — error may be due to alias, manual fix needed" | tee -a "$LOGFILE"
      continue
    fi
  fi

  # -------------------------------------------------------------------------
  # 6. Insert the import after the last existing import line in the file
  # -------------------------------------------------------------------------
  LAST_IMPORT_LINE=$(grep -n "^import " "$TARGET_FILE" | tail -1 | cut -d: -f1)

  if [ -z "$LAST_IMPORT_LINE" ]; then
    LAST_IMPORT_LINE=$(grep -n "^library\|^part of" "$TARGET_FILE" | tail -1 | cut -d: -f1)
    LAST_IMPORT_LINE="${LAST_IMPORT_LINE:-0}"
  fi

  INSERT_LINE=$((LAST_IMPORT_LINE + 1))
  NEW_IMPORT="import '${IMPORT_PATH}';"

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

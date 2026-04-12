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
# 1. Run flutter analyze — or reuse output passed in via ANALYZE_OUTPUT_FILE
#    Set ANALYZE_OUTPUT_FILE env var to skip re-running analyze (e.g. from lint step)
# -----------------------------------------------------------------------------
echo ""
if [ -n "${ANALYZE_OUTPUT_FILE:-}" ] && [ -f "$ANALYZE_OUTPUT_FILE" ]; then
  echo "▶ Reusing flutter analyze output from $ANALYZE_OUTPUT_FILE"
  ANALYZE_OUT=$(cat "$ANALYZE_OUTPUT_FILE")
else
  echo "▶ Running flutter analyze..."
  ANALYZE_OUT=$(flutter analyze --no-pub 2>&1 || true)
fi
echo "$ANALYZE_OUT" >>"$LOGFILE"

# -----------------------------------------------------------------------------
# 2. Parse undefined identifier/class errors only
# -----------------------------------------------------------------------------
echo ""
echo "▶ Parsing errors..."

UNDEFINED_ERRORS=$(echo "$ANALYZE_OUT" | grep -E "^\s*error\s+•\s+Undefined (class|name|function|getter|setter|method|type|identifier)" || true)

if [ -z "$UNDEFINED_ERRORS" ]; then
  echo "✅ No undefined identifier errors found."
  exit 0
fi

PACKAGE_NAME=$(grep -m1 "^name:" pubspec.yaml | sed 's/name:\s*//' | tr -d '[:space:]')

# -----------------------------------------------------------------------------
# 3. Build a definition index once — file:identifier for every dart file
#    Format of index: "lib/path/to/file.dart\tIdentifierName"
#    This replaces the per-error find+grep loop that caused the 2hr runtime.
# -----------------------------------------------------------------------------
echo ""
echo "▶ Building definition index..."
INDEX_FILE=$(mktemp)

while IFS= read -r f; do
  # Skip generated files
  if echo "$f" | grep -qE "\.(g|freezed|gr)\.dart$"; then
    continue
  fi

  # class / enum / mixin / typedef
  while IFS= read -r name; do
    [ -n "$name" ] && echo -e "${f}\t${name}"
  done < <(grep -oP "(?:^|\s)(class|enum|mixin|typedef)\s+\K[A-Za-z_][A-Za-z0-9_]*" "$f" 2>/dev/null || true)

  # extension ExtName
  while IFS= read -r name; do
    [ -n "$name" ] && echo -e "${f}\t${name}"
  done < <(grep -oP "^extension\s+\K[A-Za-z_][A-Za-z0-9_]*" "$f" 2>/dev/null || true)

  # getter: get identifierName
  while IFS= read -r name; do
    [ -n "$name" ] && echo -e "${f}\t${name}"
  done < <(grep -oP "\bget\s+\K[A-Za-z_][A-Za-z0-9_]*" "$f" 2>/dev/null || true)

  # final identifierName = ... (top-level DI accessors)
  while IFS= read -r name; do
    [ -n "$name" ] && echo -e "${f}\t${name}"
  done < <(grep -oP "^\s*final\s+\K[A-Za-z_][A-Za-z0-9_]*(?=\s*=)" "$f" 2>/dev/null || true)

  # top-level function: ReturnType identifierName(
  while IFS= read -r name; do
    [ -n "$name" ] && echo -e "${f}\t${name}"
  done < <(grep -oP "^[A-Za-z<>?,\s]+\s+\K[a-z][A-Za-z0-9_]*(?=\s*\()" "$f" 2>/dev/null || true)

done < <(find "$LIB_DIR" -name "*.dart" -type f) > "$INDEX_FILE"

echo "  Index built: $(wc -l < "$INDEX_FILE") entries across $(find "$LIB_DIR" -name "*.dart" -not -name "*.g.dart" -not -name "*.freezed.dart" -not -name "*.gr.dart" | wc -l) files"

# -----------------------------------------------------------------------------
# 4. Process each error using the index
# -----------------------------------------------------------------------------
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

  # Look up identifier in index — exclude the target file itself
  MATCHES=$(grep -P "^(?!${TARGET_FILE}\t).*\t${IDENTIFIER}$" "$INDEX_FILE" | cut -f1 | sort -u || true)
  MATCH_COUNT=$(echo "$MATCHES" | grep -c "." || true)

  if [ -z "$MATCHES" ] || [ "$MATCH_COUNT" -eq 0 ]; then
    echo "    [NO MATCH] No definition found for '$IDENTIFIER' — manual fix needed" | tee -a "$LOGFILE"
    continue
  fi

  if [ "$MATCH_COUNT" -gt 1 ]; then
    echo "    [AMBIGUOUS] Multiple definitions found for '$IDENTIFIER' — manual fix needed:" | tee -a "$LOGFILE"
    echo "$MATCHES" | while IFS= read -r m; do
      echo "      - $m" | tee -a "$LOGFILE"
    done
    continue
  fi

  SOURCE_FILE="$MATCHES"
  IMPORT_PATH="package:${PACKAGE_NAME}/${SOURCE_FILE#lib/}"

  # -------------------------------------------------------------------------
  # 5. Check if import exists — inspect show/hide clauses and fix them
  # -------------------------------------------------------------------------
  if grep -q "\"${IMPORT_PATH}\"\|'${IMPORT_PATH}'" "$TARGET_FILE"; then
    EXISTING_IMPORT=$(grep "'${IMPORT_PATH}'\|\"${IMPORT_PATH}\"" "$TARGET_FILE" | head -1)

    # show clause: only listed identifiers are visible
    if echo "$EXISTING_IMPORT" | grep -qE "\bshow\b"; then
      if echo "$EXISTING_IMPORT" | grep -qE "\bshow\b.*\b${IDENTIFIER}\b"; then
        echo "    [SKIP] show clause already includes '$IDENTIFIER' — error is unrelated, manual fix needed" | tee -a "$LOGFILE"
      else
        python3 - "$TARGET_FILE" "$EXISTING_IMPORT" "$IDENTIFIER" << 'PYEOF'
import sys, re
path, existing, ident = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path, 'r') as f:
    content = f.read()
updated = re.sub(r'(show\s+[^;]+?)(\s*;)', lambda m: m.group(1).rstrip() + ', ' + ident + m.group(2), existing, count=1)
content = content.replace(existing, updated, 1)
with open(path, 'w') as f:
    f.write(content)
PYEOF
        echo "    [FIXED] Extended show clause to include '$IDENTIFIER' in $TARGET_FILE" | tee -a "$LOGFILE"
        CHANGED=1
      fi
      continue
    fi

    # hide clause: listed identifiers are blocked
    if echo "$EXISTING_IMPORT" | grep -qE "\bhide\b"; then
      if echo "$EXISTING_IMPORT" | grep -qE "\bhide\b.*\b${IDENTIFIER}\b"; then
        python3 - "$TARGET_FILE" "$EXISTING_IMPORT" "$IDENTIFIER" << 'PYEOF'
import sys, re
path, existing, ident = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path, 'r') as f:
    content = f.read()
updated = re.sub(r',?\s*\b' + re.escape(ident) + r'\b,?', '', existing)
updated = re.sub(r'\s*hide\s*;', ';', updated)
updated = re.sub(r'hide\s*,\s*', 'hide ', updated)
updated = re.sub(r',\s*,', ',', updated)
content = content.replace(existing, updated, 1)
with open(path, 'w') as f:
    f.write(content)
PYEOF
        echo "    [FIXED] Removed '$IDENTIFIER' from hide clause in $TARGET_FILE" | tee -a "$LOGFILE"
        CHANGED=1
      else
        echo "    [SKIP] '$IDENTIFIER' not in hide clause, import visible — error is unrelated, manual fix needed" | tee -a "$LOGFILE"
      fi
      continue
    fi

    # Plain import exists with no show/hide — error is unrelated
    echo "    [SKIP] '$IMPORT_PATH' already imported plainly — error may be due to alias, manual fix needed" | tee -a "$LOGFILE"
    continue
  fi

  # -------------------------------------------------------------------------
  # 6. Insert import after the last existing import line
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

rm -f "$INDEX_FILE"

# -----------------------------------------------------------------------------
# 7. Deduplicate imports across all dart files in lib/
#    Handles duplicate import lines left by package renames or repeated healer runs
# -----------------------------------------------------------------------------
echo ""
echo "▶ Deduplicating imports..."

while IFS= read -r f; do
  python3 - "$f" << 'PYEOF'
import sys
path = sys.argv[1]
with open(path, 'r') as fh:
    lines = fh.readlines()
seen = set()
out = []
for line in lines:
    stripped = line.rstrip('\n')
    if stripped.startswith('import '):
        if stripped in seen:
            continue
        seen.add(stripped)
    out.append(line)
if len(out) != len(lines):
    with open(path, 'w') as fh:
        fh.writelines(out)
    print(f"  [DEDUPED] {path}")
PYEOF
done < <(find "$LIB_DIR" -name "*.dart" -type f)

# -----------------------------------------------------------------------------
# 8. If any file was changed, commit and exit 1 so the pipeline reruns
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
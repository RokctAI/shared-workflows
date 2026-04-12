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
# 3. Build definition index once
#    - Non-generated files: index all definition types
#    - Generated route files (*.gr.dart): index class names only (as definition
#      sources — the healer never edits them, but imports them when needed)
#    - part files: definitions are attributed to their parent file so the import
#      path resolves correctly (importing the parent exposes all part members)
# -----------------------------------------------------------------------------
echo ""
echo "▶ Building definition index..."
INDEX_FILE=$(mktemp)

# First pass: build a map of part file -> parent file
# so we can attribute part-file definitions to the correct import path
PART_MAP_FILE=$(mktemp)
while IFS= read -r f; do
  if echo "$f" | grep -qE "\.(g|freezed|gr)\.dart$"; then
    continue
  fi
  # Find: part 'something.dart'; lines — these declare part files
  while IFS= read -r part_rel; do
    [ -z "$part_rel" ] && continue
    # Resolve relative path from the parent file's directory
    PARENT_DIR=$(dirname "$f")
    PART_PATH="${PARENT_DIR}/${part_rel}"
    # Normalize path
    PART_PATH=$(realpath --relative-to="." "$PART_PATH" 2>/dev/null || echo "$PART_PATH")
    echo -e "${PART_PATH}\t${f}"
  done < <(grep -oP "^part\s+'?\K[^';]+" "$f" 2>/dev/null || true)
done < <(find "$LIB_DIR" -name "*.dart" -type f) >"$PART_MAP_FILE"

# Second pass: index all dart files
while IFS= read -r f; do
  # Determine the import path to use for this file:
  # if it's a part file, attribute its definitions to the parent
  PARENT=$(grep -P "^${f}\t" "$PART_MAP_FILE" | cut -f2 | head -1 || true)
  INDEX_AS="${PARENT:-$f}"

  # Skip generated non-route files as definition sources
  if echo "$f" | grep -qE "\.(g|freezed)\.dart$"; then
    continue
  fi

  # class / enum / mixin / typedef
  while IFS= read -r name; do
    [ -n "$name" ] && echo -e "${INDEX_AS}\t${name}"
  done < <(grep -oP "(?:^|\s)(class|enum|mixin|typedef)\s+\K[A-Za-z_][A-Za-z0-9_]*" "$f" 2>/dev/null || true)

  # extension ExtName
  while IFS= read -r name; do
    [ -n "$name" ] && echo -e "${INDEX_AS}\t${name}"
  done < <(grep -oP "^extension\s+\K[A-Za-z_][A-Za-z0-9_]*" "$f" 2>/dev/null || true)

  # getter: get identifierName (top-level only — skip in-class)
  while IFS= read -r name; do
    [ -n "$name" ] && echo -e "${INDEX_AS}\t${name}"
  done < <(grep -oP "^[A-Za-z<>?,\s]*\bget\s+\K[A-Za-z_][A-Za-z0-9_]*" "$f" 2>/dev/null || true)

  # final identifierName = (top-level DI accessors)
  while IFS= read -r name; do
    [ -n "$name" ] && echo -e "${INDEX_AS}\t${name}"
  done < <(grep -oP "^\s*final\s+\K[A-Za-z_][A-Za-z0-9_]*(?=\s*=)" "$f" 2>/dev/null || true)

  # top-level function: ReturnType identifierName(
  while IFS= read -r name; do
    [ -n "$name" ] && echo -e "${INDEX_AS}\t${name}"
  done < <(grep -oP "^[A-Za-z<>?,\s]+\s+\K[a-z][A-Za-z0-9_]*(?=\s*\()" "$f" 2>/dev/null || true)

done < <(find "$LIB_DIR" -name "*.dart" -type f) >"$INDEX_FILE"

echo "  Index built: $(wc -l <"$INDEX_FILE") entries across $(find "$LIB_DIR" -name "*.dart" | wc -l) files"

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

  # Skip obviously non-import errors: very short/generic names are never
  # missing imports — they're typos or missing declarations entirely
  if echo "$IDENTIFIER" | grep -qE "^(help|text|data|value|context|key|child|children|builder|state|type|name|id|index|item|list|map|set|get|on|is|to|of|in|by|at)$"; then
    echo ""
    echo "  ⚠ '$IDENTIFIER' undefined in $TARGET_FILE"
    echo "    [SKIP] '$IDENTIFIER' is a generic name — likely a missing declaration, not a missing import" | tee -a "$LOGFILE"
    continue
  fi

  echo ""
  echo "  ⚠ '$IDENTIFIER' undefined in $TARGET_FILE"

  # Look up identifier in index — exclude the target file itself
  MATCHES=$(grep -P "^(?!${TARGET_FILE}\t).*\t${IDENTIFIER}$" "$INDEX_FILE" | cut -f1 | sort -u || true)
  MATCH_COUNT=$(echo "$MATCHES" | grep -c "." || true)

  if [ -z "$MATCHES" ] || [ "$MATCH_COUNT" -eq 0 ]; then
    echo "    [NO MATCH] No definition found for '$IDENTIFIER' — file may be missing entirely, manual fix needed" | tee -a "$LOGFILE"
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
        python3 - "$TARGET_FILE" "$EXISTING_IMPORT" "$IDENTIFIER" <<'PYEOF'
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
        # Check if another import in this file also exports this identifier
        # If so, removing from hide would cause a duplicate definition conflict
        OTHER_IMPORTS=$(grep "^import " "$TARGET_FILE" | grep -v "$IMPORT_PATH" || true)
        CONFLICT=false
        while IFS= read -r other; do
          OTHER_PATH=$(echo "$other" | grep -oP "'[^']+'" | tr -d "'")
          OTHER_FILE=$(find "$LIB_DIR" -name "*.dart" -type f | while IFS= read -r f; do
            PKG="package:${PACKAGE_NAME}/${f#lib/}"
            [ "$PKG" = "$OTHER_PATH" ] && echo "$f"
          done | head -1)
          if [ -n "$OTHER_FILE" ] && grep -qE "\b(class|enum|mixin|typedef)\s+${IDENTIFIER}\b" "$OTHER_FILE" 2>/dev/null; then
            CONFLICT=true
            break
          fi
        done <<<"$OTHER_IMPORTS"

        if [ "$CONFLICT" = true ]; then
          echo "    [SKIP] Cannot remove '$IDENTIFIER' from hide — another import in $TARGET_FILE also exports it (would cause conflict), manual fix needed" | tee -a "$LOGFILE"
        else
          python3 - "$TARGET_FILE" "$EXISTING_IMPORT" "$IDENTIFIER" <<'PYEOF'
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
        fi
      else
        echo "    [SKIP] '$IDENTIFIER' not in hide clause, import visible — error is unrelated, manual fix needed" | tee -a "$LOGFILE"
      fi
      continue
    fi

    # Check for alias — if alias.anything is used in the file, keep it
    # If alias is completely unused, remove it and replace with plain import
    if echo "$EXISTING_IMPORT" | grep -qE "as\s+[A-Za-z_][A-Za-z0-9_]*"; then
      ALIAS=$(echo "$EXISTING_IMPORT" | grep -oP "as\s+\K[A-Za-z_][A-Za-z0-9_]*")
      if grep -q "${ALIAS}\." "$TARGET_FILE"; then
        echo "    [SKIP] alias '${ALIAS}' is in use — '$IDENTIFIER' must be accessed as '${ALIAS}.${IDENTIFIER}', manual fix needed" | tee -a "$LOGFILE"
      else
        python3 - "$TARGET_FILE" "$EXISTING_IMPORT" "$IMPORT_PATH" <<'PYEOF'
import sys
path, existing, import_path = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path, "r") as f:
    content = f.read()
content = content.replace(existing, f"import '{import_path}';", 1)
with open(path, "w") as f:
    f.write(content)
PYEOF
        echo "    [FIXED] Removed unused alias, replaced with plain import in $TARGET_FILE" | tee -a "$LOGFILE"
        CHANGED=1
      fi
      continue
    fi

    # Plain import exists with no show/hide/alias — identifier should be visible
    # but Dart still reports it undefined. This is unresolvable by import manipulation.
    echo "    [SKIP] '$IMPORT_PATH' already imported plainly — identifier may be missing from source file, manual fix needed" | tee -a "$LOGFILE"
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

rm -f "$INDEX_FILE" "$PART_MAP_FILE"

# -----------------------------------------------------------------------------
# 7. Deduplicate imports across all dart files in lib/
# -----------------------------------------------------------------------------
echo ""
echo "▶ Deduplicating imports..."

DEDUP_SCRIPT=$(mktemp /tmp/dedup_XXXXXX.py)
cat >"$DEDUP_SCRIPT" <<'PYEOF'
import sys, os
changed = 0
for path in sys.argv[1:]:
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
        changed += 1
sys.exit(1 if changed > 0 else 0)
PYEOF

DART_FILES=$(find "$LIB_DIR" -name "*.dart" -type f | tr '\n' ' ')
if [ -n "$DART_FILES" ]; then
  if ! python3 "$DEDUP_SCRIPT" $DART_FILES; then
    CHANGED=1
  fi
fi
rm -f "$DEDUP_SCRIPT"

# -----------------------------------------------------------------------------
# 8. Print manual fix summary grouped by type
# -----------------------------------------------------------------------------
NO_MATCH_COUNT=$(grep -c "\[NO MATCH\]" "$LOGFILE" || true)
SKIP_COUNT=$(grep -c "\[SKIP\]" "$LOGFILE" || true)

if [ "$NO_MATCH_COUNT" -gt 0 ] || [ "$SKIP_COUNT" -gt 0 ]; then
  echo ""
  echo "▶ Manual fixes still needed:"

  if [ "$NO_MATCH_COUNT" -gt 0 ]; then
    echo ""
    echo "  Identifier not found anywhere in lib/ — class/enum/route may be missing, not yet generated, or still using old package name:"
    grep "\[NO MATCH\]" "$LOGFILE" | grep -oP "for '\K[^']+" | sort -u | while IFS= read -r id; do
      FILES=$(grep "\[NO MATCH\].*for '${id}'" "$LOGFILE" | grep -oP "⚠ '[^']+' undefined in \K\S+" | sort -u | tr '
' ' ')
      echo "    • $id → $FILES"
    done
  fi

  if [ "$SKIP_COUNT" -gt 0 ]; then
    echo ""
    echo "  Import exists but identifier still unresolved (check for naming conflict or missing declaration in source file):"
    grep "\[SKIP\].*already imported plainly" "$LOGFILE" | grep -oP "⚠ '\K[^']+" | sort -u | while IFS= read -r id; do
      echo "    • $id"
    done
  fi
fi

# -----------------------------------------------------------------------------
# 9. Exit with status — caller decides whether to loop or commit
#    HEALER_NO_COMMIT=1 : just return exit code, don't commit (loop mode)
#    default            : commit and push on change (single-run mode)
# -----------------------------------------------------------------------------
if [ "$CHANGED" -eq 1 ]; then
  if [ "${HEALER_NO_COMMIT:-0}" = "1" ]; then
    echo ""
    echo "↻ Fixes applied — signalling caller to rerun."
    exit 1
  fi

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

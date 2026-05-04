# Copyright (c) 2024, Rokct Intelligence (pty) Ltd.
# For license information, please see license.txt

#!/bin/bash

run_step() {
  local title="$1"
  shift
  local step_log
  step_log=$(mktemp)
  printf "  - %s... " "$title"

  # PHASE 1: EXECUTION (captured buffer)
  "$@" >"$step_log" 2>&1
  local exit_code=$?

  # PHASE 2: VALIDATION (log inspection)
  local errors
  errors=$(grep -Ei "Traceback|Exception:|Error:|FAILED" "$step_log" 2>/dev/null || true)

  if [ $exit_code -eq 0 ] && [ -z "$errors" ]; then
    echo "✓ DONE"
  else
    echo "❌ FAILED"
    echo "    ---- LOG START ----"
    cat "$step_log"
    echo "    ---- LOG END ----"
    rm -f "$step_log"
    exit 1
  fi
  rm -f "$step_log"
}

# Configuration
BASE_URL="https://raw.githubusercontent.com/RokctAI/shared-workflows/main"
WORKFLOW_DIR="examples/workflows"
VITAL_WORKFLOWS=(
  "build.yml"
  "release.yml"
  "security.yml"
  "linter.yml"
  "merge.yml"
  "assign.yml"
  "labeler.yml"
  "stale.yml"
  "todo.yml"
  "dependabot.yml"
)

# Default Values
PROJECT_TYPE="smart"
STARTING_VERSION="0.0.1"
RELEASE_STRATEGY="immediate"
CRON_SCHEDULE="0 23 * * 5"
NODE_VERSION="24"
PYTHON_VERSION="3.14"
FLUTTER_VERSION="3.24.0"
DEPENDABOT_INTERVAL="monthly"
LOCAL_MODE=false
GH_HANDLE="@RendaniSinyage"

# Check for --local flag
for arg in "$@"; do
  if [ "$arg" == "--local" ]; then
    LOCAL_MODE=true
  fi
done

echo -e "\n\033[1;36m🚀 RokctAI Shared Workflows Installer\033[0m\n"

# --- 1. Interaction ---
if [ -t 0 ] || [ -n "$GITHUB_ACTIONS" ]; then
  read -p "Do you want to customize your workflow setup? (y/N - Press Enter for No): " CUSTOMIZE
else
  CUSTOMIZE="n"
fi

if [ -z "$CUSTOMIZE" ] && [ -n "$GITHUB_ACTIONS" ]; then
  CUSTOMIZE="n"
fi

if [[ "$CUSTOMIZE" =~ ^[Yy]$ ]]; then
  echo -e "\n\033[0;33m🛠️ Customizing Setup... (Press Enter to keep the [default] value)\033[0m\n"

  # Project Type
  echo "Select Project Type:"
  echo "1. smart (Auto-detect Flutter/Node/Frappe)"
  echo "2. flutter (Mobile/Desktop/Web)"
  echo "3. frappe (ERPNext/Python)"
  echo "4. node (Next.js/React/JS)"
  read -p "Choice [1]: " CHOICE
  case $CHOICE in
  2) PROJECT_TYPE="flutter" ;;
  3) PROJECT_TYPE="frappe" ;;
  4) PROJECT_TYPE="node" ;;
  *) PROJECT_TYPE="smart" ;;
  esac

  # Versioning (Skip for Flutter)
  if [ "$PROJECT_TYPE" != "flutter" ]; then
    read -p "Starting version [$STARTING_VERSION]: " INPUT_VER
    STARTING_VERSION=${INPUT_VER:-$STARTING_VERSION}
  fi

  # Release Strategy
  echo -e "\nSelect Release Strategy:"
  echo "1. immediate (Release on every push to main)"
  echo "2. weekly (Promote Friday RCs to Stable)"
  echo "3. weekly-rc (Pre-release RCs on every push to main)"
  read -p "Choice [1]: " CHOICE_STRAT
  case $CHOICE_STRAT in
  2) RELEASE_STRATEGY="weekly" ;;
  3) RELEASE_STRATEGY="weekly-rc" ;;
  *) RELEASE_STRATEGY="immediate" ;;
  esac

  # Cron Schedule (Only for weekly)
  if [[ "$RELEASE_STRATEGY" == "weekly" || "$RELEASE_STRATEGY" == "weekly-rc" ]]; then
    read -p "Cron schedule [$CRON_SCHEDULE] (e.g., '0 23 * * 5' for Friday 11PM): " INPUT_CRON
    CRON_SCHEDULE=${INPUT_CRON:-$CRON_SCHEDULE}
  fi

  # Dependency Versions
  echo -e "\nDefault Dependency Versions:"
  read -p "Node.js version [$NODE_VERSION]: " INPUT_NODE
  NODE_VERSION=${INPUT_NODE:-$NODE_VERSION}

  read -p "Python version [$PYTHON_VERSION]: " INPUT_PYTHON
  PYTHON_VERSION=${INPUT_PYTHON:-$PYTHON_VERSION}

  read -p "Flutter version [$FLUTTER_VERSION]: " INPUT_FLUTTER
  FLUTTER_VERSION=${INPUT_FLUTTER:-$FLUTTER_VERSION}
  # CODEOWNERS Handle
  read -p "GitHub handle for CODEOWNERS [$GH_HANDLE]: " INPUT_HANDLE
  GH_HANDLE=${INPUT_HANDLE:-$GH_HANDLE}

  # Dependabot Frequency
  echo -e "\nSelect Dependabot Update Frequency:"
  echo "1. monthly (Fleet standard - Recommended)"
  echo "2. weekly"
  echo "3. daily"
  read -p "Choice [1]: " CHOICE_DEP
  case $CHOICE_DEP in
  2) DEPENDABOT_INTERVAL="weekly" ;;
  3) DEPENDABOT_INTERVAL="daily" ;;
  *) DEPENDABOT_INTERVAL="monthly" ;;
  esac
else
  echo -e "\n\033[0;90m⏩ Using standard fleet defaults (Quick Install).\033[0m"
fi

# --- 2. Preparing Files ---
TARGET_PATH=".github/workflows"
if [ ! -d "$TARGET_PATH" ]; then
  echo -e "\n📁 Creating $TARGET_PATH..."
  run_step "Creating workflow directory" mkdir -p "$TARGET_PATH"
fi

# 3. Download and Patch
for wf in "${VITAL_WORKFLOWS[@]}"; do
  DEST_FINAL=""
  if [ "$wf" == "dependabot.yml" ]; then
    DEST_FINAL=".github/$wf"
  else
    DEST_FINAL="$TARGET_PATH/$wf"
  fi

  if [ "$LOCAL_MODE" = true ]; then
    if [ "$wf" == "dependabot.yml" ]; then
      SRC="../examples/$wf"
    else
      SRC="../$WORKFLOW_DIR/$wf"
    fi
    run_step "Copying $wf" cp "$SRC" "$DEST_FINAL.tmp"
  else
    if [ "$wf" == "dependabot.yml" ]; then
      URL="$BASE_URL/examples/$wf"
    else
      URL="$BASE_URL/$WORKFLOW_DIR/$wf"
    fi
    run_step "Fetching $wf" curl -sSL "$URL" -o "$DEST_FINAL.tmp"
  fi

  if [[ "$wf" == "build.yml" || "$wf" == "release.yml" ]]; then
    if [ "$PROJECT_TYPE" != "smart" ]; then
      run_step "Patching project type in $wf" sed -i "s/project_type: '[^']*'/project_type: '$PROJECT_TYPE'/g" "$DEST_FINAL.tmp"
    fi
    run_step "Patching release strategy in $wf" sed -i "s/release_strategy: '[^']*'/release_strategy: '$RELEASE_STRATEGY'/g" "$DEST_FINAL.tmp"

    if [[ "$wf" == "release.yml" && "$PROJECT_TYPE" == "flutter" ]]; then
      run_step "Removing Friday Cron in $wf" sed -i '/schedule:/,+1d' "$DEST_FINAL.tmp"
    else
      run_step "Patching Cron Schedule in $wf" sed -i "s/cron: '[^']*'/cron: '$CRON_SCHEDULE'/g" "$DEST_FINAL.tmp"
    fi

    run_step "Patching Node version in $wf" sed -i "/node-version:/,/default:/s/default: '[^']*'/default: '$NODE_VERSION'/" "$DEST_FINAL.tmp"
    run_step "Patching Python version in $wf" sed -i "/python-version:/,/default:/s/default: '[^']*'/default: '$PYTHON_VERSION'/" "$DEST_FINAL.tmp"
    run_step "Patching Flutter version in $wf" sed -i "/flutter-version:/,/default:/s/default: '[^']*'/default: '$FLUTTER_VERSION'/" "$DEST_FINAL.tmp"
    run_step "Patching Smart Flutter Pin in $wf" sed -i "s/flutter-version: '[^']*'/flutter-version: '$FLUTTER_VERSION'/g" "$DEST_FINAL.tmp"
  fi

  if [ "$wf" == "dependabot.yml" ]; then
    if [ "$DEPENDABOT_INTERVAL" != "monthly" ]; then
      run_step "Patching Dependabot frequency" sed -i "s/interval: \"monthly\"/interval: \"$DEPENDABOT_INTERVAL\" # rokct-keep/g" "$DEST_FINAL.tmp"
    fi
  fi

  run_step "Normalizing $wf" bash -c "
    sed -i 's/\r//g' $DEST_FINAL.tmp
    perl -0777 -pi -e 's/^\xEF\xBB\xBF//; s/^\s+//; s/\s+\z//' $DEST_FINAL.tmp
    printf '\n' >>$DEST_FINAL.tmp"
  run_step "Moving $wf to final destination" mv "$DEST_FINAL.tmp" "$DEST_FINAL"
done

# 4. Handle version.json (Skip for Flutter)
if [ "$PROJECT_TYPE" != "flutter" ]; then
  if [ ! -f "version.json" ]; then
    run_step "Creating version.json" bash -c "echo -e '{\n  \"version\": \"$STARTING_VERSION\"\n}' >version.json"
  fi
fi

# 5. Handle CODEOWNERS (Governance - Custom Setup Only)
if [[ "$CUSTOMIZE" =~ ^[Yy]$ ]] && [ ! -f ".github/CODEOWNERS" ]; then
  run_step "Creating .github directory" mkdir -p ".github"
  if [ "$LOCAL_MODE" = true ]; then
    run_step "Copying CODEOWNERS" cp "../examples/CODEOWNERS" ".github/CODEOWNERS"
  else
    run_step "Fetching CODEOWNERS" curl -sSL "$BASE_URL/examples/CODEOWNERS" -o ".github/CODEOWNERS"
  fi
  run_step "Patching CODEOWNERS" sed -i "s/{{HANDLE}}/$GH_HANDLE/g" ".github/CODEOWNERS"
fi

echo -e "\n\033[0;32m✅ Installation Complete!\033[0m\n"

echo -e "\033[1;33m⚠️  IMPORTANT: GITHUB APP PERMISSIONS\033[0m"
echo -e "To allow the Fleet Standardizer to auto-fix and update your workflows, your GitHub App MUST have:"
echo -e "  - \033[1mWorkflows: Read & Write\033[0m"
echo -e "Otherwise, maintenance PRs will fail to push. Update this in your App Settings > Permissions & events.\n"

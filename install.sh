#!/bin/bash

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
    # CODEOWNERS Handle
    read -p "GitHub handle for CODEOWNERS [$GH_HANDLE]: " INPUT_HANDLE
    GH_HANDLE=${INPUT_HANDLE:-$GH_HANDLE}
else
    echo -e "\n\033[0;90m⏩ Using standard fleet defaults (Quick Install).\033[0m"
fi

# --- 2. Preparing Files ---
TARGET_PATH=".github/workflows"
if [ ! -d "$TARGET_PATH" ]; then
    echo -e "\n📁 Creating $TARGET_PATH..."
    mkdir -p "$TARGET_PATH"
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
        cp "$SRC" "$DEST_FINAL.tmp"
    else
        if [ "$wf" == "dependabot.yml" ]; then
            URL="$BASE_URL/examples/$wf"
        else
            URL="$BASE_URL/$WORKFLOW_DIR/$wf"
        fi
        echo "📥 Fetching and Patching $wf..."
        curl -sSL "$URL" -o "$DEST_FINAL.tmp"
    fi
    
    # Ensure Unix line endings before hatching
    sed -i 's/\r//g' "$DEST_FINAL.tmp"

    if [[ "$wf" == "build.yml" || "$wf" == "release.yml" ]]; then
        # Project Type - using a more specific regex to preserve comments
        if [ "$PROJECT_TYPE" != "smart" ]; then
            sed -i "s/project_type: '[^']*'/project_type: '$PROJECT_TYPE'/g" "$DEST_FINAL.tmp"
        fi
        # Strategy
        sed -i "s/release_strategy: '[^']*'/release_strategy: '$RELEASE_STRATEGY'/g" "$DEST_FINAL.tmp"
        # Cron Schedule
        sed -i "s/cron: '[^']*'/cron: '$CRON_SCHEDULE'/g" "$DEST_FINAL.tmp"
        # Node (Multi-line aware sed)
        sed -i "/node-version:/,/default:/s/default: '[^']*'/default: '$NODE_VERSION'/" "$DEST_FINAL.tmp"
        # Python
        sed -i "/python-version:/,/default:/s/default: '[^']*'/default: '$PYTHON_VERSION'/" "$DEST_FINAL.tmp"
    fi

    mv "$DEST_FINAL.tmp" "$DEST_FINAL"
done

# 4. Handle version.json (Skip for Flutter)
if [ "$PROJECT_TYPE" != "flutter" ]; then
    if [ ! -f "version.json" ]; then
        echo -e "\n\033[0;33m📝 Creating version.json ($STARTING_VERSION)...\033[0m"
        echo -e "{\n  \"version\": \"$STARTING_VERSION\"\n}" > version.json
    fi
fi

# 5. Handle CODEOWNERS (Governance - Custom Setup Only)
if [[ "$CUSTOMIZE" =~ ^[Yy]$ ]] && [ ! -f ".github/CODEOWNERS" ]; then
    echo -e "\n\033[0;33m🛡️ Creating .github/CODEOWNERS..."
    mkdir -p ".github"
    echo -e "# All files are owned by $GH_HANDLE\n*       $GH_HANDLE" > .github/CODEOWNERS
fi

echo -e "\n\033[0;32m✅ Installation Complete!\033[0m\n"

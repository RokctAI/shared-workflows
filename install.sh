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
)

# Default Values
PROJECT_TYPE="smart"
STARTING_VERSION="0.0.1"
RELEASE_STRATEGY="immediate"
NODE_VERSION="24"
PYTHON_VERSION="3.14"

echo -e "\n\033[1;36m🚀 RokctAI Shared Workflows Installer\033[0m\n"

# --- 1. Interaction ---
read -p "Do you want to customize your workflow setup? (y/N): " CUSTOMIZE
if [[ "$CUSTOMIZE" =~ ^[Yy]$ ]]; then
    echo -e "\n\033[0;33m🛠️ Customizing Setup...\033[0m"
    
    # Project Type
    echo -e "\nSelect Project Type:"
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
    echo "1. immediate (Release on every push to main - Default)"
    echo "2. weekly (Promote Friday RCs to Stable)"
    echo "3. weekly-rc (Pre-release RCs on every push to main)"
    read -p "Choice [1]: " CHOICE_STRAT
    case $CHOICE_STRAT in
        2) RELEASE_STRATEGY="weekly" ;;
        3) RELEASE_STRATEGY="weekly-rc" ;;
        *) RELEASE_STRATEGY="immediate" ;;
    esac

    # Dependency Versions
    echo -e "\nDefault Dependency Versions:"
    read -p "Node.js version [$NODE_VERSION]: " INPUT_NODE
    NODE_VERSION=${INPUT_NODE:-$NODE_VERSION}
    
    read -p "Python version [$PYTHON_VERSION]: " INPUT_PYTHON
    PYTHON_VERSION=${INPUT_PYTHON:-$PYTHON_VERSION}
else
    echo -e "\n\033[0;90m⏩ Using standard fleet defaults (Standard Installation).\033[0m"
fi

# --- 2. Preparing Files ---
TARGET_PATH=".github/workflows"
if [ ! -d "$TARGET_PATH" ]; then
    echo -e "\n📁 Creating $TARGET_PATH..."
    mkdir -p "$TARGET_PATH"
fi

# 3. Download and Patch
for wf in "${VITAL_WORKFLOWS[@]}"; do
    URL="$BASE_URL/$WORKFLOW_DIR/$wf"
    DEST="$TARGET_PATH/$wf"
    echo "📥 Fetching and Patching $wf..."
    
    CONTENT=$(curl -sSL "$URL")
    
    if [[ "$wf" == "build.yml" || "$wf" == "release.yml" ]]; then
        # Project Type
        if [ "$PROJECT_TYPE" != "smart" ]; then
            CONTENT=$(echo "$CONTENT" | sed "s/project_type: .*#/project_type: '$PROJECT_TYPE' #/g")
            CONTENT=$(echo "$CONTENT" | sed "s/project_type: .*/project_type: '$PROJECT_TYPE'/g")
        fi
        # Strategy
        CONTENT=$(echo "$CONTENT" | sed "s/release_strategy: '.*'/release_strategy: '$RELEASE_STRATEGY'/g")
        # Node
        CONTENT=$(echo "$CONTENT" | sed "s/node-version:.*default: '.*'/node-version:\n        type: string\n        default: '$NODE_VERSION'/g")
        # Python
        CONTENT=$(echo "$CONTENT" | sed "s/python-version:.*default: '.*'/python-version:\n        type: string\n        default: '$PYTHON_VERSION'/g")
    fi

    echo "$CONTENT" > "$DEST"
done

# 4. Handle version.json (Skip for Flutter)
if [ "$PROJECT_TYPE" != "flutter" ]; then
    if [ ! -f "version.json" ]; then
        echo -e "\n\033[0;33m📝 Creating version.json ($STARTING_VERSION)...\033[0m"
        echo "{\"version\": \"$STARTING_VERSION\"}" > version.json
    fi
fi

echo -e "\n\033[0;32m✅ Installation Complete! Your repo is now part of the Rokct fleet.\033[0m\n"
echo -e "\033[0;90mNext steps:\033[0m"
echo -e "\033[0;90m1. Verify .github/workflows for your customized settings.\033[0m"
echo -e "\033[0;90m2. Commit and push the new workflows.\033[0m\n"

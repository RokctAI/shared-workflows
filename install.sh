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

echo -e "\n\033[1;36m🚀 RokctAI Shared Workflows Installer\033[0m\n"

# 1. Ensure .github/workflows exists
TARGET_PATH=".github/workflows"
if [ ! -d "$TARGET_PATH" ]; then
    echo "📁 Creating $TARGET_PATH..."
    mkdir -p "$TARGET_PATH"
fi

# 2. Download workflows
for wf in "${VITAL_WORKFLOWS[@]}"; do
    URL="$BASE_URL/$WORKFLOW_DIR/$wf"
    DEST="$TARGET_PATH/$wf"
    echo "📥 Fetching $wf..."
    if ! curl -sSL "$URL" -o "$DEST"; then
        echo -e "\033[0;31m❌ Failed to download $wf\033[0m"
    fi
done

# 3. Handle version.json
if [ ! -f "version.json" ]; then
    echo -e "\033[0;33m📝 Creating default version.json...\033[0m"
    echo '{"version": "0.0.1"}' > version.json
else
    echo -e "\033[0;90mℹ️ version.json already exists, skipping.\033[0m"
fi

echo -e "\n\033[0;32m✅ Installation Complete! Your repo is now part of the Rokct fleet.\033[0m\n"
echo -e "\033[0;90mNext steps:\033[0m"
echo -e "\033[0;90m1. Check .github/workflows/release.yml to verify project_type.\033[0m"
echo -e "\033[0;90m2. Commit and push the new workflows.\033[0m\n"

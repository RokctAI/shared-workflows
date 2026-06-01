#!/usr/bin/env bash
# Copyright (c) 2026, Rokct Intelligence (pty) Ltd.
# For license information, please see license.txt

echo "================================================================================"
echo "          ROKCT PLATFORM CI/CD - LOCAL WORKFLOW DRY-RUN WRAPPER"
echo "================================================================================"

# 1. Audit Prerequisites
echo "🔍 Auditing developer local toolchain..."

if ! command -v docker >/dev/null 2>&1; then
   echo "❌ ERROR: Docker CLI is not installed or not in PATH."
   echo "👉 Get Docker: https://docs.docker.com/get-docker/"
   exit 1
fi

if ! docker info >/dev/null 2>&1; then
   echo "❌ ERROR: Docker daemon is not running."
   echo "👉 Please start Docker Desktop or service and try again."
   exit 1
fi
echo "✅ Docker daemon is running."

if ! command -v act >/dev/null 2>&1; then
   echo "❌ ERROR: Nektos 'act' is not installed."
   echo "👉 Install 'act':"
   echo "   - macOS: brew install act"
   echo "   - Linux: curl -shttps://raw.githubusercontent.com/nektos/act/master/install.sh | sudo bash"
   echo "   - Windows (winget): winget install nektos.act"
   exit 1
fi
echo "✅ 'act' CLI is installed."

# 2. Select Workflow to Run
WORKFLOW_DIR=".github/workflows"
if [ ! -d "$WORKFLOW_DIR" ]; then
   echo "❌ ERROR: Could not locate .github/workflows directory."
   exit 1
fi

echo ""
echo "Select a workflow to dry-run locally:"
workflows=($(find "$WORKFLOW_DIR" -maxdepth 1 -name "*.yml" -o -name "*.yaml" | sort))

if [ ${#workflows[@]} -eq 0 ]; then
   echo "❌ No workflows found in $WORKFLOW_DIR."
   exit 1
fi

for i in "${!workflows[@]}"; do
   echo "  [$i] $(basename "${workflows[$i]}")"
done

echo ""
read -rp "Enter choice [0-$(( ${#workflows[@]} - 1 ))]: " choice

if [[ ! "$choice" =~ ^[0-9]+$ ]] || [ "$choice" -lt 0 ] || [ "$choice" -ge ${#workflows[@]} ]; then
   echo "❌ Invalid choice. Aborting."
   exit 1
fi

CHOSEN_WORKFLOW="${workflows[$choice]}"
echo "🚀 Selected: $CHOSEN_WORKFLOW"

# 3. Setup Safe Mock Contexts
echo "🔒 Creating temporary mock environments (.secrets.mock, .env.mock)..."
SECRETS_FILE=".secrets.mock"
ENV_FILE=".env.mock"

cat <<EOF > "$SECRETS_FILE"
MONOREPO_PAT=mock_monorepo_pat_token
APP_ID=12345
APP_PRIVATE_KEY=mock_app_private_key_pem_file
COUNTER_API_KEY=mock_counter_api_key_badge
EOF

cat <<EOF > "$ENV_FILE"
GITHUB_ACTOR=RokctBOT
GITHUB_REPOSITORY=RokctAI/shared-workflows
GITHUB_EVENT_NAME=push
EOF

# 4. Invoke Act
echo "⚡ Executing local dry-run via act..."
echo "--------------------------------------------------------------------------------"
act -W "$CHOSEN_WORKFLOW" --secret-file "$SECRETS_FILE" --env-file "$ENV_FILE"
ACT_EXIT_CODE=$?
echo "--------------------------------------------------------------------------------"

# 5. Clean up
echo "🧹 Performing secure environment cleanup..."
rm -f "$SECRETS_FILE" "$ENV_FILE"

if [ $ACT_EXIT_CODE -eq 0 ]; then
   echo "✅ Dry-run completed successfully!"
else
   echo "❌ Dry-run execution failed. Inspect logs above for debug information."
fi

exit $ACT_EXIT_CODE

import re

filepath = '.github/workflows/universal-linter.yml'
with open(filepath, 'r') as f:
    content = f.read()

# Pattern for GitHub App Permissions
old = """                   echo "### 🚨 Action Required: GitHub App Permissions" >> "$GITHUB_STEP_SUMMARY"
                   echo "The Fleet Standardizer attempted to update your workflow files but failed due to missing permissions." >> "$GITHUB_STEP_SUMMARY"
                   echo "- **Error**: $(grep -i "permission" push_error.log | head -n 1)" >> "$GITHUB_STEP_SUMMARY"
                   echo "- **Fix**: Go to your GitHub App settings > **Permissions & events** > **Repository permissions** > Set **Workflows** to **Read & Write**." >> "$GITHUB_STEP_SUMMARY"
                   echo "⚠️ CI is proceeding but your repository is out of sync with fleet standards." >> "$GITHUB_STEP_SUMMARY\""""

# Wait, I already fixed this block manually in Turn 73 with a replace_with_git_merge_diff.
# Let's check the current content.

# API Reference: pr_auto_labeler

Source file: `scripts/pr_auto_labeler.py`

## Documented Module Functions

### `def get_git_commits()`
Fetch recent commit messages on the current branch.

### `def match_conventional(text)`
Scan a line of text for standard conventional commits pattern.

### `def rule_based_labeling(title, body, commits)`
Determine labels based on regex rules on PR title, description, and commit messages.

### `def ai_labeling(title, body, groq_api_key)`
Use Groq Llama 3 to classify the PR and return tags.

### `def apply_labels(repo, pr_number, labels, token)`
Apply labels to PR via GitHub REST API.

# Agent Memory & Lessons Learned

**Rule**: Before asking a question or starting a task, the Agent **MUST** read this file to check for past lessons or user preferences.

## User Profiles
*   **[Name]**:
    *   **Safe ID**: [ray.dev.9ac2b1] (Used for filenames)
    *   **Role/Preferences**: [Details]
*   *(Agent: Add new users here as they appear)*

## Global Preferences
*   **Session Retention**: [Forever] (Options: Forever, 1 Month, 1 Week)
*   **Checkpoint Policy**: [Value] (Options: Frequent, Manual) -> *Set 'Frequent' for Cloud Agents*
*   [Active] Prefer "Frappe" for backend.
*   [Active] Prefer "Next.js + AI SDK" for frontend.
*   [Active] Prefer "Flutter" for mobile.
*   [Active] "Premium" design aesthetic is non-negotiable.

## Lessons Learned
*(Agent to append new lessons here when a mistake is made or a correction is received)*

*   **2026-06-03** - Align step list items in GHA workflows exactly; offset indentation breaks YAML parser steps blocks. Ensure variables in bash run blocks are double-quoted to satisfy shellcheck/actionlint rules.
*   **2026-06-11** - Local git exclusions (`.git/info/exclude` or `.gitignore`) only apply to untracked files. If a file is already tracked, overwriting it with private/local changes will still register as a modification. To prevent dirty/merged files from leaking into source release assets, package them directly from the target commit using `git archive` instead of zipping from the workspace filesystem.


## Safe ID
sinyage.f74d39

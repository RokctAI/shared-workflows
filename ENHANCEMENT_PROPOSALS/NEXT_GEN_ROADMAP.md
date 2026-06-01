# RokctAI Shared Workflows — Next-Generation Roadmap

This document outlines the next-generation architectural enhancements proposed for the RokctAI Shared Workflows library to further improve developer experience, pipeline resilience, and automated insights.

---

## 1. Automated Inputs Deprecation Warners
**Goal:** Prevent build failures and configuration drift in downstream repositories by warning developers when they use deprecated parameters or old workflows.

### Key Features:
- **Parameter Inspection:** Workflows analyze incoming inputs. If deprecated options (e.g. legacy env vars) are passed, write a warning using `::warning::` with upgrading instructions.
- **Version Enforcement:** Alert developers if their local repository's workflow configuration is lagging more than 3 minor versions behind the latest stable release.

### Implementation Draft:
```yaml
- name: Audit Inputs & Version Drift
  run: |
    # Check if a deprecated input is set
    if [ -n "${{ inputs.legacy_param }}" ]; then
       echo "::warning::Input 'legacy_param' is deprecated and will be removed in v2.0.0. Please migrate to 'modern_param'."
    fi
```

---

## 2. AI Commit & PR Auto-Labeler
**Goal:** Automate PR categorization and tagging by using lightweight AI to parse diffs, maintaining clean release history without requiring manual developer labeling.

### Key Features:
- **Diff Analysis:** Inspect changed file paths and commit messages (e.g., matching Conventional Commit styles).
- **Auto-Labeling:** Automatically assign labels like `feat`, `fix`, `chore`, or `docs` to the GitHub PR using the GitHub API before validation checks run.

---

## 3. Smart Flaky Test Retriers
**Goal:** Distinguish between genuine code regressions and flaky network/infrastructure issues during unit testing to ensure faster PR merges.

### Key Features:
- **Node.js (Jest/pnpm):** Inject auto-retry flags like `--retry=3` dynamically when running tests.
- **Flutter Test Recovery:** Capture test failures, filter out known flaky assertions (e.g., font loading or system layout constraints), and automatically run only the failed tests a second time before returning exit code 1.

---

## 4. Local Workflow Dry-Run Helper
**Goal:** Accelerate CI pipeline development by letting platform engineers dry-run and debug actions on their local machines before pushing code.

### Key Features:
- **CLI Wrapper:** A script `rokct-ci-debug.sh` that checks for local prerequisites (`docker`, `act`).
- **Mock Contexts:** Generates mock GitHub secrets and environment variables mimicking actual production runner states for accurate local validation.

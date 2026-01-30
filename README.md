# Universal Shared Workflows

A library of reusable GitHub Actions for "Universal" CI/CD.
Designed to work with **Flutter**, **Node.js**, **Laravel**, and **Generic** projects.

## Features
*   **Version Detection**: Automatically finds `pubspec.yaml` (Flutter), `package.json`, `__init__.py`, or `versions.json`.
*   **Delta Releases**: Generates `update_package.zip` with only modified files.
*   **Branch Support**: Handles `-dev` suffixes for `develop` branch releases automatically.
*   **RC Cleanup**: Automatically removes release candidate releases and tags after promotion to stable.
*   **Branch Protection**: Prevents direct commits to `main` (Recommended Setup).

## How to Use (The "Drop-in" Method) 🚀

This repository comes with a pre-configured Scaffold in the `examples/` directory.

### Quick Start
To equip your repository with **Release Automation, Linting, Testing, and Bot Helpers**, simply copy the scaffold:

1.  **Clone this repo** (or navigate to it).
2.  **Copy contents** of `examples/` to your target repo's `.github/` folder.

**Folder Structure (Target Repo):**
```text
my-app/
├── .github/
│   ├── dependabot.yml
│   └── workflows/
│       ├── release.yml      (Automated Release & AI Notes)
│       ├── test.yml         (CI/CD Pipeline)
│       ├── linter.yml       (Code Quality)
│       ├── assign.yml       (Auto Assign PRs)
│       ├── merge.yml        (Auto Merge Dependabot)
│       ├── stale.yml        (Close old issues)
│       └── ... (13+ workflows)
```

### Configuration ⚙️

After copying the files, you **MUST** review and update the following:

1.  **`workflows/merge.yml`**:
    *   Update `allowed_users` to your GitHub username(s).
    *   *Example:* `allowed_users: 'YourUsername,CoWorker'`
    
2.  **`workflows/release.yml`**:
    *   Update `brain_endpoint` to your own AI server (or remove if not using AI Release Notes).
    *   *Default Strategy:* `weekly`. Change to `immediate` if you prefer releases on every version bump.
    *   **RC Cleanup Options**:
        *   `cleanup_rc_releases: true` - Automatically delete RC releases after promotion to stable
        *   `one_time_cleanup_cutoff_date: '2026-02-01'` - Run one-time cleanup of historical RCs after this date
        *   Leave `one_time_cleanup_cutoff_date` empty (`''`) to disable one-time cleanup

3.  **`dependabot.yml`**:
    *   Verify the schedule and package ecosystems match your project (e.g., `pip` vs `npm`).

### Manual Setup
If you prefer picking specific workflows, you can copy individual `.yml` files from `examples/workflows/` to your `.github/workflows/` directory.


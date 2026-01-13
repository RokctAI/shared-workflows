# Universal Shared Workflows

A library of reusable GitHub Actions for "Universal" CI/CD.
Designed to work with **Flutter**, **Node.js**, **Laravel**, and **Generic** projects.

## Features
*   **Version Detection**: Automatically finds `pubspec.yaml` (Flutter), `package.json`, `__init__.py`, or `versions.json`.
*   **Delta Releases**: Generates `update_package.zip` with only modified files.
*   **Branch Support**: Handles `-dev` suffixes for `develop` branch releases automatically.
*   **Branch Protection**: Prevents direct commits to `main` (Recommended Setup).

## How to Use

### 1. In a App (Flutter, Frappe, Node)

Create `.github/workflows/release.yml`:

```yaml
name: Auto Release
on:
  push:
    branches: [main, develop]
    paths: 
      - 'pubspec.yaml' # For Flutter
      - 'versions.json' # For others (Prioritized)
      - 'package.json' 

jobs:
  release:
    uses: RokctAI/shared-workflows/.github/workflows/universal-release.yml@main
    secrets: inherit
```

### 2. Using `versions.json`

If your project (e.g., a Laravel app or a Python script) does not have a standard version file, create a `versions.json` in your root or source folder:

```json
{
  "version": "1.0.0"
}
```

The workflow will verify this file, check if `v1.0.0` exists, and if not, create the release and delta zip.

### 3. Auto Merge

Create `.github/workflows/merge.yml`:

```yaml
name: Auto Merge
on: pull_request

jobs:
  merge:
    uses: RokctAI/shared-workflows/.github/workflows/universal-merge.yml@main
    with:
      allowed_users: 'RendaniSinyage,MyCoFounder'
    secrets: inherit
```

### 4. Setup Branch Protection (Recommended) 🛡️

To ensure the "Auto Merge" workflow is the *only* way code enters production, and to prevent accidental direct commits to `main`, configure Branch Protection:

1.  Go to your Repository **Settings** on GitHub.
2.  Click **Branches** (sidebar).
3.  Click **Add rule**.
4.  **Branch name pattern**: `main`
5.  Check **Require a pull request before merging**.
    *   (Optional) Check **Require approvals**.
6.  Check **Do not allow bypassing the above settings**.
7.  Click **Create**.

### 5. Security Checks 🛡️

Create `.github/workflows/security.yml`:

```yaml
name: Security Scan
on:
  push:
    branches: [main]
  pull_request:

jobs:
  scan:
    uses: RokctAI/shared-workflows/.github/workflows/universal-security.yml@main
    secrets: inherit
```

### 6. Code Quality (Linting) 🧹

Create `.github/workflows/linter.yml`:

```yaml
name: Code Quality
on:
  push:
    branches: [main]
  pull_request:

jobs:
  lint:
    uses: RokctAI/shared-workflows/.github/workflows/universal-linter.yml@main
    secrets: inherit
```

### 7. Issue Hygiene (Stale & ToDo) 🤖

Create `.github/workflows/stale.yml`:

```yaml
name: Stale
on:
  schedule:
    - cron: '30 1 * * *' # Run every night at 1:30 AM

jobs:
  stale:
    uses: RokctAI/shared-workflows/.github/workflows/universal-stale.yml@main
    secrets: inherit
```

Create `.github/workflows/todo.yml`:

```yaml
name: ToDo Bot
on:
  push:
    branches: [main]

jobs:
  todo:
    uses: RokctAI/shared-workflows/.github/workflows/universal-todo.yml@main
    secrets: inherit
```

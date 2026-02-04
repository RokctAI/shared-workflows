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
│       ├── build.yml        (Manual APK Build)
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

4.  **`workflows/linter.yml`**:
    *   `run-build-runner: true` - Set to `true` if your Flutter project uses Freezed/JSON Serializable and needs code generation before analysis.

5.  **Android Signing & Secrets (For APK Builds)** 🔐:
    *   To enable automatic APK builds in `release.yml`, set `build_android: true`.
    *   To use manual builds via `build.yml`, just ensure these secrets are set.
    *   **NEVER commit your `.jks` keystore file to the repository.**
    *   Instead, encode it and store it as a GitHub Secret:
        1.  **Encode Keystore:**
            *   **Windows (Powershell):** `[Convert]::ToBase64String([IO.File]::ReadAllBytes("path\to\your-key.jks")) > key_b64.txt`
            *   **Linux/Mac:** `base64 -w 0 path/to/your-key.jks > key_b64.txt`
        2.  **Add Secrets** in GitHub Repo Settings -> Secrets and variables -> Actions:
            *   `KEY_JKS`: Paste the content of `key_b64.txt`.
            *   `KEY_PASSWORD`: Your keystore password.
            *   `ALIAS_PASSWORD`: Your key alias password.
        3.  **Google Services (Optional):**
            *   If you use Firebase/Google Sign-In, encode your `google-services.json` the same way.
            *   Add it as a secret named `GOOGLE_SERVICES_JSON`.

6.  **Windows Builds (For Desktop Apps)** 🪟:
    *   To enable Windows Zip builds in `release.yml`, set `build_windows: true`.
    *   **Note**: Windows builds are skipped for RC releases (Weekly Strategy) to save time, but are included in Dev, Promote, and Stable (Immediate) releases.
    *   The output will be attached as `app-windows-vX.Y.Z.zip`.

### Manual Setup
If you prefer picking specific workflows, you can copy individual `.yml` files from `examples/workflows/` to your `.github/workflows/` directory.

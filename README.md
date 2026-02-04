# Universal Shared Workflows

<!-- usage-badge-start -->
![Total Builds](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fapi.counterapi.dev%2Fv2%2Frokctai%2Fusage&query=%24.value&label=Total%20Builds&color=blue)
<!-- usage-badge-end -->

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

43: 1.  **`workflows/merge.yml`**:
44:     *   Update `allowed_users` to your GitHub username(s).
45:     *   *Example:* `allowed_users: 'YourUsername,CoWorker'`
46:     
47: 2.  **`workflows/release.yml`**:
48:     *   Update `brain_endpoint` to your own AI server (or remove if not using AI Release Notes).
49:     *   *Default Strategy:* `weekly`. Change to `immediate` if you prefer releases on every version bump.
50:     *   **RC Cleanup Options**:
51:         *   `cleanup_rc_releases: true` - Automatically delete RC releases after promotion to stable
52:         *   `one_time_cleanup_cutoff_date: 'YYYY-MM-DD'` - Run one-time cleanup of historical RCs after this date
53:         *   Leave `one_time_cleanup_cutoff_date` empty (`''`) to disable one-time cleanup
54: 
55: 3.  **`dependabot.yml`**:
56:     *   Verify the schedule and package ecosystems match your project (e.g., `pip` vs `npm`).
57: 
58: 4.  **`workflows/linter.yml`**:
59:     *   `run-build-runner: true` - Set to `true` if your Flutter project uses Freezed/JSON Serializable and needs code generation before analysis.
1.  **`workflows/merge.yml`**:
    *   Update `allowed_users` to your GitHub username(s).
    *   *Example:* `allowed_users: 'YourUsername,CoWorker'`
    
2.  **`workflows/release.yml`**:
    *   Update `brain_endpoint` to your own AI server (or remove if not using AI Release Notes).
    *   *Default Strategy:* `weekly`. Change to `immediate` if you prefer releases on every version bump.
    *   **RC Cleanup Options**:
        *   `cleanup_rc_releases: true` - Automatically delete RC releases after promotion to stable
        *   `one_time_cleanup_cutoff_date: 'YYYY-MM-DD'` - Run one-time cleanup of historical RCs after this date
        *   Leave `one_time_cleanup_cutoff_date` empty (`''`) to disable one-time cleanup

3.  **`dependabot.yml`**:
    *   Verify the schedule and package ecosystems match your project (e.g., `pip` vs `npm`).

        *   Values: `true` / `false` (default: `false` for `install-erpnext` and `install-payments`).

5.  **`workflows/universal-node-ci.yml`**:
    *   Designed for **Next.js**, **React**, or generic Node.js apps.
    *   **Features**: Setup Node, Cache Dependencies, Install, Build, Test, Telemetry.
    *   **Usage**: The `build.yml` example is "Smart"—it auto-detects `package.json` vs `pubspec.yaml` and calls this workflow automatically for Node projects.

6.  **"Smart" Build Example (`examples/workflows/build.yml`)** 🧠:
    *   This single file works for both **Flutter** and **Node.js** projects.
    *   **How it works**: It detects your project type (`pubspec.yaml` or `package.json`) and runs the appropriate pipeline (`universal-flutter-build` or `universal-node-ci`).
    *   **Recommendation**: Rename `examples/workflows` to `.github` in your new project.

7.  **Android Secrets (for Signing)** 🤖:
    *   **Encode Keystore:**
        *   **Windows (Powershell):**
            ```powershell
            [Convert]::ToBase64String([IO.File]::ReadAllBytes("android\app\keys\upload-keystore.jks"))
            ```
            *(Note: Adjust the path if your key is named differently, e.g., `key.jks`)*
        *   **Linux/Mac:** `base64 -w 0 android/app/keys/upload-keystore.jks > key_b64.txt`
    *   **Add Secrets** in GitHub Repo Settings -> Secrets and variables -> Actions:
        *   `KEY_JKS`: Paste the content of `key_b64.txt`.
        *   `KEY_PASSWORD`: Your keystore password.
        *   `ALIAS_PASSWORD`: Your key alias password.
        *   **Google Services (Optional)::**
            *   If you use Firebase/Google Sign-In, encode your `google-services.json` (Android) and `GoogleService-Info.plist` (iOS) using these PowerShell commands (run from project root):
                *   **Android:** `[Convert]::ToBase64String([IO.File]::ReadAllBytes("android\app\google-services.json"))`
                *   **iOS:** `[Convert]::ToBase64String([IO.File]::ReadAllBytes("ios\Runner\GoogleService-Info.plist"))`
            *   Add the output strings as secrets named `GOOGLE_SERVICES_JSON` and `IOS_GOOGLE_SERVICE_INFO_PLIST` respectively.

6.  **Windows Builds (For Desktop Apps)** 🪟:
    *   To enable Windows Zip builds in `release.yml`, set `build_windows: true`.
    *   **Note**: Windows builds are skipped for RC releases (Weekly Strategy) to save time, but are included in Dev, Promote, and Stable (Immediate) releases.
    *   The output will be attached as `app-windows-vX.Y.Z.zip`.

7.  **iOS Builds (Stable Only Strategy)** 🍎:
    *   To save costs, iOS builds are recommended to be run **only on stable releases** via a separate workflow.
    *   **Setup**: Copy [`examples/workflows/release-ios.yml`](examples/workflows/release-ios.yml) to your `.github/workflows/` folder.
    *   **Cost Control**: The example includes a `MAX_MONTHLY_BUILDS` variable to limit expensive Mac runner usage.
    *   **Secrets Required**:
        *   `IOS_P12_BASE64`: Base64 encoded Distribution Certificate (.p12).
        *   `IOS_MOBILEPROVISION_BASE64`: Base64 encoded Provisioning Profile.
        *   `IOS_CERTIFICATE_PASSWORD`: Password for the .p12 certificate.
        *   `IOS_GOOGLE_SERVICE_INFO_PLIST` (Optional): Base64 encoded `GoogleService-Info.plist` for Firebase.

    8.  **macOS Builds (Desktop)** 🖥️:
        *   Supported via `universal-flutter-build.yml` with `build-type: macos`.
        *   **Setup**: Copy [`examples/workflows/release-macos.yml`](examples/workflows/release-macos.yml).
        *   **Artifact**: Produces a `macos-app.zip` containing the signed `.app`.
        *   **Secrets**: Uses the same `IOS_...` signing secrets as iOS (requires a Mac Certificate).

    9.  **Usage Tracking (Optional)** 📡:
    *   To track total builds across all repos, set the `COUNTER_API_KEY` secret.
    *   The workflows will ping your private counter on every run.

### Manual Setup
If you prefer picking specific workflows, you can copy individual `.yml` files from `examples/workflows/` to your `.github/workflows/` directory.

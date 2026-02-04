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
60: 
61: 5.  **Android Signing & Secrets (For APK Builds)** 🔐:
62:     *   To enable automatic APK builds in `release.yml`, set `build_android: true`.
63:     *   To use manual builds via `build.yml`, just ensure these secrets are set.
64:     *   **NEVER commit your `.jks` keystore file to the repository.**
65:     *   Instead, encode it and store it as a GitHub Secret:
66:         1.  **Encode Keystore:**
67:             *   **Windows (Powershell):** `[Convert]::ToBase64String([IO.File]::ReadAllBytes("path\to\your-key.jks")) > key_b64.txt`
68:             *   **Linux/Mac:** `base64 -w 0 path/to/your-key.jks > key_b64.txt`
69:         2.  **Add Secrets** in GitHub Repo Settings -> Secrets and variables -> Actions:
70:             *   `KEY_JKS`: Paste the content of `key_b64.txt`.
71:             *   `KEY_PASSWORD`: Your keystore password.
72:             *   `ALIAS_PASSWORD`: Your key alias password.
73:         3.  **Google Services (Optional):**
74:             *   If you use Firebase/Google Sign-In, encode your `google-services.json` the same way.
75:             *   Add it as a secret named `GOOGLE_SERVICES_JSON`.
76: 
77: 6.  **Windows Builds (For Desktop Apps)** 🪟:
78:     *   To enable Windows Zip builds in `release.yml`, set `build_windows: true`.
79:     *   **Note**: Windows builds are skipped for RC releases (Weekly Strategy) to save time, but are included in Dev, Promote, and Stable (Immediate) releases.
80:     *   The output will be attached as `app-windows-vX.Y.Z.zip`.
81: 
82: 7.  **iOS Builds (Stable Only Strategy)** 🍎:
83:     *   To save costs, iOS builds are recommended to be run **only on stable releases** via a separate workflow.
84:     *   **Setup**: Copy [`examples/workflows/release-ios.yml`](examples/workflows/release-ios.yml) to your `.github/workflows/` folder.
85:     *   **Cost Control**: The example includes a `MAX_MONTHLY_BUILDS` variable to limit expensive Mac runner usage.
86:     *   **Secrets Required**:
87:         *   `IOS_P12_BASE64`: Base64 encoded Distribution Certificate (.p12).
88:         *   `IOS_MOBILEPROVISION_BASE64`: Base64 encoded Provisioning Profile.
89:         *   `IOS_CERTIFICATE_PASSWORD`: Password for the .p12 certificate.
### Manual Setup
If you prefer picking specific workflows, you can copy individual `.yml` files from `examples/workflows/` to your `.github/workflows/` directory.

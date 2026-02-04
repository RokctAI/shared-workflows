# Universal Shared Workflows

<!-- usage-badge-start -->
![Total Builds](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fapi.counterapi.dev%2Fv2%2Frokctai%2Fusage%2Fstats&query=%24.data.up_count&label=Total%20Builds&color=blue)
![Stable](https://img.shields.io/github/v/release/RokctAI/shared-workflows?label=Stable&color=0052cc)
![Candidate](https://img.shields.io/github/v/tag/RokctAI/shared-workflows?label=Candidate&color=e67e22&include_prereleases)
<!-- usage-badge-end -->

A library of reusable GitHub Actions for "Universal" CI/CD.
Designed for **pnpm** (preferred), **Flutter**, **Node.js**, **Frappe**, and **Documentation** projects.

## Features

*   **🧠 Smart Detection**: The `build.yml` workflow automatically scans your repo for `pubspec.yaml` (Flutter) or `package.json` (Node.js) and runs the correct pipeline.
*   **📦 Universal Release**: One workflow (`release.yml`) handles Semantic Versioning, AI Release Notes, and Git Tagging for ALL project types.
*   **📱 Multi-Platform**: Supports Android (APK/Bundle), iOS (IPA), macOS (.app), Windows (Zip), and Web.
*   **🧪 Universal Testing**: Specialized CI for Node.js (Fast) and Frappe (Database-enabled).
*   **🧹 Maintenance Bots**: Auto-merge Dependabot, Stale issue closer, PR Assignee, Labeler, and more.

---

## 🚀 How to Use (The "Drop-in" Standard)

All repositories in the fleet should typically have the standard set of workflows.

### 1. Setup
Simply copy the entire `examples/workflows` directory to your repository:

```bash
# Run from the root of your new repo
cp -r ../shared-workflows/examples/workflows .github/workflows
```

### 2. What you get
This installs **"The Standard Fleet"**:

| Workflow | Purpose | Smart Logic 🧠 |
| :--- | :--- | :--- |
| **`build.yml`** | **CI Build** | Auto-detects **Flutter** vs **Node**. Skips if neither (e.g. pure Python/Docs). |
| **`release.yml`** | **Release** | Auto-handles Versioning & Tags. Configurable for Android/Windows builds. |
| **`frappe-ci.yml`** | **Frappe Test** | Special workflow for Frappe Apps (MariaDB+Redis). |
| **`linter.yml`** | **Code Quality** | Runs Flake8 (Python), Flutter Analyze, or ESLint (JS) based on files found. |
| **`...others`** | **Bots** | Automations for Labeling, Assigning, Merging, Security, etc. |

### 3. Configuration ⚙️

After copying, check these files:

#### A. `workflows/release.yml`
*   **Next.js / Web**: Ensure `build_android: false` (or remove the line).
*   **Flutter**: Set `build_android: true` if you want APKs.
*   **Windows**: Set `build_windows: true` for Desktop apps.
*   **AI Notes**: Update `brain_endpoint` or remove if not using AI.

#### B. `workflows/frappe-ci.yml`
*   Only needed for **Frappe** apps. Delete if not using Frappe.
*   Set `install-erpnext: true` or `install-payments: true` if your app requires them.

#### C. `workflows/merge.yml`
*   Update `allowed_users` to your GitHub username(s) for auto-merging.

---

## 🔐 Secrets Setup

Ensure these secrets are set in your Repository (or Org) settings. **All workflows use `secrets: inherit`**, so you only need to set them once.

### 1. Android Signing 🤖
*   **`KEY_JKS`**: Base64 encoded `.jks` file.
    *   *PowerShell*: `[Convert]::ToBase64String([IO.File]::ReadAllBytes("android\app\keys\upload-keystore.jks"))`
*   **`KEY_PASSWORD`**: Keystore password.
*   **`ALIAS_PASSWORD`**: Key alias password.
*   **`GOOGLE_SERVICES_JSON`**: Base64 encoded `google-services.json` (Optional, for Firebase).

### 2. iOS & macOS Signing 🍎
*   **`IOS_P12_BASE64`**: Base64 encoded Distribution Certificate (.p12).
*   **`IOS_MOBILEPROVISION_BASE64`**: Base64 encoded Provisioning Profile.
*   **`IOS_CERTIFICATE_PASSWORD`**: Password for the .p12 certificate.
*   **`IOS_GOOGLE_SERVICE_INFO_PLIST`**: Base64 encoded `GoogleService-Info.plist` (Optional).

### 3. Telemetry 📡
*   **`COUNTER_API_KEY`**: Key for the `counterapi.dev` badge. All standard workflows will try to ping this if present.

---

## 🧩 Advanced Workflows

These are available in `examples/workflows` but usually strictly for **Flutter mobile/desktop** apps:

*   **`release-ios.yml`**: Builds `.ipa`. Recommended to run **only on Stable releases** to save costs ($$$).
*   **`release-macos.yml`**: Builds `.app` / `.zip` for macOS Desktop. Same cost warning.

---

## 🛠️ Architecture

*   **`universal-flutter-build.yml`**: The heavy lifter for Dart/Flutter.
*   **`universal-node-ci.yml`**: The lightweight builder for Next.js/React.
*   **`universal-frappe-ci.yml`**: The environment builder for Python/Bench.
*   **`universal-release.yml`**: The brain of the operation.

*Maintained by the Platform Engineering Team.*

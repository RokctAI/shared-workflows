# Universal Shared Workflows

<!-- usage-badge-start -->
![Total Builds](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fapi.counterapi.dev%2Fv2%2Frokctai%2Fusage%2Fstats&query=%24.data.up_count&label=Total%20Builds&color=blue)
![Stable](https://img.shields.io/github/v/release/RokctAI/shared-workflows?label=Stable&color=0052cc)
![Candidate](https://img.shields.io/github/v/tag/RokctAI/shared-workflows?label=Candidate&color=e67e22&include_prereleases)
<!-- usage-badge-end -->

A library of reusable GitHub Actions for "Universal" CI/CD.
Designed for **pnpm** (preferred), **Flutter**, **Node.js**, **Frappe**, and **Documentation** projects.

![All Checks Passed](./images/checks_passed.png)

## Features

*   **🛡️ CI-Gate Orchestration**: The new `universal-pipeline.yml` chains `Security` -> `Lint` -> `CI` -> `Release` sequentially. Tags are only created if all quality checks pass.
*   **🧠 Smart Detection**: The `build.yml` workflow automatically scans your repo for `pubspec.yaml` (Flutter), `package.json` (Node.js), or Frappe patterns and runs the correct pipeline via the orchestrator.
*   **📦 Universal Release**: One workflow (`release.yml`) handles Semantic Versioning, AI Release Notes, and Git Tagging for ALL project types, protected by the CI-Gate.
*   **📱 Multi-Platform**: Supports Android (APK/Bundle), iOS (IPA), macOS (.app), Windows (Zip), and Web.
*   **🧹 Maintenance Bots**: Auto-merge Dependabot, Stale issue closer, PR Assignee, Labeler, and more.

---

## 🚀 How to Use (The "Drop-in" Standard)

All repositories in the fleet should typically have the standard set of workflows.

### 1. Simple Bootstrap (Recommended)

Run our interactive one-liner from the root of your repository. It will bootstrap your repo with the standard fleet workflows and a `version.json`. 

> [!NOTE]
> It will ask if you want to **Standardize** (Full Defaults) or **Customize** (Specific Project Type, Versions, etc.).

**Windows (PowerShell):**
```powershell
iwr -useb https://raw.githubusercontent.com/RokctAI/shared-workflows/main/install.ps1 | iex
```

**Unix / macOS / Linux (Bash):**
```bash
curl -sSL https://raw.githubusercontent.com/RokctAI/shared-workflows/main/install.sh | bash
```

### 2. Manual Copy (Local Development)
If you have `shared-workflows` cloned locally as a sibling to your current project, you can copy the files directly:

```bash
# Assumes your folders are: 
# /Work/shared-workflows/
# /Work/your-project/ <--- Run from here
cp -r ../shared-workflows/examples/workflows .github/workflows
```

### 3. What you get
This installs **"The Unified Fleet"**:

| Workflow | Purpose | Orcherstration ⛓️ |
| :--- | :--- | :--- |
| **`build.yml`** | **Manual/Push CI** | Uses `universal-pipeline.yml`. Auto-detects **Flutter**, **Node**, or **Frappe**. |
| **`release.yml`** | **Auto Release** | Uses `universal-pipeline.yml`. Locked to **Friday 11 PM UTC**. |
| **`linter.yml`** | **Code Quality** | Runs Flake8, Flutter Analyze, or ESLint based on file patterns. |
| **`security.yml`**| **Vulnerability Fix**| Automated security scanning and patching. |
| **`...others`** | **Bots** | Automations for Labeling, Assigning, Merging, Stale, etc. |

### 3. Configuration ⚙️

After copying, check these files:

#### A. `workflows/release.yml`
*   **Project Type**: Set `project_type` to `'frappe'`, `'node'`, or `'flutter'`.
*   **Next.js / Web**: Ensure `build_android: false`.
*   **Flutter**: Set `build_android: true` if you want APKs.
*   **AI Notes**: Update `brain_endpoint` or remove if not using AI.
*   **Version Format**: Use `version_format` (e.g., `'##.##.##'`) to control how the automated bumper behaves.

---

## 🏆 Stable Release Strategy (`@v###` vs `@latest`)

To maintain a healthy balance between **speed** and **stability**, we use a tiered tagging strategy:

| Tag Stage | Target Audience | Policy |
| :--- | :--- | :--- |
| **`@main`** | Core Developers | Bleeding edge. Updates on every push to `shared-workflows`. |
| **`@latest`** | Fleet Applications | **Production Default.** Represents the latest *verified* stable release. |
| **`@v1.2.3`** | Mission Critical | **Pinned.** Locked to a specific snapshot. Never changes. |

### 🔒 The "Immutable Snapshot" Logic
When you promote an RC to Stable in this repository:
1.  **Pinning**: The `universal-release` workflow automatically scans all internal calls and replaces `@main` or `@latest` with the **actual version tag** (e.g., `@v1.2.3`).
2.  **Immutability**: This creates a 100% frozen environment for that version.
3.  **Flexibility**: The `main` branch is immediately reverted back to `@main` for ongoing development.

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

*   **`universal-pipeline.yml`**: The Orchestrator. Chains Security, Lint, CI, and Release.
*   **`universal-flutter-build.yml`**: The heavy lifter for Dart/Flutter.
*   **`universal-node-ci.yml`**: The lightweight builder for Next.js/React.
*   **`universal-frappe-ci.yml`**: The environment builder for Python/Bench.
*   **`universal-release.yml`**: The release and tagging engine.

*Maintained by the Platform Engineering Team.*

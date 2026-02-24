# 🛠️ System Stability & Installer Integrity

To maintain a seamless developer experience, any changes to the workflow files in `examples/workflows/` **MUST** be reflected in the installer scripts.

## ⚠️ Important Rules

1.  **Template Consistency**: If you add new inputs, outputs, or significant structural changes to `build.yml` or `release.yml`, ensure the `install.ps1` and `install.sh` patching logic (regex/sed) is updated to handle them.
2.  **Versioning Schema**: The "Pin-on-Release" logic in `universal-release.yml` assumes a specific internal reference format. Do not change the `@main` tagging convention without updating the pinning script.
3.  **Cross-Platform Parity**: Always update **both** `install.ps1` (Windows) and `install.sh` (Unix) simultaneously.
4.  **Flutter Exemption**: Flutter projects do not use `version.json`. Any "mandatory" versioning features added to the fleet must remain optional for Flutter to avoid breaking the mobile pipeline.

## 🛡️ Glossary of Safety Features

-   **Zero-Drift (Parity)**: We use an automated "Parity Check" in CI to ensure the Bash script and PowerShell script produce **identical** output. If one script is updated but the other is forgotten, the build will fail. 
-   **Local Mode (`--local`)**: This is an internal flag used by our automated tests (`installer-parity.yml`). It tells the script to copy workflow templates from the local repo folder instead of downloading them from GitHub. This is how we verify that your new changes haven't broken the installation process before you even push them.

## 🧪 Testing the Installer
Before pushing changes to the installer scripts, test them locally in a dummy repository:
```powershell
# Windows
cat ..\shared-workflows\install.ps1 | iex

# Unix
cat ../shared-workflows/install.sh | bash
```

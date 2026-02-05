# 🛠️ System Stability & Installer Integrity

To maintain a seamless developer experience, any changes to the workflow files in `examples/workflows/` **MUST** be reflected in the installer scripts.

## ⚠️ Important Rules

1.  **Template Consistency**: If you add new inputs, outputs, or significant structural changes to `build.yml` or `release.yml`, ensure the `install.ps1` and `install.sh` patching logic (regex/sed) is updated to handle them.
2.  **Versioning Schema**: The "Pin-on-Release" logic in `universal-release.yml` assumes a specific internal reference format. Do not change the `@main` tagging convention without updating the pinning script.
3.  **Cross-Platform Parity**: Always update **both** `install.ps1` (Windows) and `install.sh` (Unix) simultaneously.
4.  **Flutter Exemption**: Flutter projects do not use `version.json`. Any "mandatory" versioning features added to the fleet must remain optional for Flutter to avoid breaking the mobile pipeline.

## 🧪 Testing the Installer
Before pushing changes to the installer scripts, test them locally in a dummy repository:
```powershell
# Windows
cat ..\shared-workflows\install.ps1 | iex

# Unix
cat ../shared-workflows/install.sh | bash
```

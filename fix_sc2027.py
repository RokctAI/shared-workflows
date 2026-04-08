import re
import os

def fix_content(content):
    # Fix "Bearer "$API_KEY"" -> "Bearer $API_KEY"
    content = re.sub(r'Bearer "\$([^"]+)"', r'Bearer $\1', content)
    # Fix "... "$VAR"..." -> "... $VAR..."
    # This is tricky because we don't want to break actual nested quotes if they are needed
    # But usually in these workflows they are not.
    # Pattern: "something "$VAR" something"
    content = re.sub(r'="\$([^"]+)"', r'=$\1', content) # for echo "var="$VAR""
    content = re.sub(r'detected: "\$([^"]+)"', r'detected: $\1', content)
    content = re.sub(r'found: "\$([^"]+)"', r'found: $\1', content)
    content = re.sub(r'synced "\$([^"]+)"', r'synced $\1', content)
    content = re.sub(r'for "\$([^"]+)"', r'for $\1', content)
    content = re.sub(r'Version "\$([^"]+)"', r'Version $\1', content)
    content = re.sub(r'since "\$([^"]+)"', r'since $\1', content)
    content = re.sub(r'cutoff: "\$([^"]+)"', r'cutoff: $\1', content)
    content = re.sub(r'Delete release for "\$([^"]+)"', r'Delete release for $\1', content)
    content = re.sub(r'Deleting "\$([^"]+)"', r'Deleting $\1', content)
    return content

files = [
    ".github/workflows/universal-flutter-build.yml",
    ".github/workflows/universal-frappe-ci.yml",
    ".github/workflows/universal-linter.yml",
    ".github/workflows/universal-merge.yml",
    ".github/workflows/universal-pipeline.yml",
    ".github/workflows/universal-node-ci.yml",
    ".github/workflows/universal-release.yml",
    ".github/workflows/universal-security.yml"
]

for filepath in files:
    if os.path.exists(filepath):
        with open(filepath, 'r') as f:
            content = f.read()
        new_content = fix_content(content)
        if new_content != content:
            with open(filepath, 'w') as f:
                f.write(new_content)
            print(f"Fixed SC2027 in {filepath}")

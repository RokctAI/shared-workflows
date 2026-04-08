import re

def group_redirects(content, file_path):
    # Pattern to find consecutive echo ... >> "$GITHUB_OUTPUT"
    # and replace them with { echo ...; echo ...; } >> "$GITHUB_OUTPUT"

    # This is a bit complex for a general regex, let's do it for specific known blocks

    # Block 1: universal-release.yml bumped=true
    old1 = """             echo "bumped=true" >> "$GITHUB_OUTPUT"
             echo "old_ver=$OLD_VER" >> "$GITHUB_OUTPUT"
             echo "old_major=$OLD_MAJOR" >> "$GITHUB_OUTPUT" """
    new1 = """             {
               echo "bumped=true"
               echo "old_ver=$OLD_VER"
               echo "old_major=$OLD_MAJOR"
             } >> "$GITHUB_OUTPUT" """
    content = content.replace(old1, new1)

    # Block 2: Configure LTS Environment
    old2 = """          echo "OLD_VER=${{ steps.check_major.outputs.old_ver }}" >> "$GITHUB_ENV"
          echo "MAJOR=${{ steps.check_major.outputs.old_major }}" >> "$GITHUB_ENV"
          echo "BRANCH_NAME=version-${{ steps.check_major.outputs.old_major }}" >> "$GITHUB_ENV"
          echo "TAG_NAME=v${{ steps.check_major.outputs.old_ver }}-LTS" >> "$GITHUB_ENV"
          echo "PREV_MAJOR=$((${{ steps.check_major.outputs.old_major }} - 1))" >> "$GITHUB_ENV" """
    new2 = """          {
            echo "OLD_VER=${{ steps.check_major.outputs.old_ver }}"
            echo "MAJOR=${{ steps.check_major.outputs.old_major }}"
            echo "BRANCH_NAME=version-${{ steps.check_major.outputs.old_major }}"
            echo "TAG_NAME=v${{ steps.check_major.outputs.old_ver }}-LTS"
            echo "PREV_MAJOR=$((${{ steps.check_major.outputs.old_major }} - 1))"
          } >> "$GITHUB_ENV" """
    content = content.replace(old2, new2)

    return content

filepath = '.github/workflows/universal-release.yml'
with open(filepath, 'r') as f:
    content = f.read()

fixed_content = group_redirects(content, filepath)

with open(filepath, 'w') as f:
    f.write(fixed_content)

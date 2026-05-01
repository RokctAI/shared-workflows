# Linting Enhancements Proposal for RokctAI Shared Workflows

This document proposes additional linting tools and quality checks that could be integrated into the universal-linter.yml workflow and expanded to other universal files in the repository.

## Why Enhance Linting?

As a shared workflows repository used across multiple projects, maintaining high code quality is essential. Enhanced linting helps:

1. **Prevent common issues** before they propagate to consumer repositories
2. **Maintain consistency** across the fleet of projects using these workflows
3. **Catch security vulnerabilities** early in the development process
4. **Improve maintainability** by enforcing coding standards
5. **Reduce technical debt** by identifying problems early

## Proposed Linting Tools

### 1. Bandit (Python Security Linter)
**What it does:** Scans Python code for common security issues like hardcoded passwords, SQL injection, and unsafe functions.

**Why needed:** 
- As a workflow repository, we may contain Python scripts that handle credentials or process user input
- Security issues in shared workflows could affect all downstream projects
- Complements existing Ruff/ty checks with security-specific rules

**Integration:** 
Add to existing `lint-python` job:
```yaml
- name: Run Bandit Security Check
  if: steps.check_python.outputs.exists == 'true'
  run: |
    pip install bandit
    bandit -r . -x venv,env,.git,__pycache__,node_modules -lll || true
```

### 2. markdownlint (Markdown Style Checker)
**What it does:** Lints Markdown files for style consistency, syntax issues, and best practices.

**Why needed:**
- Repository contains documentation (README.md, CONTRIBUTING.md, etc.)
- Inconsistent markdown formatting reduces readability
- Helps maintain professional documentation standards

**Integration:** New job:
```yaml
lint-markdown:
  needs: telemetry
  name: 📝 Markdown Lint
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v6
    - name: Install markdownlint
      run: npm install -g markdownlint-cli2
    - name: Run markdownlint
      run: markdownlint-cli2 '**/*.md' --ignore node_modules --ignore .git
```

### 3. Hadolint (Dockerfile Linter)
**What it does:** Lints Dockerfiles for best practices, security issues, and common mistakes.

**Why needed:**
- Repository may contain Dockerfiles for custom actions or testing
- Ensures Docker images built from these files are secure and efficient
- Prevents common Dockerfile anti-patterns

**Integration:** New job:
```yaml
lint-dockerfile:
  needs: telemetry
  name: 🐳 Dockerfile Lint
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v6
    - name: Install Hadolint
      run: |
        wget -O /bin/hadolint https://github.com/hadolint/hadolint/releases/download/v2.12.0/hadolint-Linux-x86_64 && \
        chmod +x /bin/hadolint
    - name: Run Hadolint
      run: hadolint **/Dockerfile* || true
```

### 4. Secret Detection (Detect Secrets)
**What it does:** Scans for accidentally committed secrets like API keys, passwords, and tokens.

**Why needed:**
- Critical for a shared workflows repository that may contain examples or templates
- Prevents credential leaks that could affect all consumer projects
- Complements existing security scanning

**Integration:** New job:
```yaml
detect-secrets:
  needs: telemetry
  name: 🔐 Secret Detection
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v6
    - name: Install detect-secrets
      run: pip install detect-secrets
    - name: Scan for secrets
      run: |
        detect-secrets scan --baseline .secrets.baseline
        # Check for new secrets (exit code 1 means new secrets found)
        ! detect-secrets scan --baseline .secrets.baseline || \
          (echo "::error::New secrets detected! Run 'detect-secrets scan --baseline .secrets.baseline' to update baseline." && exit 1)
```

### 5. Dependency License Checker
**What it does:** Verifies that project dependencies comply with licensing policies.

**Why needed:**
- Ensures we don't accidentally propagate licenses incompatible with our users' projects
- Important for a shared workflows repository that others depend on
- Helps maintain legal compliance across the ecosystem

**Integration:** Add to relevant language-specific jobs:
```yaml
# For Python lint job
- name: Check Python License Compatibility
  if: steps.check_python.outputs.exists == 'true'
  run: |
    pip install pip-licenses
    pip-licenses --from=mixed --format=csv --output-file=licenses.csv
    # Add logic to check for prohibited licenses

# For Node lint job  
- name: Check Node License Compatibility
  if: steps.check_node.outputs.exists == 'true'
  run: |
    npm install -g license-checker
    license-checker --production --out licenses.csv
    # Add logic to check for prohibited licenses
```

### 6. TODO/FIXME Comment Tracker
**What it does:** Tracks and reports on TODO, FIXME, and other annotation comments in the codebase.

**Why needed:**
- Helps track technical debt and unfinished work
- Prevents comments from being forgotten in shared workflows
- Encourages timely resolution of pending items

**Integration:** New job:
```yaml
lint-todos:
  needs: telemetry
  name: 📋 TODO/FIXME Checker
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v6
    - name: Check for TODO/FIXME comments
      run: |
        TODOS=$(grep -r -i "TODO\|FIXME\|XXX\|HACK" --include="*.{py,js,ts,jsx,tsx,java,cs,go,rs,sh,ps1,yml,yaml,json,md}" --exclude-dir={.git,node_modules,__pycache__,env,venv,dist,build} . || true)
        if [ -n "$TODOS" ]; then
          echo "::warning::Found TODO/FIXME comments:"
          echo "$TODOS"
          # Don't fail job, just warn
        else
          echo "✅ No TODO/FIXME comments found."
        fi
```

## Expansion to Other Universal Files

Beyond the linter workflow, these quality principles can be applied to other universal files:

### 1. Issue Templates (.github/ISSUE_TEMPLATE/)
- **Enhancement:** Add template validation using JSON schema
- **Benefit:** Ensures consistency in issue reporting across all projects using these templates
- **Implementation:** JSON schema validation step in PR checks

### 2. Pull Request Templates (.github/PULL_REQUEST_TEMPLATE/)
- **Enhancement:** Add markdownlint validation
- **Benefit:** Maintains professional, consistent PR descriptions
- **Implementation:** Markdown lint job extended to check template files

### 3. Contributing Guidelines (CONTRIBUTING.md)
- **Enhancement:** Add prose linter (vale) and link checker
- **Benefit:** Ensures documentation is clear, correct, and free of broken links
- **Implementation:** 
  ```yaml
  lint-contributing:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - name: Install Vale
        # ... installation steps
      - name: Run Vale
        run: vale CONTRIBUTING.md
      - name: Check Links
        run: |
          # Use markdown-link-check or similar
          npx markdown-link-check CONTRIBUTING.md
  ```

### 4. README Files
- **Enhancement:** Add badges validation and screenshot verification
- **Benefit:** Ensures READMEs accurately represent the project and have working badges
- **Implementation:**
  ```yaml
  validate-readme:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - name: Validate Badges
        run: |
          # Check that badge URLs are accessible
          grep -o 'https://[^)]*' README.md | xargs -I{} curl -f {} || echo "Warning: Some badge URLs may be inaccessible"
      - name: Check Image Dimensions
        run: |
          # Optional: verify screenshot sizes/recommendations
  ```

### 5. Configuration Templates
- **Enhancement:** Add schema validation for common config formats
- **Benefit:** Prevents propagation of invalid configuration templates
- **Implementation:** 
  - JSON schemas for `.github/` configs
  - YAML schemas for workflow templates
  - TOML validation for Cargo/Python projects

## Implementation Recommendations

1. **Phased Rollout:** Start with the most critical additions (secret detection, bandit) then expand
2. **Baseline Establishment:** For tools like detect-secrets, establish an initial baseline
3. **Gradual Strictness:** Begin with warnings, then enforce failures as baseline improves
4. **Documentation Updates:** Update CONTRIBUTING.md to reflect new linting requirements
5. **Performance Considerations:** Cache dependencies where possible to minimize job runtime
6. **Error Handling:** Use `continue-on-error: true` or `|| true` for non-critical checks initially

## Files That Could Benefit

In addition to `.github/workflows/universal-linter.yml`, consider enhancing:
- `.github/actions/` - Custom action source code
- `.github/scripts/` - Helper scripts used by workflows
- `docs/` - Documentation files
- `examples/` - Example configurations and usage
- `templates/` - Template files for new projects

## Conclusion

Implementing these linting enhancements would significantly improve the quality, security, and maintainability of the RokctAI shared workflows repository. By catching issues early and maintaining high standards, we ensure that all projects relying on these workflows benefit from improved reliability and reduced technical debt.

The proposed additions complement existing checks while expanding coverage to critical areas like security, documentation, and legal compliance that weren't previously addressed.
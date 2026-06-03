# API Reference: standardize_fleet

Source file: `scripts/standardize_fleet.py`

## Documented Module Functions

### `def fix_git_identity(content)`
Ensure any workflow job that runs git commit sets --global identity
immediately after its first checkout step. This prevents 'Author identity
unknown' failures in scripts that commit (linters, healers, sync jobs).

### `def fix_release_strategy(workflow_dir)`
Ensure release_strategy is aligned between build.yml and release.yml.
release.yml is the canonical source. If both exist and differ, align build.yml to release.yml.
If only build.yml exists, enforce 'weekly' as the fleet default.

### `def fix_release_push_dedup(workflow_dir)`
When both build.yml and release.yml exist, remove push triggers from release.yml.
build.yml handles pushes (CI on every commit). release.yml handles weekly cron + manual dispatch.
Having push in both causes duplicate CI runs.

### `def fix_android_debug_buildtype(check_only=False)`
Ensure android/app/build.gradle has an explicit debug buildType.
Without it, debug builds in CI fall back to Gradle defaults which can
fail due to missing signing config or inherited release config.

### `def fix_android_gradle_properties(check_only=False)`
Ensure android/gradle.properties has a sensible baseline JVM heap.
Debug builds process large Flutter engine JARs via JetifyTransform and
will OOM on Gradle's default heap. The workflow retry logic will bump
further if needed, but a 4g baseline avoids the first OOM entirely.

### `def standardize_linter_configs(check_only=False)`
Ensure standard linter configuration files exist with modern default overrides.

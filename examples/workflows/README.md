# Example workflows

Templates for consuming this repo's reusable workflows from another repo. Copy
the relevant file into your own repo's `.github/workflows/` and adjust the
`with:` block for your app.

## play-deploy.yml

Minimal caller for [`universal-play-deploy.yml`](../../.github/workflows/universal-play-deploy.yml),
the reusable Play Store release workflow. It handles the main-branch gate,
weekly release limit, no-op detection, AAB build, and publish to the Play
Developer API — your repo just needs to `uses:` it with a few inputs.

**Required secret:** `PLAY_STORE_SERVICE_ACCOUNT_JSON` (Google Play service
account key JSON, raw or base64, with Release Manager access). Configure it
in your repo's (or org's) Actions secrets, then `secrets: inherit` passes it
through automatically.

See the comment header in the file for the full list of optional secrets
(signing keystore, Firebase config, private-repo PAT, GitHub App credentials
for committing the release-state marker) and how to adapt the inputs.

## flutter-analyze.yml

Caller for [`universal-flutter-analyze.yml`](../../.github/workflows/universal-flutter-analyze.yml),
a clean-checkout `flutter analyze` **0-error gate**. On a genuinely fresh
checkout of HEAD it runs the real compose pipeline (initiate + SDK-module
composition, the same one `universal-flutter-build.yml` uses), then
`flutter pub get`, regenerates generated code with `build_runner`, and runs
`flutter analyze`. This catches the class of bug that looks fine in a diff but
breaks on a real composed build — missing `AppRoutes.I` wiring, drift/sqlite3
version mismatches, stale generated code — which a warm local cache hides. It
never commits or pushes, so it's safe on PRs and any branch.

**No required secrets.** Optional `MONOREPO_PAT` (private companion repo) and
`COUNTER_API_KEY` (telemetry) pass through via `secrets: inherit` if present.
See the file's comment header for how to adapt the inputs (`working-directory`,
`run-compose`, `fail-on-warnings`, `flutter-version`).

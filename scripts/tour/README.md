# Guided-tour pipeline

Automated feature-tour screenshots, feature guide, and vertical video for
composed Flutter app shells. Runs via
`.github/workflows/universal-guided-tour.yml`, which composes the app the
same way `universal-flutter-build.yml` does, builds a demo APK
(`--dart-define=IS_DEMO=true --dart-define=TOUR_MODE=true`), walks a scripted
tour on a headless Android emulator, and commits the outputs back to the app
shell repo under `marketing/tour/`:

- `marketing/tour/screenshots/NN-key.png` — one still per tour step (required)
- `marketing/tour/feature-guide.md` — stills + captions (required)
- `marketing/tour/tour.mp4` — 1080x1920 9:16, 30fps, H.264, burned-in
  captions with optional accent-colour keyword highlights, ~3s hook card
  first (when the manifest has a `video.hook`), ~6% zoom per still, ~3s
  logo/offer end card last (when the manifest has a `video.offer` or an
  `app.logo`) (best-effort; a video failure never blocks the screenshots
  or the guide)

## Who owns what

- **SDK template repos** own brand-neutral tour *fragments* next to their
  demo data: `<module>/dart/templates/tour/<sdk>.tour.yaml`
  (e.g. `agent`'s `lms/dart/templates/tour/lms.tour.yaml`, `Users`'
  `auth/dart/templates/tour/auth.tour.yaml`). Fragments never contain app
  branding; `{app_name}` / `{app_tagline}` placeholders are substituted at
  merge time. No assembled outputs ever land in an SDK repo.
- **App shell repos** own a thin manifest `tour/app.tour.yaml` (fragment
  order, app-specific steps, all branded wording), the committed
  integration_test runner, and the committed outputs.
- **This repo** owns the merge/capture/assembly scripts and the reusable
  workflow, shared by every app shell.

## App manifest (`tour/app.tour.yaml`)

```yaml
app:
  name: Supacharge            # substituted into {app_name}
  tagline: Live tutoring...   # substituted into {app_tagline}
  logo: assets/logo.png       # optional; repo-relative, shown on the end card
video:
  hook: "Big test coming? Bring backup."   # optional; ~3s opening card
  seconds_per_step: 3
  brand_color: "#0B2A4A"      # optional; hook/end card background
  accent_color: "#41D68C"     # optional; caption keyword highlight colour
  offer: "Start free today."  # optional; ~3s end card CTA line
setup:                        # optional Dart run once before app.main()
  imports:
    - "import 'package:base_sdk/src/services/local_storage.dart';"
  dart: |
    await LocalStorage.init();
tour:
  - step:                     # inline app-level step
      key: welcome
      title: "Welcome to {app_name}"
      caption: "..."
      action: wait
      settle: 10
  - fragment: auth            # include an SDK fragment (clean SDK name)
  - fragment: lms
```

The hook card, end card and colour keys are all optional: a manifest
without them assembles exactly as before (no cards, plain captions).
Captions (in manifests and fragments alike) may mark ONE key phrase with
asterisks — `caption: "Rewatch *past lessons* whenever you like."` — and
the video renders that phrase in the accent colour; the markers are
stripped everywhere else, so the guide stays plain text.

## SDK fragment (`templates/tour/<sdk>.tour.yaml`)

```yaml
sdk: lms
imports: []                   # optional Dart imports for dart actions
steps:
  - key: schedule             # ^[a-z][a-z0-9_]*$ — unique across the tour
    title: "Today, sorted"    # guide heading
    caption: "..."            # guide text + burned-in video caption
    action: route             # wait | route | dart
    route: /schedule          # for action: route (navigated via replaceNamed)
    settle: 7                 # seconds to let the screen settle
    screenshot: true          # false = perform the action, capture nothing
  - key: login
    action: dart
    screenshot: false
    dart: |
      // runs inside the tour runner with `tester` and `router` in scope
```

## Fragment resolution

`merge_fragments.py` resolves each `fragment:` entry in order:

1. the composed SDK cache (`.rokct/cache/<sdk>/templates/tour/`) — the normal
   path once the fragment is merged in the SDK repo;
2. the SDK's source repo via the GitHub contents API at `--fragments-ref`,
   then `--fallback-ref` (repo + subpath come from the app's composer.json,
   auth via `MONOREPO_PAT`);
3. otherwise the fragment is skipped with a warning — never a failure — so
   apps can adopt fragments gradually.

The merge emits `tour.resolved.json` (for capture/assembly) and regenerates
the app's `integration_test/tour_steps.g.dart`. App repos commit a generated
copy of that file so the repo analyzes without running the merge; CI
overwrites it on every run.

## How a step runs on device

The committed runner (`integration_test/guided_tour_test.dart` in the app
repo) launches the composed app, then per step: performs the action,
settles for `settle` seconds, prints `TOUR_SHOT:<key>` to logcat and holds
the frame; the host-side `capture_screenshots.py` answers each marker with
`adb exec-out screencap -p`. `TOUR_COMPLETE:<n>` ends the run. A partial
tour still commits whatever it captured (with warnings); only zero
screenshots fails the workflow.

## Local testing of the assembly

```sh
python3 scripts/tour/assemble.py \
  --resolved tour.resolved.json --shots tour_screenshots \
  --out /tmp/tour-out --guide --video \
  --ffmpeg /path/to/ffmpeg --codec libvpx --container webm
```

Codec and container are parametrized because trimmed local ffmpeg builds
often lack libx264; CI installs full ffmpeg via apt and uses the defaults
(libx264/mp4/faststart). All zoom + caption work is done in Pillow and piped
to ffmpeg as rawvideo, so no ffmpeg filters are required.

`assemble.py --require-varied` turns the "every captured screenshot is
byte-identical" warning (a sure sign the capture regressed to placeholder
frames) into a hard failure; without the flag assembly stays best-effort.

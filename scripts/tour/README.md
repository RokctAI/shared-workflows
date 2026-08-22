# Guided-tour pipeline

Automated feature-tour screenshots, feature guide, and vertical video for
composed Flutter app shells. Runs via
`.github/workflows/universal-guided-tour.yml`, which composes the app the
same way `universal-flutter-build.yml` does, builds a demo APK
(`--dart-define=IS_DEMO=true --dart-define=TOUR_MODE=true`), walks a scripted
tour on a headless Android emulator, and commits the outputs back to the app
shell repo under `marketing/tour/`:

- `marketing/tour/screenshots/NN-key.png` — one still per tour step (required)
- `marketing/tour/feature-guide.md` — one unified guide, stills + captions
  (required)
- `marketing/tour/tour-<chapter>.mp4` — ONE video per chapter (e.g.
  `tour-auth.mp4`, `tour-lms.mp4`; a chapter = the steps one fragment
  contributed, with app-shell steps folded into the chapter they precede).
  1080x1920 9:16, 30fps, H.264, WhatsApp-store-ad style: the canvas is the
  brand PRIMARY colour, each screenshot sits in a thin BLACK rounded-bezel
  phone frame (drawn in Pillow — bezel, rounded screen clip, soft drop
  shadow) anchored to the bottom canvas edge with its lower part cropped
  off-screen, easing gently toward the edge each beat. Bold caption lines
  are drawn straight on the canvas above the phone, in black or white ink
  (whichever reads better on the canvas) with optional accent-colour
  keyword highlights (underlined ink instead when the accent cannot read
  on the canvas — e.g. when both derive from the same primary).
  `video.chapter_frame_anchor` flips named chapters to hang top-cropped
  from the top edge (caption moves below the phone — right for chapters
  whose key content is bottom sheets) or to the legacy fully-visible
  floating phone. Each video opens on the same ~3s hook card (when the
  manifest has a `video.hook`), holds each screenshot for a fixed ~4s
  caption beat (`video.beat_seconds` overrides), and closes on the same
  ~3s logo/offer end card (when the manifest has a `video.offer` or an
  `app.logo`). Total length is whatever the chapter needs — never crammed
  into a fixed window. A chapter with no captured screenshots gets no
  video (logged, never a failure); the whole video stage stays
  best-effort — a video failure never blocks the screenshots or the guide.
- `marketing/tour/store/NN-key.png` — one Play-Store-ready styled still
  per step (rendered by the same best-effort video stage): the beat
  composition at rest on the 1080x1920 portrait canvas — framed phone with
  its chapter's anchor crop, brand background, caption — with no hook/end
  cards and no drift. Numbering matches `screenshots/`; the directory is
  refreshed wholesale so renamed or removed steps never linger.

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
  beat_seconds: 4             # optional; seconds each still holds (default 4)
  brand_color: "#0B2A4A"      # optional; card/beat background override
  accent_color: "#41D68C"     # optional; keyword highlight colour override
  offer: "Start free today."  # optional; ~3s end card CTA line
  chapter_frame_anchor:       # optional; per-chapter phone-frame anchoring
    auth: top                 # bottom (default) | top | full
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

Every `video` key is optional. When `brand_color` / `accent_color` are
absent, the merge derives them from the composed app sources instead of
falling back straight to house defaults: first the named `Color(0x...)`
arguments of the `AppStyle.injectBrandColors(...)` call in the app's
composed theme shim (`lib/presentation/theme/theme.dart`, override with
`--app-theme`) — per-app palettes win — then base_sdk's own `AppStyle`
field defaults in the composed cache
(`.rokct/cache/base/lib/src/presentation/theme/app_style.dart`). Both
`accent_color` and `brand_color` derive from AppStyle `primary` — the
video canvas IS the brand's primary colour, WhatsApp-ad style; when
neither file parses, assemble.py keeps its built-in defaults. Text ink is
picked per background (black or white, whichever reads better), so any
primary colour works. `video.seconds_per_step` (the retired
fixed-total-window pacing) is ignored; each still now holds a fixed
`beat_seconds` beat.
Captions (in manifests and fragments alike) may mark ONE key phrase with
asterisks — `caption: "Rewatch *past lessons* whenever you like."` — and
the video renders that phrase in the accent colour when it reads against
the canvas (an accent that matches the canvas — the derived default —
falls back to underlined ink); the markers are stripped everywhere else,
so the guide stays plain text.

`video.chapter_frame_anchor` maps chapter names (fragment names, plus
`app` for pre-chapter plans) to how that chapter's phone frame meets the
canvas edge: `bottom` (default — phone anchored to the bottom edge, lower
part cropped off-screen, caption above), `top` (phone hangs top-cropped
from the top edge, caption below — use when the chapter's key content is
bottom sheets, e.g. auth), or `full` (legacy fully-visible floating
phone). Unknown values warn and fall back to `bottom`; the key is
entirely optional.

Each `fragment:` entry opens a video *chapter* named after the fragment;
inline `step:` entries belong to the chapter they precede (trailing steps
join the chapter before them; a tour with no fragments is a single `app`
chapter). Every chapter renders to its own `tour-<chapter>.mp4` sharing
the manifest's hook card and end card, so an app with `auth`, `lms` and
`lms_admin` fragments publishes three short videos instead of one long
one. The feature guide stays unified.

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

1. the composed SDK cache — first `.rokct/cache/<fragment>/templates/tour/`
   (the SDK named after the fragment), then a scan of every composed SDK's
   cache dir for `<fragment>.tour.yaml`, because one SDK may ship several
   fragments (e.g. `lms`'s `templates/tour/` holding `lms.tour.yaml` and
   `lms_partner.tour.yaml`); a fragment name shipped by more than one SDK
   is an error;
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
(libx264/mp4/faststart). All frame work (phone frame, cards, captions) is
done in Pillow and fed to ffmpeg as a concatenated-JPEG stream, so no
ffmpeg filters are required.

`assemble.py --require-varied` turns the "every captured screenshot is
byte-identical" warning (a sure sign the capture regressed to placeholder
frames) into a hard failure; without the flag assembly stays best-effort.

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
  (whichever reads better on the canvas); an optional keyword sits inside
  a filled rounded highlight chip — accent-filled when the accent stands
  apart from the canvas, filled with the black/white contrast ink when it
  cannot (e.g. when both derive from the same primary) — with the keyword
  ink picked black or white against the chip fill.
  `video.chapter_frame_anchor` flips named chapters to hang top-cropped
  from the top edge (caption moves below the phone — right for chapters
  whose key content is bottom sheets) or to the legacy fully-visible
  floating phone. Each video opens on the same ~3s opening card — the
  app's real splash image when one resolves (`app.splash`, or
  auto-detected from the checkout; portrait art renders full-bleed,
  a square/landscape mark sits centred on the brand canvas), else the
  legacy hook card (when the manifest has a `video.hook`) — holds each
  screenshot for a fixed ~4s caption beat (`video.beat_seconds`
  overrides), and closes on the same ~3s logo/offer end card (when the
  manifest has a `video.offer` or an `app.logo`). Total length is whatever the chapter needs — never crammed
  into a fixed window. A chapter with no captured screenshots gets no
  video (logged, never a failure); the whole video stage stays
  best-effort — a video failure never blocks the screenshots or the guide.
- `marketing/tour/store/NN-key.png` — one Play-Store-ready styled still
  per step (rendered by the same best-effort video stage): the beat
  composition at rest on the 1080x1920 portrait canvas — framed phone with
  its chapter's anchor crop, brand background, caption — with no hook/end
  cards and no drift. Numbering matches `screenshots/`; the directory is
  refreshed wholesale so renamed or removed steps never linger.
- `marketing/tour/store/feature-graphic.png` — the Play listing's
  LANDSCAPE feature graphic, exactly 1024x500 (rendered supersampled at
  2x so the type stays crisp): brand-primary canvas; the app logo, app
  name and tagline stacked on the left; the hero screenshot in the house
  phone frame on the right, its bottom edge cropped by the canvas. The
  hero still is the step named by `store.feature_step` when the manifest
  sets one (the convention is the app's HOME step); otherwise the first
  captured step of the SECOND chapter (the first chapter is usually
  onboarding/sign-in), falling back to the tour's first captured step.
  `store.logo` overrides the graphic's logo mark independently of
  `app.logo` — an explicitly empty value draws no logo at all (name and
  tagline only). Composed to Play feature-graphic conventions:
  minimal text, nothing critical near the edges or the exact centre
  (Play crops the graphic in some placements and overlays a play button
  on it when it fronts the promo video).
- `marketing/tour/tour-wide.mp4` — ONE widescreen 16:9 highlight reel
  across ALL chapters (1920x1080, same fps/codec/pacing as the chapter
  videos), for the Play listing's landscape promo-video slot. Landscape
  composition: the caption (same type treatment, same highlight chip)
  fills the left half of the brand canvas; the portrait framed phone
  sits in the right half, gently edge-cropped per its chapter's anchor
  (`full` keeps it fully visible). It opens on a landscape splash card —
  portrait splash art renders CONTAINED at full canvas height with the
  side pillars filled with the art's own border-average colour (16:9
  centre-cropping full-screen portrait art would slice through its
  typography); full-bleed landscape art cover-crops; a small mark sits
  centred on the brand canvas — and closes on the landscape logo/offer
  end card. Beat selection keeps the reel short: chapters keep tour
  order; each contributes its first TWO captured steps that carry a
  `*highlight*` phrase (the manifest author's own emphasis is the best
  available signal for a chapter's strongest beats), or its first
  captured step when none do — so every chapter appears — capped at 8
  beats overall, trimming later chapters' second picks first. The name
  `tour-wide.mp4` is reserved: a fragment named `wide` would collide
  with it (the assembler warns and the reel wins).

Just before committing those outputs, the workflow also runs
`readme_sections.py`, which refreshes two marker-delimited blocks in the
app shell's `README.md` so the README rides the same output commit (see
that script's docstring for the full contract): a `## About` block
mirroring the Play listing's `full_description.txt` (empty while the
listing file holds only comments), and a `## App tour` gallery of the
styled `marketing/tour/store/` stills — everything not excluded by the
optional curation manifest `marketing/tour/readme_gallery.yml`
(`exclude:` list, `captions:` overrides) is shown, so new tour steps
appear in the README automatically. Nothing outside the marker blocks is
ever touched, and the generated Markdown stays inside default
markdownlint rules (80-column lines, no inline HTML). Note the chosen
trade-off: editing the store listing alone refreshes the README on the
next tour run (or a manual `workflow_dispatch`), not immediately.

## The tablet leg

After the phone leg, the workflow reruns the SAME tour serially on a
second emulator (input `tablet`, ON by default — no caller change
needed; pass `tablet: false` to opt out) using the SDK's `pixel_tablet`
device profile on the same api-34 google_apis x86_64 system image, with
the canvas forced to a tablet-class portrait geometry: `wm size
1600x2560`, `wm density 240` — 1600 / (240/160) = **1066dp** wide, what
a 12.4-inch 2560x1600 panel (Galaxy Tab S7 FE class, ~243ppi) really
reports, and both sides sit inside Play's 320-3840px screenshot bounds.

The density is what makes the leg a tablet. `PlaneHost.planeCountFor`
(RokctAI/core) gives three planes only from 840dp up, two from 600dp;
the earlier `wm density 320` made this same 1600px panel 800dp wide, so
every "tablet" still was the two-plane FOLDABLE layout and the gallery
was mislabelled. Real 10-inch tablets land under 840dp too — the
`pixel_tablet` profile's own 2560x1600 @ 320 is exactly 800dp in
portrait — so the number is chosen, not inherited. The PIXEL size is
unchanged: `assemble.py`'s `tablet` preset composites onto 1600x2560.

`run_tour.sh` is shared by both legs — the tablet leg only
overrides its `TOUR_OUT` / `TOUR_WM_SIZE` / `TOUR_WM_DENSITY` /
`TOUR_LOGCAT` / `TOUR_TEST_LOG` env defaults — and gets the same
fresh-AVD retry and zero-screenshots check as the phone leg.

Tablet outputs land in their own tree, `marketing/tour/tablet/`,
assembled by `assemble.py --device tablet` (geometry preset: 1600x2560
canvas, scaled phone-frame boxes):

- `marketing/tour/tablet/screenshots/NN-key.png` + `feature-guide.md` —
  the raw tablet stills and guide (same format as the phone leg's)
- `marketing/tour/tablet/tour-<chapter>.mp4` — per-chapter videos on the
  tablet canvas (best-effort, like the phone videos)
- `marketing/tour/tablet/store/NN-key.png` — styled tablet stills. The
  directory is separate from `marketing/tour/store/` ON PURPOSE: the
  Play deploy classifies it by LOCATION into `tenInchScreenshots`
  (ordered by the same `marketing/store/screenshots.txt` pick-list the
  phone listing uses, else first 8 in filename order; overflow logged)
  — a 1600x2560 still is
  dimensionally indistinguishable from a large phone screenshot, so
  directory is the only reliable signal. The tablet run never writes a
  feature graphic, icon, or `tour-wide` reel — those Play assets exist
  once per listing and stay with the phone run. The stills map to the
  10-inch slot only, not `sevenInchScreenshots`: the phone set at
  1080x1920 already shows the handset-class content, and 10-inch
  layouts in the 7-inch slot would misrepresent a 7-inch device.

Each `--device` run wipes only its OWN `screenshots/` and `store/` dirs
wholesale — the tablet refresh never touches the phone dirs, and vice
versa. A tablet-leg failure fails the job (honest red), but only AFTER
the phone outputs commit: every tablet step is outcome-gated so phone
assets are never lost to a tablet flake. Turning `tablet` off later does
not delete previously committed `marketing/tour/tablet/` outputs —
remove the directory by hand to retire the tablet listing assets.

## What "success" means

A tour run is a success only when it captured what its resolved manifest
asked for. `run_tour.sh` deliberately keeps going on a PARTIAL capture —
exiting 0 whenever at least one still landed — so the screenshots it did
get are still assembled and committed; that tolerance is about not losing
assets, not about the verdict. Each leg therefore writes what it actually
produced to `<out-dir>.status` (`tour_screenshots.status`,
`tour_screenshots_tablet.status`: expected count, captured count,
`flutter test` exit code), the `Tour Status` step records the verdict, and
a `Tour Completeness Gate` AFTER the commit step turns the job red when
the leg captured materially fewer stills than expected (more than one
short) or `flutter test` exited non-zero — the same
commit-then-fail-honestly shape the tablet gate already uses. One missing
still stays a warning.

Before that gate, a crash partway through the tour reported green: run
33448833555 captured 4 of 19 stills, logged `flutter test exited 1 but 4
screenshots were captured - continuing`, and still reported ✅.

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
  splash: assets/splash.png   # optional; repo-relative, the ~3s opening card
                              # (auto-detected when absent — see below)
video:
  hook: "Big test coming? Bring backup."   # optional; hook-card fallback
  beat_seconds: 4             # optional; seconds each still holds (default 4)
  brand_color: "#0B2A4A"      # optional; card/beat background override
  accent_color: "#41D68C"     # optional; keyword highlight colour override
  offer: "Start free today."  # optional; ~3s end card CTA line
  chapter_frame_anchor:       # optional; per-chapter phone-frame anchoring
    auth: top                 # bottom (default) | top | full
store:                        # optional; Play feature-graphic overrides
  feature_step: schedule      # step key whose screenshot is the hero
                              # (convention: the app's HOME step)
  logo: ""                    # feature-graphic logo override; ""/~ = none
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

Every `store` key is optional too. `store.feature_step` names the step
key whose captured screenshot fronts the feature graphic; the convention
is to point it at the app's HOME step — the safest single screen to sell
the app with — set explicitly per app because auto-detecting "home" is
unreliable (e.g. supacharge's home step is `schedule`). An unknown or
uncaptured key warns (at merge time and again at assembly) and falls back
to the default second-chapter-first-step hero; with the key absent
nothing changes. `store.logo` controls the feature graphic's logo mark
independently of `app.logo` (which the video end card and app icon keep
using): absent = use `app.logo`; a repo-relative path = use that path;
explicitly empty (`""` or `~`) = draw no logo — right for apps whose only
logo is a wordmark that would double the app name (the graphic re-centres
the name + tagline block, as it already does when no logo resolves).

Each chapter video OPENS on the app's real splash image (~3s) when one
resolves. An explicit `app.splash` (repo-relative) wins; when absent the
merge auto-detects it from the checkout — the flutter_native_splash
config (`flutter_native_splash.yaml`, override with `--splash-config`):
its `background_image`, then its `image`; then the conventional
committed asset `assets/images/splash.png` — taking the first path that
actually exists. Portrait splash art fills the whole 1080x1920 frame
(cover-scaled, centre-cropped, faithful to how the native splash
stretches to the device screen); a square or landscape splash mark sits
centred on the brand canvas instead. When no splash resolves, the video
falls back to the legacy hook card (`video.hook`), and with neither it
simply starts on the first beat — manifests without a splash render
exactly as before.
Captions (in manifests and fragments alike) may mark ONE key phrase with
asterisks — `caption: "Rewatch *past lessons* whenever you like."` — and
the video (and the store stills) draw that phrase inside a filled rounded
highlight chip: the chip fills with the accent colour when the accent
stands apart from the canvas, and with the black/white contrast ink when
it cannot (the derived default, where accent and canvas share the
primary); the keyword's own ink is black or white against the chip fill,
so the chip always provides its own contrast. The phrase never splits
across a line wrap — when it does not fit the current line it drops whole
to the next row. The markers are stripped everywhere else, so the guide
stays plain text.

### How long a caption may be

The caption block is drawn into a fixed box and the phone card is pasted
over it afterwards, so a caption the box cannot hold is not reflowed — it
is clipped. The assembler measures the fit and FAILS the run rather than
publishing a clipped still, naming the step and the overrun. Two budgets,
both on the phone leg (1080x1920, DejaVu Sans Bold 64px, 84px rows) —
the tablet leg's larger canvas is never the binding one:

- **at most 7 wrapped rows.** In practice ~170 characters, but rows are
  what is measured, since word lengths decide where the wraps land.
- **each row at most 936px wide.** Ordinary words wrap on their own; the
  one thing that cannot is the `*highlight*` phrase, which never splits.
  Keep it to a genuine key phrase (roughly 22 characters or fewer) rather
  than a whole clause — a phrase too wide for one row runs off the canvas
  and loses its last letters.

The wide reel's caption column is narrower still (800px, half a landscape
canvas). An overrun there crowds the phone rather than losing characters,
so it warns instead of failing.

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

`assemble.py` fails the run when ANY two captured screenshots are
byte-identical, naming both step keys. Two steps showing the same pixels
means one of them never reached its own screen, and the guide, video and
store listing would otherwise publish the same still twice under two
different captions; an all-identical run (the capture regressed to
placeholder frames) is reported as the extreme case of the same fault.
`--require-varied` used to opt into failing on the all-identical case only;
it is now an accepted no-op, kept so existing callers keep working.

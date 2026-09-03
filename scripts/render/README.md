# Real-render review strips

Review frames that come out of the app's own code, not out of somebody's
hand-written HTML.

A thread that wants a design reviewed runs the app's real screen through a
headless Flutter widget test, captures a PNG plus the measured rectangle of
every element worth pointing at, and composes those into one scrollable page
with numbered callouts. The reviewer is then looking at what the code
actually draws.

The harness renders the SDKs' own demo/seed fixtures and should not be wired
to a live client or backend.

**The rule this kit exists to enforce: a review frame is a render of real
code with demo data. It is never a drawing of what the code is believed to
do.** A hand-drawn frame agrees with whatever its author believed while
drawing it. A render disagrees when the belief is wrong - which is the entire
value. Real findings that only surfaced because the pixels were real, on the
first screen this was done to: an untranslated string key in the usage line,
an email ellipsising at 390px, a footer showing its genuine offline state,
and a 94px spacer everyone had been reading as padding.

Two halves, used together:

| Half | Lives in | What it does |
|---|---|---|
| Render harness | [`templates/render-harness/`](../../templates/render-harness/) | A Dart widget test you copy into a throwaway package. Pumps a real screen at phone size with real fonts, writes `out/<name>.png` and `out/<name>.json`. |
| Strip composer | [`compose_strip.py`](compose_strip.py) | Reads those PNGs + rect JSONs plus a small config, writes ONE self-contained HTML page. |
| CI workflow | [`universal-render-strip.yml`](../../.github/workflows/universal-render-strip.yml) | Optional. Runs both halves on a runner and uploads the page as an artifact - see [§8](#8-running-it-in-ci). |

The halves are decoupled on purpose: the composer only needs the sidecar
format, so a non-Flutter surface that can emit the same JSON composes into
the same page.

---

## 1. Output format (fixed, not per-thread)

The page format is a house convention. Threads pick the content; they do not
pick the shape.

- **One vertical scroll.** Frames stack down the page and sit side by side
  only where the viewport is wide. **No pan/zoom canvas** - a canvas the
  reviewer has to drag around has been explicitly rejected, because they can
  never tell whether they have seen everything.
- **CSS phone bezels.** The PNG is the screen; the bezel is drawn in CSS.
- **Orange (`#FF6600`) number chips**, positioned from the measured rect.
  Never placed by hand, so they cannot drift out of sync with the render.
- **A legend per frame**, keyed by the same numbers.
- **A status pill per frame** from a fixed four-word vocabulary (below).
- **Notes** for what is real, what is stubbed, and what the render exposed.
- **A chips on/off toggle.** Chips on is review mode. Chips off is
  presentation mode - the same page, client- and investor-facing, no second
  export to keep in sync.
- **Light/dark aware page chrome**, and self-contained: images are inlined as
  data URIs, so the file opens from disk with no network.

---

## 2. Setup

### 2.1 Flutter

`flutter test` runs headless in a container - no emulator, no display.

```bash
git clone https://github.com/flutter/flutter.git --depth 1 -b stable flutter-sdk
export PATH="$PWD/flutter-sdk/bin:$PATH"
flutter --version
```

> **Gotcha - the version in a pubspec is the DART SDK version.** A pubspec
> line like `sdk: ">=3.5.0 <4.0.0"` is Dart, not Flutter; picking a Flutter
> release by that number gives you one several years stale and a wall of
> resolver errors. Read the `flutter:` constraint (e.g. `>=3.38.5`) and
> install a stable release that satisfies it.

### 2.2 A throwaway package with path deps

The harness is **not** committed to an app or SDK repo. Clone the SDK repos
read-only, then create the scratch package beside them from
[`templates/render-harness/pubspec.yaml`](../../templates/render-harness/pubspec.yaml):

```text
<scratch>/
  core/            # clone of RokctAI/core     (read-only)
  agent/           # clone of RokctAI/agent    (read-only)
  flutter-sdk/
  render-harness/  # the throwaway package
```

Mirror the app shell's `dependency_overrides` exactly. The harness is
compiling the same SDK the app composes; if the overrides differ, the render
is of something nobody ships.

### 2.3 Gotcha - `tr_keys` injection

A feature SDK that normally compiles inside a composed app may not compile
standalone until the host's translation keys exist. The host repo ships its
own tool for this:

```bash
dart run tool/inject_tr_keys.dart          # in the app/host repo
```

It performs a **marker-region write into the base_sdk clone** - i.e. it
mutates the read-only clone. Revert it when the run is done:

```bash
git -C core checkout -- .
```

Symptom when it has not been run: the analyzer/compiler reports undefined
getters on the translation keys class, from SDK code you did not touch.

### 2.4 Gotcha - google_fonts in tests

`google_fonts` fetches faces at runtime. In a test there is no network, the
fetch fails silently, and every glyph falls back to the Ahem/FlutterTest
block font - a PNG that looks plausible in a thumbnail and is worthless.

Two things are needed:

1. **Turn fetching off**, so a failure is loud rather than silent:

   ```dart
   GoogleFonts.config.allowRuntimeFetching = false;
   ```

2. **Register the real faces from files.** `google_fonts` resolves a family
   name PLUS its variant (`Inter_600`, `Inter_regular`), so register the
   per-weight variant families *and* the plain family, because
   `fontFamilyFallback` lands on the plain name. The asset copies live under
   `assets/google_fonts/` and must be named the way the package's test path
   expects; the harness template's `loadRealFonts()` shows the shape.

Also register, or lose them:

- **MaterialIcons** - inside the Flutter SDK cache
  (`bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf`).
- **Package icon fonts** (Remix, Cupertino, ...) - in the pub cache, under
  their package-scoped family name (`packages/remixicon/Remix`).
- **The default family** (usually Roboto) - anything with a bare `TextStyle`
  and no family falls back to it.

### 2.5 Demo data comes from the SDKs, not from the harness

**Do not hand-write fixtures.** Every SDK already owns its demo data and
already swaps it in itself. `AppConstants.isDemo`
(`core/base/dart/lib/src/constants/app_constants.dart`) is
`bool.fromEnvironment('IS_DEMO')`, and each SDK's DI registration branches on
it:

| SDK | Registration | What demo mode gives you |
|---|---|---|
| lms | `LmsSdkDependencies.register` (`agent/lms/dart/lib/src/common/di/lms_di.dart`) | `DemoLmsRepository` - courses, enrolments, grade, tutors, board, practice, server clock - and `SeededTutorCatalog` |
| auth | `AuthSdkDependencies.register` (`Users/auth/dart/lib/src/common/di/auth_di.dart`) | `MockAuthRepository`, including the demo logins (`partner@`/`admin@`/`driver@`/`manager@demo.rokct.ai`) and its demo `ProfileData` |
| users | `UsersSdkDependencies.register` (`Users/users/dart/lib/src/common/di/users_di.dart`) | `MockAddressRepository` |

So the whole data setup for a screen is: run the test with
`--dart-define=IS_DEMO=true` and call the DI registrations in composed-app
order (base first, then each feature SDK). Per-screen config then really is
just *which screen* - see `TODO(harness) 2/8` in the template.

Registrations are guarded by `isRegistered`, so anything pre-registered wins;
that is also how the exception hook below gets in.

#### The one gap: locally accumulated history

Demo mode covers repositories. It does **not** pre-fill stores the device
accumulates through use - an attendance ledger, a downloads list, a watch
history. Those are written by the app as the user does things
(`ProfileStore.recordAttendance` is called from `schedule_notifier.dart` as
lessons are attended), and `DemoLmsRepository.recordAttendanceEvent` is a
deliberate no-op. The guided tour fills them by BOOTING the app and walking
the schedule; a widget test never walks that journey, so on a fresh temp
database those screens render empty.

For a screen that reads such history - the lms student profile is the
canonical case - seed it in `TODO(harness) 3/8`, through the app's REAL store
API so the derived values (attendance %, averages, streaks) are still computed
by the app, and say so in the page's notes. **This is the documented
exception, not the default path.**

`TODO(harness) 4/8` is the second, rarer exception: a hand-written stub, for a
service with no `isDemo` implementation at all. Let stubs throw from
`noSuchMethod` so they name the exact member the screen touches and cannot
quietly grow.

### 2.6 Why the screen is named, and not derived from the tour fragments

Reasonable question, since the SDKs' guided-tour fragments
(`<sdk>/dart/templates/tour/<sdk>.tour.yaml`) already list the app's screen
surface. It was investigated and does not work, for three separate reasons.

**A tour step never names a widget.** The step schema
(`scripts/tour/merge_fragments.py`, `VALID_ACTIONS = ("wait", "route",
"dart")`) allows a route PATH, a raw Dart block, or nothing. A path is
validated only as "starts with `/`" and is navigated on a BOOTED app via
`context.router.replaceNamed`; a `dart` step drives `tester` and `router`
against that running app. Neither is constructible in a widget test. Across
the fleet's fragments the split is roughly half route steps, half Dart
interaction steps.

**The path-to-widget hop needs composed host glue.** A path joins to the
SDK's `manifest.json` `routes` entry (`/schedule` ->
`"page": "ScheduleRoute.page"`), but the route class is not the widget and the
widget is not name-derivable: `StudentProfileRoute` is
`StudentProfileRouteView`, which renders base_sdk's `GenericProfilePage`
inside a `Stack` with the app's floating nav. That view lives in
`templates/routes/lms_route_pages.dart` - host glue full of `${package}`
placeholders, installed into the shell at compose time - and the route classes
themselves are auto_route output that exists only after `build_runner` runs on
a composed shell. An app shell repo has no `lib/` to read at all.

**Route steps are not independent of each other.** In `lms.tour.yaml` the
`/schedule` step deliberately lands on the new-school-year gate, and the NEXT
step taps its confirm button so every later screen renders the rolled-over
grade. `/schedule` therefore names two different screens depending on whether
a prior step ran. `auth.tour.yaml` documents the same trap from the other
side: routing straight to `/register` renders the sheet "as bare pages - not
the UX a user ever sees", which is exactly what construct-from-route would
produce. Fragments also skip screens whose routes take parameters, so they are
not a complete inventory either.

What IS reusable is the ORDER. `merge_fragments.py` tags every step with the
chapter it came from, and the shell manifest fixes the fragment order. That
maps cleanly onto this kit's `section` field - but it is four lines of config,
not worth coupling the renderer to the tour pipeline. Name the screen.

---

## 3. Running it

```bash
# 1. render (in the harness package). IS_DEMO=true is what makes the SDKs
#    register their own demo fixtures instead of their real HTTP repositories.
flutter test --dart-define=IS_DEMO=true test/render_screen_test.dart
RENDER_SUFFIX=_draft flutter test --dart-define=IS_DEMO=true \
    test/render_screen_test.dart                                # PR heads

# 2. compose
python scripts/render/compose_strip.py \
    --config my-screen.strip.json \
    --base-dir <scratch>/render-harness/out \
    --out strip.html \
    --emit-numbering numbering.json
```

Marginal cost after the one-time setup is small: name the screen, register
the SDKs, list the elements to number. Seconds of runtime per variant.

### Strip config

```jsonc
{
  "title": "Profile host - lms student",
  "kicker": "profile-host migration - real render",
  "lede": "One paragraph on what the reader is looking at.",
  "fonts": "system",          // "google" opts into the webfont link
  "chips_default": true,      // false ships the page in presentation mode

  "frames": [
    {
      "section": "Shipped - what main renders today",  // groups frames
      "caption": "lms student - light",
      "status": "SHIPPED",
      "png": "profile_light.png",
      "rects": "profile_light.json",
      "note": "core main aba527c",
      "legend": { "base.identity_header": "per-frame legend override" }
    }
  ],

  "labels":    { "<element key or raw label>": "legend text for the reviewer" },
  "numbering": { "map": { "<element key>": 1 }, "retired": { "23": "what it was" } },
  "notes":     [ { "kicker": "how this was produced", "body": ["..."],
                   "items": ["..."] } ]
}
```

Frame paths resolve against `base_dir` in the config, else `--base-dir`, else
the config's own directory.

---

## 4. Numbering conventions

Numbers are how a review conversation refers to things ("14 is too tight").
They only work if they behave like identifiers.

1. **Globally unique across the page.** Not per frame. Number 14 means one
   element, whichever frame it appears in - which is exactly what makes a
   before/after pair readable: the same element carries the same number in
   both.
2. **Stable across revisions.** Every element carries a `key` (the harness
   writes it; the composer binds a number to it in `numbering.map`). Commit
   that map. A re-render with a new element appends the next free number
   instead of shuffling the ones already discussed. Run with
   `--emit-numbering` and commit the result; the composer warns when it had
   to invent numbers with nowhere to write them back.
3. **Retired numbers are kept as tombstones.** When an element is removed,
   move its number into `numbering.retired` with a line saying what it was.
   It is never re-issued, and it renders in a "Retired numbers" block at the
   foot of the page. Old review comments therefore keep their meaning, and
   nobody has to ask what happened to 26.
4. **`key` is an identity, `label` is prose.** Reword labels whenever the
   wording helps. Changing a key rebinds the number and breaks rule 2.

---

## 5. Status pill vocabulary

Four tags, deliberately few enough to hold in your head:

| Tag | Means |
|---|---|
| `SHIPPED` | This is what `main` renders today. |
| `PROPOSED` | This is what the change under review renders. |
| `BEFORE` | Prior state, kept beside a `PROPOSED` frame for contrast. |
| `HELD` | Drawn and deliberately not being built - parked, needs a decision. |

The composer refuses any other value. If a frame does not fit one of the
four, the frame's status is the thing that is unclear, not the vocabulary.

---

## 6. Worked example

[`examples/lms-profile.strip.json`](examples/lms-profile.strip.json) is a
real, runnable config: four frames (shipped light/dark, proposed light/dark)
of the lms student profile, with the legend aliases, the committed numbering
map, eight tombstones carried over from the page's hand-drawn predecessor,
and the notes that declare what was stubbed.

Point it at a directory of harness outputs and it composes:

```bash
python scripts/render/compose_strip.py \
    --config scripts/render/examples/lms-profile.strip.json \
    --base-dir <scratch>/render-harness/out \
    --out lms-profile.html
```

Expected output for that config: 4 frames, 19 numbered elements, 2 sections,
8 tombstones, one page, no external references.

---

## 7. Tests

```bash
python scripts/tests/test_render_strip_compose.py
python -m unittest discover -s scripts/tests
```

The tests synthesise their own tiny PNG and rect JSON, so they run with no
Flutter, no clones and no fixtures.

---

## 8. Running it in CI

[`universal-render-strip.yml`](../../.github/workflows/universal-render-strip.yml)
is a `workflow_call` workflow that does the whole pipeline on a runner:
composes the caller's SDK modules the way `universal-flutter-build` does, runs
the render test, composes the strip, and uploads the page as a build artifact.
`flutter test` is headless, so there is no emulator and no display - this is a
cheap job by fleet standards.

The job only ever READS the repository and uploads an artifact - it never
commits or pushes. It declares `permissions: write-all` purely to match the
other `universal-*` workflows: a caller whose own block is narrower than the
reusable workflow's makes GitHub refuse the run at startup with zero jobs, so
the fleet keeps one permissions shape everywhere.

**Private SDK access** uses the same mechanism as every other Flutter workflow
here: the org-wide **`MONOREPO_PAT`** secret, declared optional under
`secrets:` and exposed as job env so the composer and the `.private_repo`
clone step pick it up (`TOKEN="${{ secrets.MONOREPO_PAT || github.token }}"`).
Callers pass it with `secrets: inherit`. **No per-repo Actions secret is
created for this.**

The caller snippet a shell repo drops into its own `.github/workflows/`:

```yaml
name: Render Strip

# Manual only, deliberately. Rendering on every commit is not wanted:
# a shell adopts this by CHOOSING to run it.
on:
  workflow_dispatch:
    inputs:
      render-suffix:
        description: "Suffix for this run's outputs (e.g. _draft)"
        required: false
        default: ''

# Must grant at least what the reusable workflow declares
# (universal-render-strip.yml sets `permissions: write-all`). A narrower
# block here makes GitHub refuse the run at startup with zero jobs.
permissions: write-all

jobs:
  render:
    uses: RokctAI/shared-workflows/.github/workflows/universal-render-strip.yml@main
    secrets: inherit
    with:
      render-suffix: ${{ inputs.render-suffix }}
      # Defaults: test/render/render_screen_test.dart + test/render/strip.json.
      # The job skips cleanly when the render test is absent, so this file is
      # safe to land before the test exists.
```

Then download the `render-strip` artifact and open the HTML - it is
self-contained, so it needs no network.

> ⚠️ On a public repository that artifact is downloadable by anyone. The
> demo-data rule at the top of this file is what keeps that safe.

---

## 9. Keeping the render in sync with the screen

A project standing rule, extended to cover this tool: a PR that changes a
demo-visible surface updates the owning SDK's tour fragment and demo seeds in
the same PR. The render is now on that list. If a PR changes a screen the
render covers, it updates that screen's render config - and its example, where
one is committed - in the same PR, exactly as it updates the tour fragment and
the seeds. A render that lags the code stops being evidence and becomes another
drawing, which is the one thing this tool exists to avoid.

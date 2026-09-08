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
| CI runner | [`run_strip.sh`](run_strip.sh) | Runs both halves against an already-composed tree. One implementation, called by both workflows below. |
| Placement export | `compose_strip.py --emit-svg` | One SVG per frame, annotated and clean, for dropping a screen into a user guide or a deck - see [§10](#10-svg-per-frame-for-a-guide-or-a-deck). |
| CI workflow | [`universal-render-strip.yml`](../../.github/workflows/universal-render-strip.yml) | Optional manual button. Composes the SDKs on a runner, renders, uploads the page as an artifact - see [§8](#8-running-it-in-ci). |
| CI gate | [`universal-guided-tour.yml`](../../.github/workflows/universal-guided-tour.yml) | Automatic. Renders the strip BEFORE the tour's emulator legs and fails the run if it does not render - see [§8.1](#81-the-guided-tour-runs-it-automatically-first). |

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

#### Block glyphs that are not a missing weight

Every weight loads, the frame is otherwise correct, and one or two labels are
still solid rectangles - a floating Back pill, an avatar's initials. The reflex
is to curl another face in; for these it is wasted effort. Diagnose first:

- **Width probe.** In the test, lay the text out with `TextPainter` (or read
  the `RenderParagraph` size) and compare against a real face. An Ahem block
  advances exactly one em, so `Back` at 20px measures 80.0pt in the block
  font and 43.9pt in Roboto. A one-em-per-glyph width means the *family* was
  never registered, not the weight.
- **Ask which family the text resolves to.** Walk `DefaultTextStyle.of` at
  the widget, or read the SVG source.

Three facts that produce the block:

- A widget floating in the route `Stack` with **no `Material` ancestor**
  inherits WidgetsApp's fallback `DefaultTextStyle`, whose family is
  `monospace`. Inside a `Material` the theme's `Typography` supplies Roboto,
  which is why a SnackBar in the same frame is always fine.
- An inline SVG `<text font-family="Helvetica, Arial, sans-serif">` goes
  through vector_graphics_compiler, which passes the attribute through
  **whole** - the CSS stack becomes one family name, not a fallback list.
- Registering faces under `Ahem` or `FlutterTest` does **not** displace the
  engine's block default.

The fix is an alias, not a download: in `loadRealFonts()` register
`monospace`, `Helvetica`, `Arial`, `sans-serif` and the literal
`Helvetica, Arial, sans-serif` onto Roboto, which already ships in the
Flutter SDK cache (`bin/cache/artifacts/material_fonts/Roboto-*.ttf`), so no
new binary is committed. The template carries the loop. Rule: a floating
widget outside `Material`, or an SVG `<text>`, needs a family alias in the
harness. Metrics differ (Roboto is proportional where a device's `monospace`
is not) but the word is readable, which is what the review needs.

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

### 2.6 Wrapping fidelity - where a render lies

Everything else in this kit fails loudly. A screen that does not compile
stops the run, an element that does not match throws with a reason, a
harness that writes no PNG fails the tour's gate. **An incomplete wrapper
fails silently.** It produces a clean, plausible, entirely convincing PNG of
a screen no user will ever see, and nothing downstream can tell the
difference - not the composer, not the numbering, not the reviewer.

That is the one failure this kit cannot absorb, because the whole premise is
that a review frame is *evidence* rather than a drawing. A wrong wrapper
turns it back into a drawing that happens to have been rendered.

It has now happened twice, both times in `TODO(harness) 6/8` and nowhere
else.

**1. `darkTheme:` omitted.** A `MaterialApp` given a single `theme:`
switched on the `dark` flag renders both frames from one `ThemeData`. The
"dark" frame was never the app's dark theme - it was the light theme with a
brightness flag flipped. Wire all three and let the app choose, exactly as
`main.dart` does:

```dart
theme: ThemeData(brightness: Brightness.light, /* the app's real light */),
darkTheme: ThemeData(brightness: Brightness.dark, /* the app's real dark */),
themeMode: dark ? ThemeMode.dark : ThemeMode.light,
```

**2. A modal rendered detached.** paas_manager's login is a **modal
presented over a real splash background page**. The harness handed the modal
straight to `home:`, so the splash behind it never existed and the strip
showed a login floating on nothing - a screen that does not occur anywhere
in the product. The render was sharp, the numbering was correct, and it was
still wrong.

#### So: render a modal over its host

If the screen under test is a modal, a bottom sheet or a dialog, `home:` is
the **host page**, and the modal is opened over it before anything is
measured.

**Open it by driving the app's own trigger.** Not by presenting the modal
yourself, and not by pushing its route by hand. The barrier, the sheet
shape, the height constraint, the insets and the safe-area handling all come
from the app's own call site; a stand-in gets them wrong in exactly the way
that is hardest to notice, and a hand-pushed route stops noticing when the
real call site drifts.

This is what paas_manager's harness does, and it is the pattern to copy:

```dart
/// Opens the sign-in sheet the way the app opens it: by tapping LoginPage's
/// Login button, which calls `AppHelpers.showCustomModalBottomSheet` with
/// `const LoginScreen()`.
Future<void> openSheet(WidgetTester tester) async {
  final loginButton = find.widgetWithText(
    CustomButton,
    AppHelpers.getTranslation(TrKeys.login),
  );
  expect(
    loginButton,
    findsWidgets,
    reason: 'no Login button on LoginPage - the sheet cannot be opened the '
        'way the app opens it',
  );
  await tester.tap(loginButton.first, warnIfMissed: false);
  await _drain(tester, rounds: 4);
  expect(
    find.byType(LoginScreen),
    findsOneWidget,
    reason: 'tapping Login did not put the sign-in sheet on screen',
  );
}
```

Both `expect`s matter. They are what turn a silent wrapper fault into a loud
one: if the trigger disappears or stops opening the sheet, the render fails
with a reason instead of quietly producing a frame of the host page alone.

Call it in the render body immediately after the first `_drain`, before pass
1 measures:

```dart
await tester.pumpWidget(
  RepaintBoundary(key: boundaryKey, child: buildScreen(dark: dark)),
);
await _drain(tester);
await openSheet(tester);      // <- the modal is now over its host
```

> **Note.** That last line is currently a hand-edit inside the region the
> template tells you to leave alone. The template has no seam between the
> first drain and pass-1 measurement, so every shell with a modal has to add
> it by hand. If that turns out to be more than a one-off, the fix is a
> no-op `afterFirstPump` hook in the template rather than each harness
> editing the proven mechanism.

**When there is no reachable trigger** - the modal is only ever opened by a
push notification, a deep link, or a code path the demo fixtures cannot
reach - present it yourself from a post-frame callback over the host, using
the app's own presenter:

```dart
home: const _HostThenModal(host: SplashPage()),

// ...

class _HostThenModal extends StatefulWidget {
  const _HostThenModal({required this.host});

  final Widget host;

  @override
  State<_HostThenModal> createState() => _HostThenModalState();
}

class _HostThenModalState extends State<_HostThenModal> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      // The app's OWN presenter - showModalBottomSheet, showDialog, or the
      // helper the app wraps them in. Never a substitute.
      showDialog<void>(
        context: context,
        barrierDismissible: false,
        builder: (_) => const LoginModal(),
      );
    });
  }

  @override
  Widget build(BuildContext context) => widget.host;
}
```

The post-frame shape is not new either: paas_driver's `_CourierJourney`
already uses it to fire the home page's statistics fetch before the profile
renders. Prefer the trigger; fall back to this.

The tour lane learned all of this first and wrote it down. `auth.tour.yaml`
warns that routing straight to `/register` renders the sheet *"as bare pages
- not the UX a user ever sees"* - the same trap, reached from the other
side, with the same answer.

### 2.7 Why the screen is named, and not derived from the tour fragments

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

### 8.1 The guided tour runs it automatically, first

The button above is not the only trigger, and it is no longer the usual one.
[`universal-guided-tour.yml`](../../.github/workflows/universal-guided-tour.yml)
renders the strip as a **step inside its own job**, after the SDK compose /
`pub get` / `build_runner` work and **before** the APK build and both emulator
legs, and **fails the run when the render fails**. That is the whole point: a
compile break or a screen that will not lay out costs one minute instead of
forty, and no emulator time is burned on a tree that was never going to
render.

Three consequences worth knowing:

* **It is a step, not a job.** A separate job would land on a fresh VM and
  re-run the whole SDK compose - several minutes - purely to render. As a step
  it reuses the tree the tour already composed and adds about a minute.
* **It skips cleanly.** The step needs BOTH `test/render/render_screen_test.dart`
  and `test/render/strip.json`. A repo with neither (most of the fleet - the
  tour is distributed everywhere) skips it silently and tours exactly as
  before: nothing rendered, nothing uploaded, nothing committed. Not an empty
  file, not a placeholder.
* **The page is committed**, and so are the per-frame SVGs ([§10](#10-svg-per-frame-for-a-guide-or-a-deck)).
  The page goes to `<output-dir>/render-strip.html` and the SVGs to
  `<output-dir>/svg/` (`marketing/tour/` by
  default), so the tour's existing output commit ships them in the SAME commit
  as the screenshots and the feature guide, with the same `[skip ci]`
  convention and the same rebase handling. There is no second commit-back
  path. `readme_sections.py` then links it from the README's
  `@generated-render-strip` block.
  GitHub serves a committed `.html` as source, so that link opens the markup,
  not the rendered page - open the file from a checkout to read it.

Both lanes run the same code: [`run_strip.sh`](run_strip.sh) is the render +
compose pair, and the two workflows differ only in the environment they hand
it. The manual `workflow_dispatch` button is untouched.

---

## 9. One number, one chip - alternating across the frames

A screen rendered in **both** light and dark used to chip every element on
both frames: numbers 1-11 appeared twice and the page read as if it had 22
points. It does not any more.

The rule is **alternation, in numbering order**. Walk the numbers and hand
them to the frames in turn:

* The first number is chipped on the first frame, the second on the second
  frame, the third on the first again, and so on.
* Both frames end up carrying **roughly half** the numbers, so neither
  picture is bare and the reviewer's eye crosses between them - which is the
  point, because the two renders are what is being compared.
* An element that exists on **only one** frame is always chipped there and
  does **not** consume an alternation slot, so a frame-specific element
  cannot push the split lopsided.
* Everything a frame does not carry this turn is still in the markup, marked
  `rep`, hidden by CSS. The **repeats** checkbox in the mode bar shows the
  full set again - the same mechanism as the **chips** checkbox beside it.
  `"repeats_default": true` in the config makes that the starting state.

On the paas_driver courier profile (numbers 13-27) that reads:

| Frame | Carries |
|---|---|
| `courier profile - light` | 13, 15, 17, 19, 21, 23, 25, 27 |
| `courier profile - dark` | 14, 16, 18, 20, 22, 24, 26 |

This replaced an earlier rule - *"the first frame owns every number; a later
frame chips only what measurably changed"* - which fixed the double-count but
left the dark frame with nothing on it. The pixel change-detection that rule
needed (per-element luminance standard deviation against a 35% threshold) no
longer decides anything and has been removed rather than left orphaned.

Numbering is untouched by any of this. Roles decide what is *drawn*; a
number is still bound to a key for the life of the page and
`--emit-numbering` round-trips exactly as before.

> **The page alternates. The SVG export does not.** See [§10](#10-svg-per-frame-for-a-guide-or-a-deck).

---

## 10. SVG per frame, for a guide or a deck

The page is the review format. It is the wrong shape for *placement* - one
long scroll cannot be dropped into a slide. So `--emit-svg DIR` writes, per
frame, two standalone files:

```text
DIR/<variant>.annotated.svg    chips + numbered legend
DIR/<variant>.clean.svg        the screen, no annotation
```

`<variant>` is the harness sidecar's own `variant` name (falling back to the
PNG's stem), slugified - `profile_light` becomes `profile-light.svg`. The
names are predictable on purpose: a document references them without
guessing.

**They are genuine vector wrappers, not a flattened picture of the page.**
The screenshot is the only raster in the file - Flutter rasterises, there is
no vector of the screen to recover - and it is *embedded* as a data URI, so
the file travels alone with no external reference. Everything else is real
vector: chips are `<circle>` + `<text>`, the legend and the caption are
`<text>`. They stay sharp at any size on a slide and stay selectable in a
design app.

The two variants are the page's own two modes rather than a second idea of
what annotation is: `clean` omits exactly what the page's `.present` class
hides.

**The annotated SVG carries every numbered element on its frame** - it does
*not* alternate the way the page does ([§9](#9-one-number-one-chip---alternating-across-the-frames)).
The page alternates because its frames are read side by side, so a number
only has to be said once. An exported SVG is used **alone** - in a guide, on
a slide - with no second frame beside it to carry the other half, so a frame
that dropped its repeats would ship unlabelled widgets and a legend that does
not describe the picture. Page alternates, SVG is complete; do not "fix"
either to match the other. Numbers stay global either way: chip 13 is 13 on
the light SVG and on the dark one, never renumbered per file.

**The screen is drawn inside the page's own device bezel** - same radius,
colour, padding and inset ring, read from shared constants so the two
renderings cannot drift. The status pill uses the page's `CHIP_COLOR`, the
chip radius is the page's 17px chip (8.5), and the type is the page's system
stack. The screenshot's data URI is emitted **once**, as `xlink:href`: SVG
1.1's spelling, which is what Illustrator, Affinity and Figma read on import.
Chromium, librsvg and cairosvg all resolve either spelling, so the renderers
cast no vote and the widest importer support decides.

Both CI lanes write them: the tour commits them to
`marketing/tour/svg/` beside the page, and the manual lane ships them inside
the `render-strip` artifact.

---

## 11. Keeping the render in sync with the screen

A project standing rule, extended to cover this tool: a PR that changes a
demo-visible surface updates the owning SDK's tour fragment and demo seeds in
the same PR. The render is now on that list. If a PR changes a screen the
render covers, it updates that screen's render config - and its example, where
one is committed - in the same PR, exactly as it updates the tour fragment and
the seeds. A render that lags the code stops being evidence and becomes another
drawing, which is the one thing this tool exists to avoid.

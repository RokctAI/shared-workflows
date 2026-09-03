# Render-harness starter kit

Copies-and-edits for a thread that needs a screen reviewed as a **real
render** rather than a hand-drawn frame. Full pipeline documentation lives in
[`scripts/render/README.md`](../../scripts/render/README.md).

The harness renders the SDKs' own demo/seed fixtures and should not be wired
to a live client or backend.

The harness is a **throwaway package**. It is never committed to an app or an
SDK repo: it lives in scratch space beside read-only clones of the repos it
renders, and it is deleted when the review is over. Only the strip config and
its numbering map are worth keeping.

The exception is CI: to run the pipeline through
[`universal-render-strip.yml`](../../.github/workflows/universal-render-strip.yml)
a shell repo commits the render test and its strip config (by default
`test/render/render_screen_test.dart` and `test/render/strip.json`) and runs
against its own composed `lib/`, so no path deps or scratch clones are needed.
Locally, the throwaway package with path deps is still the fastest loop.

| File in the scratch package | Source | Editing needed |
|---|---|---|
| `pubspec.yaml` | [`pubspec.yaml`](pubspec.yaml) here | path deps, the app's `dependency_overrides`, the packages the screen imports |
| `test/render_screen_test.dart` | [`render_screen_test.dart`](render_screen_test.dart) here | the eight `TODO(harness)` markers - mostly just naming the screen |
| `fonts/*.ttf`, `assets/google_fonts/` | fetched once | none, but see the google_fonts gotcha |
| `<screen>.strip.json` | [`scripts/render/examples/lms-profile.strip.json`](../../scripts/render/examples/lms-profile.strip.json) | captions, statuses, legend labels, notes |

## Adoption steps

1. Install a Flutter stable release that satisfies the host SDK's `flutter:`
   constraint - **not** the Dart version printed next to `sdk:`. Clone the
   SDK repos read-only next to the harness package.
2. Copy `pubspec.yaml` here and fill in the path dependencies and the app
   shell's `dependency_overrides` verbatim, then `flutter pub get`.
3. If a feature SDK does not compile standalone, run the host repo's
   `dart run tool/inject_tr_keys.dart` first, and `git checkout --` the clone
   afterwards - it writes into the base_sdk clone.
4. Copy `render_screen_test.dart` to `test/` and work the eight
   `TODO(harness)` markers in order: imports, the SDK demo-mode DI, the two
   exception hooks, screen registration, the widget under test, the element
   specs, the fonts. Nothing outside those markers should need changing - the
   height fixed-point pass, the real-event-loop drain, the `RepaintBoundary`
   capture and the rect sidecar are the proven mechanism.

   Markers 3 and 4 are EXCEPTIONS and are usually left empty: the SDKs supply
   their own demo data through marker 2. See §2.5 of
   [`scripts/render/README.md`](../../scripts/render/README.md).
5. `flutter test --dart-define=IS_DEMO=true test/render_screen_test.dart`.
   Without `IS_DEMO=true` the SDKs register their real HTTP repositories and
   you render an empty screen. Open a PNG before going any further: if the
   type looks like uniform blocks, the fonts did not load and nothing
   downstream is worth doing.
6. Write the strip config and compose:

   ```bash
   python scripts/render/compose_strip.py --config <screen>.strip.json \
       --base-dir <scratch>/render-harness/out --out strip.html \
       --emit-numbering numbering.json
   ```

7. Commit the numbering map back into the config so the next revision keeps
   the same numbers.

## Things that are easy to get wrong

- **Rendering both themes.** Keep the dark *and* light `testWidgets` blocks.
  Theme bugs only ever appear in the variant nobody rendered.
- **`pumpAndSettle` on real async.** Widget-test fake-async never runs the
  real event loop, so a screen awaiting a real Future settles as empty. Use
  the template's `_drain`, which alternates `runAsync` with `pump`.
- **One-pass height.** The frame height must be measured and then re-rendered
  at that height: screenutil's `.h` sizes scale with the viewport, so the
  height converges rather than being knowable up front.
- **Forgetting `--dart-define=IS_DEMO=true`.** The SDKs then wire their real
  HTTP repositories, every fetch fails, and the render is of a broken screen.
- **Hand-writing fixtures.** The SDKs own their demo data; reach for marker 3
  only for history a device accumulates through use (an attendance ledger, a
  downloads list), and marker 4 only where no demo implementation exists at
  all. A value the app did not compute is decoration, and the render stops
  being evidence.

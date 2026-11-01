// Copyright (c) 2026 ROKCT INTELLIGENCE (PTY) LTD
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be included in all
// copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
// SOFTWARE.

// TEMPLATE (templates/render-harness/ in RokctAI/shared-workflows): copy to
// the THROWAWAY harness package as test/render_screen_test.dart and work
// through the `TODO(harness)` markers. Everything NOT marked TODO is the
// proven mechanism and should be left alone - the fixed-point height
// measurement, the real-event-loop drain, the RepaintBoundary capture and
// the rect sidecar are what make the output composable by
// scripts/render/compose_strip.py.
//
// What this is: a widget test that renders a REAL screen from real app code
// at phone size, writes a PNG of it, and writes a sidecar JSON of every
// element rect the review wants to point a number at. See
// scripts/render/README.md.
//
// DATA COMES FROM THE SDK, NOT FROM HERE. The harness switches the process
// into a demo session (`DemoSession.instance.activate()`, so
// `DemoSession.demoActive` is true) and calls each SDK's own DI registration.
// The SDKs register their REAL Http repositories as usual; base_sdk's
// `DemoGatewayInterceptor` then answers every platform call from the
// `<cmd>.json` fixtures each SDK registered with
// `DemoFixtures.registerAssetDirectory`. There are no demo or mock
// repositories: the render exercises the same repository code the app ships.
// Naming the screen should be nearly the whole job. Hand-written fakes are an
// EXCEPTION with its own marker below - never the default.
//
// The harness renders fixtures and should not be wired to a live backend.
// No build flag is needed (IS_DEMO no longer exists; TOUR_MODE=true also
// turns demo on, but it is the guided-tour switch and not needed here).
//
// Run:  flutter test test/render/render_screen_test.dart
//       RENDER_SUFFIX=_draft flutter test test/render/render_screen_test.dart

import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

// TODO(harness) 1/8 - imports of the code under test.
// Import the REAL screen, its section/route registry and whatever the screen
// reads (notifiers, stores, theme seam). Importing `src/...` paths directly is
// expected here: the harness is deliberately coupled to the shipped code, not
// to a public facade.
//
//   import 'package:flutter_riverpod/flutter_riverpod.dart';
//   import 'package:flutter_screenutil/flutter_screenutil.dart';
//   import 'package:shared_preferences/shared_preferences.dart';
//   import 'package:google_fonts/google_fonts.dart';
//   import 'package:get_it/get_it.dart';
//   import 'package:<app>_sdk/src/presentation/pages/<screen>.dart';
//   import 'package:<app>_sdk/src/common/di/<app>_di.dart';
//   import 'package:base_sdk/src/di/base_di.dart';
//   import 'package:base_sdk/src/presentation/theme/app_style.dart';
//   import 'package:base_sdk/src/services/local_storage.dart';
//   import 'package:base_sdk/src/services/demo_session.dart';

// ---------------------------------------------------------------------------
// Render settings - phone size the reviews are judged at. Only change these
// if the whole review is moving to a different device class.
// ---------------------------------------------------------------------------

/// Logical width of the frame (iPhone-class phone). The strip composer scales
/// the PNG to the bezel, so this only affects LAYOUT, not output resolution.
const double kLogicalWidth = 390;

/// Device pixel ratio the PNG is captured at (3 = @3x, crisp on any display).
const double kDevicePixelRatio = 3.0;

/// Tall probe viewport for the first pass. Must exceed the tallest screen; the
/// second pass shrinks to the measured content height.
const double kProbeHeight = 2600;

/// Slack below the last element in the final frame, in logical pixels.
const double kBottomPadding = 20;

/// Phone height used when the content is taller than [kProbeHeight] and
/// cannot be fitted (iPhone 12-15 class, 390 x 844). A warning is logged.
const double kDeviceHeight = 844;

/// How long (real time) the harness waits for the screen to be READY (see
/// [readyFinders]) before it fails instead of capturing a blank or loading
/// frame.
const Duration kReadyTimeout = Duration(seconds: 30);

/// TODO(harness) 2/8 - the SDK's own demo data. THIS IS THE MAIN PATH.
///
/// Every SDK ships `<cmd>.json` fixtures and registers them from its own DI
/// via `DemoFixtures.registerAssetDirectory`. Activate the demo session, then
/// call the DI registrations in the same order the composed app does: base
/// first, then each feature SDK. Each SDK registers its REAL Http repository;
/// `DemoGatewayInterceptor` (installed on base_sdk's HTTP client) sees
/// `DemoSession.demoActive` and answers each `rokct.platform.api` call from
/// the fixture for its cmd. Nothing you wrote has to be kept truthful.
///
///   SharedPreferences.setMockInitialValues(<String, Object>{});
///   await LocalStorage.init();
///   await DemoSession.instance.activate();
///   BaseSdkDependencies.register(GetIt.I);
///   AuthSdkDependencies.register(GetIt.I);
///   UsersSdkDependencies.register(GetIt.I);
///   LmsSdkDependencies.register(GetIt.I);
///
/// A cmd with no fixture throws `DemoFixtureMissing(cmd)` - that is an SDK
/// gap to fix in the SDK's fixtures, not something to paper over here.
///
/// Registration is guarded by `isRegistered`, so a host may pre-register its
/// own implementation first and the SDK will leave it alone - which is also
/// how the exception hook below works.
Future<void> registerDemoDependencies() async {
  // SharedPreferences.setMockInitialValues(<String, Object>{});
  // await LocalStorage.init();
  // await DemoSession.instance.activate();
  // assert(DemoSession.demoActive,
  //     'demo session not active: the SDKs would call a real backend and '
  //     'the render is of a broken, empty screen');
  // BaseSdkDependencies.register(GetIt.I);
}

/// TODO(harness) 3/8 - EXCEPTION: device history the demo mode cannot supply.
///
/// Leave this EMPTY for most screens. It exists for one real gap: stores that
/// accumulate from a device's own usage - an attendance ledger, a downloads
/// list, a watch history - are written by the app as the user does things, so
/// demo mode alone leaves them empty (a fixture answers the write cmd but
/// stores nothing; the ledger is filled by the schedule as lessons are
/// attended). A widget test never walks that journey.
///
/// When a screen genuinely reads such history, seed it through the app's REAL
/// store API so the derived values (totals, averages, streaks) are still
/// computed by the app - and say in the strip config's notes that you did.
/// Anything hand-written that the app would otherwise have computed is a
/// number the reviewer cannot trust.
Future<void> seedDeviceHistory(WidgetTester tester) async {
  await tester.runAsync(() async {
    // await ProfileStore().recordAttendance(...);  // attendance ledger only
  });
}

/// TODO(harness) 4/8 - EXCEPTION: stub a service with no demo implementation.
///
/// Also usually EMPTY. Reach for it only where a service the screen needs does
/// not go through the platform gateway, so no fixture can answer it. Pre-register the stub in `GetIt.I` BEFORE
/// `registerDemoDependencies()` runs and the SDK's guarded registration will
/// stand aside. Let stubs throw from `noSuchMethod` by default: it names the
/// exact member the screen touches, so the stub cannot quietly grow.
///
///   class _StubThing implements ThingFacade {
///     @override
///     dynamic noSuchMethod(Invocation i) =>
///         throw UnimplementedError('thing: ${i.memberName}');
///   }
void registerExceptionStubs() {}

/// TODO(harness) 5/8 - register sections / routes / gates.
///
/// Called once per variant, before the widget is pumped. Register the same
/// sections the composed app registers, and resolve gates the way they resolve
/// for the persona being shown (e.g. admin gates false for a student frame).
void registerScreen() {
  // ProfileSectionRegistry.I
  //   ..reset()
  //   ..onEditProfile = (context) {}
  //   ..onLogout = (context) {};
  // LmsProfileSections.registerStudentSections(...);
}

/// TODO(harness) 6/8 - the widget under test.
///
/// Return the REAL screen widget, wrapped in whatever the app wraps it in:
/// ProviderScope with the demo overrides, ScreenUtilInit with the app's
/// design size, MaterialApp with the app's `theme` AND `darkTheme`. Do not
/// substitute a simplified scaffold - the wrapping is part of what is being
/// reviewed.
///
/// THIS IS THE MARKER THAT MAKES A RENDER LIE.
///
/// Everything else in this file fails loudly. A screen that does not compile
/// stops the run; an element that does not match throws with a reason; a
/// harness that writes no PNG fails the gate. An INCOMPLETE WRAPPER fails
/// SILENTLY - it produces a clean, plausible, entirely convincing PNG of a
/// screen no user will ever see, and nothing downstream can tell. The whole
/// point of this kit is that a review frame is evidence rather than a
/// drawing; a wrong wrapper turns it back into a drawing that happens to
/// have been rendered.
///
/// It has now happened twice, both times in the wrapper and nowhere else:
///
///   1. `darkTheme:` OMITTED. A MaterialApp given a single `theme:` switched
///      on the `dark` flag renders both frames from one ThemeData, so the
///      "dark" frame was never the app's dark theme - it was the light
///      theme with a brightness flag flipped. Wire `theme:` + `darkTheme:` +
///      `themeMode:` and let the app choose, exactly as main.dart does. The
///      snippet below is that shape; the earlier one-ThemeData shape is the
///      bug, so do not copy it back in from an older harness.
///
///   2. A MODAL RENDERED DETACHED. paas_manager's login is a MODAL presented
///      over a real splash background page. The harness handed the modal
///      straight to `home:`, so the splash behind it never existed, and the
///      strip showed a login screen floating on nothing - a screen that does
///      not occur anywhere in the product. The render was sharp, the
///      numbering was correct, and it was still wrong.
///
/// So: IF THE SCREEN IS A MODAL, A BOTTOM SHEET OR A DIALOG, RENDER IT OVER
/// ITS HOST. `home:` is the HOST page, and the modal is opened over it
/// before anything is measured.
///
/// OPEN IT BY DRIVING THE APP'S OWN TRIGGER - tap the button the user taps -
/// not by presenting the modal yourself and not by pushing its route by
/// hand. The barrier, the sheet shape, the height constraint, the insets and
/// the safe-area handling all come from the app's own call site; a stand-in
/// gets them wrong in exactly the way that is hardest to notice, and a
/// hand-pushed route stops noticing when the real call site drifts.
///
/// paas_manager's harness is the pattern to copy - see the `openSheet`
/// sketch below and section 2.6 of scripts/render/README.md. Where no
/// trigger is reachable (a modal only ever opened by a push notification or
/// a deep link), fall back to presenting it over the host from a post-frame
/// callback with the app's OWN presenter - the `_HostThenModal` sketch,
/// also below.
///
/// The tour lane learned this first and wrote it down: `auth.tour.yaml`
/// warns that routing straight to `/register` renders the sheet "as bare
/// pages - not the UX a user ever sees". Same trap, same answer.
Widget buildScreen({required bool dark}) {
  // return ProviderScope(
  //   overrides: [profileProvider.overrideWith((ref) => _DemoNotifier())],
  //   child: ScreenUtilInit(
  //     designSize: const Size(375, 812),
  //     builder: (context, child) => MaterialApp(
  //       debugShowCheckedModeBanner: false,
  //       // BOTH themes, chosen by themeMode - never one ThemeData switched
  //       // on `dark`. See fault 1 above.
  //       theme: ThemeData(
  //         useMaterial3: false,
  //         brightness: Brightness.light,
  //         scaffoldBackgroundColor: AppStyle.surfaceLightRaw,
  //       ),
  //       darkTheme: ThemeData(
  //         useMaterial3: false,
  //         brightness: Brightness.dark,
  //         scaffoldBackgroundColor: AppStyle.surfaceDarkRaw,
  //       ),
  //       themeMode: dark ? ThemeMode.dark : ThemeMode.light,
  //
  //       // A screen that IS a page: hand it over directly.
  //       home: const YourRealScreen(),
  //
  //       // A screen that is a MODAL / SHEET / DIALOG: hand over its HOST
  //       // and open the modal over it from the render body with
  //       // `openSheet(tester)`. See fault 2 above and the sketches below.
  //       // home: const LoginPage(),
  //     ),
  //   ),
  // );
  throw UnimplementedError('TODO(harness) 6/8: return the real screen widget');
}

// WHEN THE SCREEN UNDER TEST IS A MODAL, a bottom sheet or a dialog.
//
// PREFERRED - drive the app's own trigger. Call this from the render body
// immediately after the first `_pumpUntilReady`, before the frame is fitted:
//
//     await _pumpUntilReady(tester, phase: ' ($name)');
//     await openSheet(tester);   // the modal is now over its host
//
// Both `expect`s are load-bearing: they turn a silent wrapper fault into a
// loud one. If the trigger disappears or stops opening the sheet, the render
// fails with a reason instead of quietly producing a frame of the host page
// on its own.
//
// /// Opens the sheet the way the APP opens it - by tapping the real button,
// /// which calls the app's own showCustomModalBottomSheet. Driving the
// /// button rather than pushing a route by hand is the point: the sheet's
// /// constraints, its shape and its scrim all come from the app's call site,
// /// so none of them can drift from what ships without this test noticing.
// Future<void> openSheet(WidgetTester tester) async {
//   final trigger = find.widgetWithText(
//     CustomButton,
//     AppHelpers.getTranslation(TrKeys.login),
//   );
//   expect(
//     trigger,
//     findsWidgets,
//     reason:
//         'no Login button on the host page - the sheet cannot be opened '
//         'the way the app opens it',
//   );
//   await tester.tap(trigger.first, warnIfMissed: false);
//   await _drain(tester, rounds: 4);
//   expect(
//     find.byType(LoginScreen),
//     findsOneWidget,
//     reason: 'tapping the trigger did not put the sheet on screen',
//   );
// }
//
// FALLBACK - only where no trigger is reachable (a modal opened solely by a
// push notification, a deep link, or a path the demo fixtures cannot reach).
// Present it over the host from a post-frame callback, with the app's OWN
// presenter. Same shape as paas_driver's shipping `_CourierJourney`.
//
// class _HostThenModal extends StatefulWidget {
//   const _HostThenModal({required this.host});
//
//   final Widget host;
//
//   @override
//   State<_HostThenModal> createState() => _HostThenModalState();
// }
//
// class _HostThenModalState extends State<_HostThenModal> {
//   @override
//   void initState() {
//     super.initState();
//     WidgetsBinding.instance.addPostFrameCallback((_) {
//       if (!mounted) return;
//       // The app's OWN presenter - showModalBottomSheet, showDialog, or the
//       // helper the app wraps them in. Never a substitute.
//       showDialog<void>(
//         context: context,
//         barrierDismissible: false,
//         builder: (_) => const LoginModal(),
//       );
//     });
//   }
//
//   @override
//   Widget build(BuildContext context) => widget.host;
// }

/// TODO(harness) 7/8 - the elements the review points at.
///
/// One entry per numbered point. `key` is the STABLE IDENTITY the strip
/// composer binds a number to for the life of the page - use a durable
/// identifier (the section/registry id where one exists, else a
/// `screen.element` slug you commit to). Reword `label` freely; never reword
/// `key`, and never recycle a key for a different element.
///
/// Private widgets have no importable type: match them by runtime type NAME
/// (`w.runtimeType.toString() == '_IdentityHeader'`). Matching by name also
/// lets one harness compile against two branches that do not share a type.
List<ElementSpec> elementSpecs() {
  return <ElementSpec>[
    // ElementSpec(
    //   key: 'base.identity_header',
    //   label: 'Identity header - name, contact, role, edit/logout',
    //   finder: find.byWidgetPredicate(
    //       (w) => w.runtimeType.toString() == '_IdentityHeader'),
    // ),
    // ElementSpec.each(
    //   keyOf: (i, w) => 'lms.setting_row.${(w as LmsSettingCard).title}',
    //   labelOf: (i, w) => 'Setting row - ${(w as LmsSettingCard).title}',
    //   finder: find.byType(LmsSettingCard),
    // ),
  ];
}

/// TODO(harness) 7/8 (cont.) - what must be on screen before the capture.
///
/// The frame is captured only once EVERY finder here matches and no
/// CircularProgressIndicator is showing; otherwise the test FAILS after
/// [kReadyTimeout]. Name the widgets the demo data produces (a list row, a
/// card), not the page scaffold, which exists while the data is still
/// loading. A fixed sleep here is what shipped blank light frames.
List<Finder> readyFinders() => <Finder>[
  // find.byType(LmsSettingCard),
];

/// TODO(harness) 8/8 - real fonts.
///
/// Without this every glyph renders as the Ahem/FlutterTest block font and the
/// PNG is worthless. Load the app's real faces from files (see the README's
/// google_fonts section for the asset naming the test path requires), plus the
/// icon fonts, plus whatever family bare `TextStyle`s fall back to.
Future<void> loadRealFonts() async {
  final root = Directory.current.path;

  Future<void> load(String family, List<String> files) async {
    final loader = FontLoader(family);
    for (final path in files) {
      final bytes = File(path).readAsBytesSync();
      loader.addFont(Future.value(ByteData.view(bytes.buffer)));
    }
    await loader.load();
  }

  // google_fonts resolves a family PLUS its variant name (e.g. `Inter_600`),
  // so register both the per-weight variant families and the plain family
  // (the latter is what fontFamilyFallback lands on).
  const weights = <String, String>{
    'regular': 'Inter-400.ttf',
    '500': 'Inter-500.ttf',
    '600': 'Inter-600.ttf',
    '700': 'Inter-700.ttf',
    '800': 'Inter-800.ttf',
  };
  for (final entry in weights.entries) {
    await load('Inter_${entry.key}', ['$root/fonts/${entry.value}']);
  }
  await load(
    'Inter',
    weights.values.map((file) => '$root/fonts/$file').toList(),
  );

  // Bare TextStyles with no family fall back to the platform default. The
  // same three weights also ship inside the Flutter SDK cache as
  // `$FLUTTER_ROOT/bin/cache/artifacts/material_fonts/Roboto-{Regular,Medium,
  // Bold}.ttf`, so a shell can point here instead of committing a copy.
  final roboto = <String>[
    '$root/fonts/Roboto-400.ttf',
    '$root/fonts/Roboto-500.ttf',
    '$root/fonts/Roboto-700.ttf',
  ];
  await load('Roboto', roboto);

  // THE BLOCK-GLYPH ALIASES. A block glyph on an otherwise correct frame is
  // usually NOT a missing weight: it is text asking for a family the engine
  // never had registered. Two known sources, both proven with a width probe
  // (an Ahem block advances exactly one em, so "Back" at 20px lays out 80.0pt
  // wide in the block font against 43.9pt in Roboto):
  //
  //   * a widget floating in the route Stack with NO Material ancestor (a
  //     back pill, a floating nav) inherits WidgetsApp's fallback
  //     DefaultTextStyle, whose family is 'monospace' - inside a Material the
  //     theme's Typography supplies 'Roboto', which is why SnackBars are fine;
  //   * an inline SVG <text font-family="Helvetica, Arial, sans-serif">:
  //     vector_graphics_compiler passes the attribute through WHOLE, so the
  //     CSS stack becomes ONE family name, not a fallback list.
  //
  // Registering faces under 'Ahem' / 'FlutterTest' does not displace the
  // engine's block default; aliasing the asked-for names onto a real face is
  // what a device does. The last entry is deliberately the whole CSS stack.
  for (final alias in <String>[
    'monospace',
    'Helvetica',
    'Arial',
    'sans-serif',
    'Helvetica, Arial, sans-serif',
  ]) {
    await load(alias, roboto);
  }

  // Icon fonts: MaterialIcons ships inside the Flutter SDK cache; package
  // icon fonts (Remix, Cupertino, ...) live in the pub cache and are
  // registered under their package-scoped family name.
  final flutterRoot = Platform.environment['FLUTTER_ROOT'];
  if (flutterRoot != null) {
    await load('MaterialIcons', [
      '$flutterRoot/bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf',
    ]);
  }
  // final pubCache = Platform.environment['PUB_CACHE'] ??
  //     '${Platform.environment['HOME']}/.pub-cache';
  // await load('packages/remixicon/Remix', ['$pubCache/.../fonts/Remix.ttf']);
}

// ===========================================================================
// Below here is the mechanism. Leave it alone. It waits for the screen to be
// ready (no fixed sleep), fits the frame to the real content, and FAILS rather
// than capture a blank, loading or block-glyph frame. The composer's quality
// gate (scripts/render/frame_quality.py) checks the result again.
// ===========================================================================

/// One numbered point: a finder, a stable key, and a human label.
class ElementSpec {
  ElementSpec({required this.key, required this.label, required this.finder})
    : keyOf = null,
      labelOf = null;

  /// A finder that matches SEVERAL widgets (e.g. every settings row); key and
  /// label are derived per match, so the numbering stays per-row.
  ElementSpec.each({
    required this.keyOf,
    required this.labelOf,
    required this.finder,
  }) : key = '',
       label = '';

  final String key;
  final String label;
  final Finder finder;
  final String Function(int index, Widget widget)? keyOf;
  final String Function(int index, Widget widget)? labelOf;
}

class _Measured {
  _Measured(this.key, this.label, this.rect);

  final String key;
  final String label;
  final Rect rect;
}

/// Mocks the path_provider channel so real drift/sqlite stores can open a
/// database in a temp dir. This is the ONLY platform channel the harness
/// fakes - everything else runs its real code path.
void _mockPathProvider(String dir) {
  const channel = MethodChannel('plugins.flutter.io/path_provider');
  TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
      .setMockMethodCallHandler(channel, (call) async => dir);
}

/// Lets REAL async work (drift isolate, futures, file IO) complete, then pumps
/// frames so the resulting setStates land. Only for helpers such as
/// `openSheet` that need a fixed settle after a tap; the capture itself
/// waits with [_pumpUntilReady].
///
/// `pumpAndSettle` cannot do this: widget-test fake-async never runs the real
/// event loop, so a screen that waits on a real Future settles as empty.
// Kept for the commented openSheet helper above; unused until it is enabled.
// ignore: unused_element
Future<void> _drain(WidgetTester tester, {int rounds = 8}) async {
  for (var i = 0; i < rounds; i++) {
    await tester.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 120)),
    );
    await tester.pump(const Duration(milliseconds: 250));
  }
}

/// Pumps until the screen is READY - every [readyFinders] matches and no
/// CircularProgressIndicator is showing - letting real async work run between
/// frames. Fails the test on [kReadyTimeout] instead of capturing.
Future<void> _pumpUntilReady(WidgetTester tester, {String phase = ''}) async {
  final finders = readyFinders();
  if (finders.isEmpty) {
    fail(
      'readyFinders() is empty - name the widgets the demo data produces '
      '(TODO(harness) 7/8), or the frame may be captured while loading',
    );
  }
  final deadline = DateTime.now().add(kReadyTimeout);
  final spinner = find.byType(CircularProgressIndicator);
  var stableFrames = 0;
  while (true) {
    await tester.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 50)),
    );
    await tester.pump(const Duration(milliseconds: 100));
    final ready =
        finders.every((f) => f.evaluate().isNotEmpty) &&
        spinner.evaluate().isEmpty;
    stableFrames = ready ? stableFrames + 1 : 0;
    if (stableFrames >= 2) break;
    if (DateTime.now().isAfter(deadline)) {
      final missing = finders
          .where((f) => f.evaluate().isEmpty)
          .map((f) => f.describeMatch(Plurality.zero))
          .toList();
      fail(
        'screen not ready after ${kReadyTimeout.inSeconds}s$phase: '
        '${missing.isEmpty ? '' : 'missing ${missing.join(', ')}; '}'
        '${spinner.evaluate().length} spinner(s) still showing. '
        'Refusing to capture a blank or loading frame.',
      );
    }
  }
  // Let entrance animations finish so nothing is captured half-faded.
  for (var i = 0; i < 10; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

/// Rect, in logical px, of every painted leaf under [root]: text, images,
/// custom paint, decorated and physical boxes. Offstage subtrees and the
/// unselected children of an IndexedStack (laid out, never painted) are
/// skipped.
Map<RenderBox, Rect> _paintedLeaves(RenderObject root) {
  final out = <RenderBox, Rect>{};
  void visit(RenderObject o) {
    if (o is RenderOffstage && o.offstage) return;
    if (o is RenderIndexedStack) {
      var child = o.firstChild;
      for (var i = 0; child != null; i++) {
        if (i == o.index) visit(child);
        child = o.childAfter(child);
      }
      return;
    }
    if (o is RenderBox &&
        o.attached &&
        o.hasSize &&
        (o is RenderParagraph ||
            o is RenderImage ||
            o is RenderCustomPaint ||
            o is RenderDecoratedBox ||
            o is RenderPhysicalModel ||
            o is RenderPhysicalShape)) {
      final rect = MatrixUtils.transformRect(
        o.getTransformTo(root),
        Offset.zero & o.size,
      );
      if (rect.width > 0 && rect.height > 0) out[o] = rect;
    }
    o.visitChildren(visit);
  }

  root.visitChildren(visit);
  return out;
}

/// How tall the frame must be to show all of the content and nothing else.
///
/// The screen root (and any background) fills the probe viewport, so its rect
/// says nothing about the content. The screen is laid out at two probe
/// heights and every painted leaf compared: a leaf that did not move is
/// CONTENT; a leaf that moved with the viewport bottom and kept its size is
/// PINNED chrome (tab bar, floating button), reserved below the content so it
/// never covers it; anything else (stretched backgrounds) is ignored. Returns
/// null when the content does not fit inside [kProbeHeight].
Future<double?> _contentHeight(
  WidgetTester tester,
  RenderObject Function() root,
) async {
  const shrink = 400.0;
  final tall = _paintedLeaves(root());
  _setViewHeight(tester, kProbeHeight - shrink);
  await _pumpUntilReady(tester, phase: ' (second probe)');
  final short = _paintedLeaves(root());
  _setViewHeight(tester, kProbeHeight);
  await _pumpUntilReady(tester, phase: ' (back to probe height)');

  var contentBottom = 0.0;
  var pinnedReserve = 0.0;
  var matched = 0;
  for (final entry in tall.entries) {
    final a = entry.value;
    final b = short[entry.key];
    if (b != null) matched++;
    if (b == null || (a.bottom - b.bottom).abs() < 0.5) {
      if (a.bottom > contentBottom) contentBottom = a.bottom;
    } else if ((a.bottom - b.bottom - shrink).abs() < 0.5 &&
        (a.height - b.height).abs() < 0.5) {
      final reserve = kProbeHeight - a.top;
      if (reserve > pinnedReserve) pinnedReserve = reserve;
    }
  }
  if (matched == 0) {
    throw StateError(
      'the screen rebuilt every render object between the two '
      'probes, so content and viewport-pinned chrome cannot be told apart',
    );
  }
  if (contentBottom <= 0) {
    throw StateError('no painted content found under the screen');
  }
  final height = contentBottom + pinnedReserve + kBottomPadding;
  // ignore: avoid_print
  print(
    'render: content ends at ${contentBottom.toStringAsFixed(1)}, '
    'pinned chrome needs ${pinnedReserve.toStringAsFixed(1)} -> '
    'frame height ${height.toStringAsFixed(1)}',
  );
  if (contentBottom + pinnedReserve >= kProbeHeight - 1) return null;
  return height;
}

void _setViewHeight(WidgetTester tester, double height) {
  tester.view.physicalSize = Size(
    kLogicalWidth * kDevicePixelRatio,
    height * kDevicePixelRatio,
  );
}

/// Texts on screen drawn in the FlutterTest/Ahem block font. A block glyph
/// advances exactly one em, so a single-line text whose width is
/// (characters x font size) is in the block font: its family was never
/// registered in [loadRealFonts].
List<String> _blockGlyphTexts(RenderObject root) {
  final hits = <String>[];
  void visit(RenderObject o) {
    if (o is RenderOffstage && o.offstage) return;
    if (o is RenderParagraph && o.attached && o.hasSize) {
      final text = o.text.toPlainText(includePlaceholders: false);
      final style = o.text.style;
      final size = style?.fontSize;
      final chars = text.runes.length;
      if (size != null &&
          chars >= 3 &&
          !text.contains('\n') &&
          o.text is TextSpan &&
          ((o.text as TextSpan).children?.isEmpty ?? true)) {
        final width = o.getMaxIntrinsicWidth(double.infinity);
        final em = o.textScaler.scale(size);
        final spacing = (style?.letterSpacing ?? 0) * chars;
        if ((width - spacing - chars * em).abs() < 0.5) {
          hits.add('${style?.fontFamily ?? '(default)'}: "$text"');
        }
      }
    }
    o.visitChildren(visit);
  }

  root.visitChildren(visit);
  return hits;
}

List<_Measured> _measure(WidgetTester tester, List<ElementSpec> specs) {
  final measured = <_Measured>[];
  for (final spec in specs) {
    final elements = spec.finder.evaluate().toList();
    for (var i = 0; i < elements.length; i++) {
      try {
        final widget = elements[i].widget;
        measured.add(
          _Measured(
            spec.keyOf?.call(i, widget) ?? spec.key,
            spec.labelOf?.call(i, widget) ?? spec.label,
            tester.getRect(spec.finder.at(i)),
          ),
        );
      } catch (_) {
        // Off-stage or unlaid-out matches are skipped rather than failing the
        // render: a section hidden by a gate is a legitimate outcome.
      }
    }
  }

  // Top-to-bottom, then drop wrappers that share a rect with a more specific
  // match (a decorated card whose child is the row we already measured).
  measured.sort((a, b) => a.rect.top.compareTo(b.rect.top));
  final deduped = <_Measured>[];
  for (final item in measured) {
    final clash = deduped.any(
      (kept) =>
          (kept.rect.top - item.rect.top).abs() < 2 &&
          (kept.rect.height - item.rect.height).abs() < 4,
    );
    if (!clash) deduped.add(item);
  }
  return deduped;
}

/// Renders one variant end to end and writes `out/<name>.png` + `out/<name>.json`.
Future<void> renderVariant(
  WidgetTester tester, {
  required bool dark,
  required String name,
  required String dbDir,
}) async {
  final outDir = Directory('${Directory.current.path}/out')
    ..createSync(recursive: true);

  _mockPathProvider(dbDir);

  // Each variant starts from nothing. rootBundle caches every loadString
  // FUTURE, and DemoGatewayInterceptor reads each fixture through it: a load
  // the previous variant started in its fake-async zone and never finished
  // is awaited forever by the next one (sticks' light frame stayed on its
  // spinner). Also reset GetIt (`await GetIt.I.reset();`) before the SDK
  // registrations below when the harness registers through GetIt.
  rootBundle.clear();

  // TODO(harness) - app-wide state the screen reads before it builds
  // (persisted user, settings, theme mode, brightness seam).
  //   SharedPreferences.setMockInitialValues({});
  //   await tester.runAsync(() async {
  //     await LocalStorage.init();
  //     await LocalStorage.setAppThemeMode(dark);
  //     // Resetting SharedPreferences drops the persisted demo flag, so
  //     // activate the demo session again after it.
  //     await DemoSession.instance.activate();
  //   });
  //   AppStyle.setBrightness(dark ? Brightness.dark : Brightness.light);

  await tester.runAsync(_loadRealFontsOnce);

  // Order matters. Exception stubs go into GetIt FIRST so the SDKs' guarded
  // registrations stand aside; then the SDKs register their own demo
  // implementations; then any device history the demo mode cannot supply.
  registerExceptionStubs();
  await tester.runAsync(registerDemoDependencies);
  await seedDeviceHistory(tester);
  registerScreen();

  tester.view.physicalSize = Size(
    kLogicalWidth * kDevicePixelRatio,
    kProbeHeight * kDevicePixelRatio,
  );
  tester.view.devicePixelRatio = kDevicePixelRatio;
  addTearDown(tester.view.reset);

  final boundaryKey = GlobalKey();
  await tester.pumpWidget(
    RepaintBoundary(
      key: boundaryKey,
      child: buildScreen(dark: dark),
    ),
  );
  await _pumpUntilReady(tester, phase: ' ($name)');

  var measured = _measure(tester, elementSpecs());
  expect(
    measured,
    isNotEmpty,
    reason:
        'no elements matched - check elementSpecs() and the gates in '
        'registerScreen()',
  );

  // Fit the frame to the real content (see _contentHeight). When it does
  // not fit the probe, capture one phone screen and say so.
  final fitted = await _contentHeight(
    tester,
    () => boundaryKey.currentContext!.findRenderObject()!,
  );
  final double targetHeight;
  if (fitted == null) {
    targetHeight = kDeviceHeight;
    // ignore: avoid_print
    print(
      'WARNING: $name is taller than the ${kProbeHeight.toInt()} px probe; '
      'capturing one ${kDeviceHeight.toInt()} px phone screen instead.',
    );
  } else {
    targetHeight = fitted.clamp(400.0, kProbeHeight);
  }

  _setViewHeight(tester, targetHeight);
  await _pumpUntilReady(tester, phase: ' ($name, final height)');
  measured = _measure(tester, elementSpecs());

  final blockGlyphs = _blockGlyphTexts(
    boundaryKey.currentContext!.findRenderObject()!,
  );
  if (blockGlyphs.isNotEmpty) {
    fail(
      '${blockGlyphs.length} text(s) drawn in the FlutterTest block font - '
      'register their family in loadRealFonts(): '
      '${blockGlyphs.take(5).join(' | ')}',
    );
  }

  await tester.runAsync(() async {
    final boundary =
        boundaryKey.currentContext!.findRenderObject() as RenderRepaintBoundary;
    final image = await boundary.toImage(pixelRatio: kDevicePixelRatio);
    final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
    File(
      '${outDir.path}/$name.png',
    ).writeAsBytesSync(bytes!.buffer.asUint8List());

    // Sidecar consumed by scripts/render/compose_strip.py. `number` is a
    // convenience only - the composer re-derives stable global numbers from
    // `key`, so a new element never renumbers the ones already reviewed.
    final sidecar = <String, Object?>{
      'variant': name,
      'logicalWidth': kLogicalWidth,
      'logicalHeight': targetHeight,
      'devicePixelRatio': kDevicePixelRatio,
      // Read by scripts/render/frame_quality.py, which refuses the frame if
      // either count is non-zero.
      'quality': <String, Object?>{
        'spinners': find.byType(CircularProgressIndicator).evaluate().length,
        'blockGlyphTexts': blockGlyphs.length,
      },
      'elements': <Object>[
        for (var i = 0; i < measured.length; i++)
          <String, Object?>{
            'number': i + 1,
            'key': measured[i].key,
            'label': measured[i].label,
            'x': measured[i].rect.left,
            'y': measured[i].rect.top,
            'w': measured[i].rect.width,
            'h': measured[i].rect.height,
          },
      ],
    };
    File(
      '${outDir.path}/$name.json',
    ).writeAsStringSync(const JsonEncoder.withIndent('  ').convert(sidecar));
  });
}

bool _fontsLoaded = false;
Future<void> _loadRealFontsOnce() async {
  if (_fontsLoaded) return;
  await loadRealFonts();
  _fontsLoaded = true;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  // Never let a test reach out for a webfont: the render must be reproducible
  // offline, and a silent fetch failure is a silent Ahem fallback.
  // GoogleFonts.config.allowRuntimeFetching = false;

  final dbDir = Directory.systemTemp.createTempSync('render_harness_db').path;

  // RENDER_SUFFIX distinguishes runs of the SAME harness against different
  // checkouts (e.g. `_draft` for the PR heads, empty for main), so both sets
  // of outputs can sit in one out/ dir and be composed into one page.
  final suffix = Platform.environment['RENDER_SUFFIX'] ?? '';

  // TODO(harness) - rename these to the screen being rendered. Keep BOTH
  // variants: dark and light are reviewed together, and theme bugs only ever
  // show up in the one nobody rendered.
  testWidgets('render <screen> - dark (app default)', (tester) async {
    await renderVariant(
      tester,
      dark: true,
      name: 'screen_dark$suffix',
      dbDir: dbDir,
    );
  });

  testWidgets('render <screen> - light', (tester) async {
    await renderVariant(
      tester,
      dark: false,
      name: 'screen_light$suffix',
      dbDir: dbDir,
    );
  });
}

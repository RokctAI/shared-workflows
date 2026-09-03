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
// DATA COMES FROM THE SDK, NOT FROM HERE. Run with
// `--dart-define=IS_DEMO=true` and call each SDK's own DI registration: the
// SDKs already ship their demo fixtures behind `AppConstants.isDemo` and swap
// them in themselves (DemoLmsRepository, SeededTutorCatalog,
// MockAuthRepository, MockAddressRepository, ...). Naming the screen should
// be nearly the whole job. Hand-written fakes are an EXCEPTION with its own
// marker below - never the default.
//
// The harness renders demo/seed fixtures and should not be wired to a live
// client or backend.
//
// Run:  flutter test --dart-define=IS_DEMO=true test/render/render_screen_test.dart
//       RENDER_SUFFIX=_draft flutter test --dart-define=IS_DEMO=true \
//           test/render/render_screen_test.dart

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

/// TODO(harness) 2/8 - the SDK's own demo data. THIS IS THE MAIN PATH.
///
/// Every SDK already ships its demo fixtures and swaps them in itself behind
/// `AppConstants.isDemo` (`bool.fromEnvironment('IS_DEMO')`). Run the test
/// with `--dart-define=IS_DEMO=true` and just call the DI registrations, in
/// the same order the composed app does: base first, then each feature SDK.
/// You get the SDK's demo repositories - not fakes you wrote and have to keep
/// truthful.
///
///   BaseSdkDependencies.register(GetIt.I);
///   AuthSdkDependencies.register(GetIt.I);   // MockAuthRepository
///   UsersSdkDependencies.register(GetIt.I);  // MockAddressRepository
///   LmsSdkDependencies.register(GetIt.I);    // DemoLmsRepository, SeededTutorCatalog
///
/// Registration is guarded by `isRegistered`, so a host may pre-register its
/// own implementation first and the SDK will leave it alone - which is also
/// how the exception hook below works.
Future<void> registerDemoDependencies() async {
  // assert(AppConstants.isDemo,
  //     'run with --dart-define=IS_DEMO=true, or the SDKs register their real '
  //     'HTTP repositories and the render is of a broken, empty screen');
  // BaseSdkDependencies.register(GetIt.I);
}

/// TODO(harness) 3/8 - EXCEPTION: device history the demo mode cannot supply.
///
/// Leave this EMPTY for most screens. It exists for one real gap: stores that
/// accumulate from a device's own usage - an attendance ledger, a downloads
/// list, a watch history - are written by the app as the user does things, so
/// demo mode alone leaves them empty (e.g. `DemoLmsRepository`'s
/// `recordAttendanceEvent` is a deliberate no-op; the ledger is filled by the
/// schedule as lessons are attended). A widget test never walks that journey.
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
/// Also usually EMPTY. Reach for it only where an SDK has no `isDemo` path for
/// something the screen needs. Pre-register the stub in `GetIt.I` BEFORE
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
/// Return the REAL screen widget, wrapped in whatever the app wraps it in
/// (ProviderScope with the demo overrides, ScreenUtilInit with the app's
/// design size, MaterialApp with the app's theme). Do not substitute a
/// simplified scaffold: the wrapping is part of what is being reviewed.
Widget buildScreen({required bool dark}) {
  // return ProviderScope(
  //   overrides: [profileProvider.overrideWith((ref) => _DemoNotifier())],
  //   child: ScreenUtilInit(
  //     designSize: const Size(375, 812),
  //     builder: (context, child) => MaterialApp(
  //       debugShowCheckedModeBanner: false,
  //       theme: ThemeData(
  //         brightness: dark ? Brightness.dark : Brightness.light,
  //         useMaterial3: false,
  //       ),
  //       home: const YourRealScreen(),
  //     ),
  //   ),
  // );
  throw UnimplementedError('TODO(harness) 6/8: return the real screen widget');
}

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
  await load('Inter',
      weights.values.map((file) => '$root/fonts/$file').toList());

  // Bare TextStyles with no family fall back to the platform default.
  await load('Roboto', ['$root/fonts/Roboto-400.ttf',
    '$root/fonts/Roboto-500.ttf', '$root/fonts/Roboto-700.ttf']);

  // Icon fonts: MaterialIcons ships inside the Flutter SDK cache; package
  // icon fonts (Remix, Cupertino, ...) live in the pub cache and are
  // registered under their package-scoped family name.
  final flutterRoot = Platform.environment['FLUTTER_ROOT'];
  if (flutterRoot != null) {
    await load('MaterialIcons', [
      '$flutterRoot/bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf'
    ]);
  }
  // final pubCache = Platform.environment['PUB_CACHE'] ??
  //     '${Platform.environment['HOME']}/.pub-cache';
  // await load('packages/remixicon/Remix', ['$pubCache/.../fonts/Remix.ttf']);
}

// ===========================================================================
// Below here is the proven mechanism. Leave it alone.
// ===========================================================================

/// One numbered point: a finder, a stable key, and a human label.
class ElementSpec {
  ElementSpec({
    required this.key,
    required this.label,
    required this.finder,
  })  : keyOf = null,
        labelOf = null;

  /// A finder that matches SEVERAL widgets (e.g. every settings row); key and
  /// label are derived per match, so the numbering stays per-row.
  ElementSpec.each({
    required this.keyOf,
    required this.labelOf,
    required this.finder,
  })  : key = '',
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
/// frames so the resulting setStates land.
///
/// `pumpAndSettle` cannot do this: widget-test fake-async never runs the real
/// event loop, so a screen that waits on a real Future settles as empty.
Future<void> _drain(WidgetTester tester, {int rounds = 8}) async {
  for (var i = 0; i < rounds; i++) {
    await tester.runAsync(
        () => Future<void>.delayed(const Duration(milliseconds: 120)));
    await tester.pump(const Duration(milliseconds: 250));
  }
}

List<_Measured> _measure(WidgetTester tester, List<ElementSpec> specs) {
  final measured = <_Measured>[];
  for (final spec in specs) {
    final elements = spec.finder.evaluate().toList();
    for (var i = 0; i < elements.length; i++) {
      try {
        final widget = elements[i].widget;
        measured.add(_Measured(
          spec.keyOf?.call(i, widget) ?? spec.key,
          spec.labelOf?.call(i, widget) ?? spec.label,
          tester.getRect(spec.finder.at(i)),
        ));
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
    final clash = deduped.any((kept) =>
        (kept.rect.top - item.rect.top).abs() < 2 &&
        (kept.rect.height - item.rect.height).abs() < 4);
    if (!clash) deduped.add(item);
  }
  return deduped;
}

/// Renders one variant end to end and writes out/<name>.png + out/<name>.json.
Future<void> renderVariant(
  WidgetTester tester, {
  required bool dark,
  required String name,
  required String dbDir,
}) async {
  final outDir = Directory('${Directory.current.path}/out')
    ..createSync(recursive: true);

  _mockPathProvider(dbDir);

  // TODO(harness) - app-wide state the screen reads before it builds
  // (persisted user, settings, theme mode, brightness seam).
  //   SharedPreferences.setMockInitialValues({});
  //   await tester.runAsync(() async {
  //     await LocalStorage.init();
  //     await LocalStorage.setAppThemeMode(dark);
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

  tester.view.physicalSize =
      Size(kLogicalWidth * kDevicePixelRatio, kProbeHeight * kDevicePixelRatio);
  tester.view.devicePixelRatio = kDevicePixelRatio;
  addTearDown(tester.view.reset);

  final boundaryKey = GlobalKey();
  await tester.pumpWidget(RepaintBoundary(
    key: boundaryKey,
    child: buildScreen(dark: dark),
  ));
  await _drain(tester);

  // Pass 1 measures the real content height in the tall probe viewport; pass 2
  // re-renders at exactly that height so the PNG is a full-length strip with
  // no dead space. Two passes are REQUIRED, not an optimisation: screenutil
  // `.h` sizes scale with the viewport, so the height converges to a fixed
  // point rather than being known up front.
  var measured = _measure(tester, elementSpecs());
  expect(measured, isNotEmpty,
      reason: 'no elements matched - check elementSpecs() and the gates in '
          'registerScreen()');

  final contentBottom =
      measured.map((m) => m.rect.bottom).reduce((a, b) => a > b ? a : b);
  final targetHeight =
      (contentBottom + kBottomPadding).clamp(400.0, kProbeHeight);

  tester.view.physicalSize =
      Size(kLogicalWidth * kDevicePixelRatio, targetHeight * kDevicePixelRatio);
  await tester.pump(const Duration(milliseconds: 50));
  await _drain(tester, rounds: 4);
  measured = _measure(tester, elementSpecs());

  await tester.runAsync(() async {
    final boundary =
        boundaryKey.currentContext!.findRenderObject() as RenderRepaintBoundary;
    final image = await boundary.toImage(pixelRatio: kDevicePixelRatio);
    final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
    File('${outDir.path}/$name.png')
        .writeAsBytesSync(bytes!.buffer.asUint8List());

    // Sidecar consumed by scripts/render/compose_strip.py. `number` is a
    // convenience only - the composer re-derives stable global numbers from
    // `key`, so a new element never renumbers the ones already reviewed.
    final sidecar = <String, Object?>{
      'variant': name,
      'logicalWidth': kLogicalWidth,
      'logicalHeight': targetHeight,
      'devicePixelRatio': kDevicePixelRatio,
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
          }
      ],
    };
    File('${outDir.path}/$name.json')
        .writeAsStringSync(const JsonEncoder.withIndent('  ').convert(sidecar));
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
    await renderVariant(tester,
        dark: true, name: 'screen_dark$suffix', dbDir: dbDir);
  });

  testWidgets('render <screen> - light', (tester) async {
    await renderVariant(tester,
        dark: false, name: 'screen_light$suffix', dbDir: dbDir);
  });
}

// Copyright (c) 2026 RokctAI
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

// TEMPLATE (templates/tour-app/ in RokctAI/shared-workflows): copy to the
// app repo as integration_test/guided_tour_test.dart and replace the ONE
// `{app_package}` token below with the app's pubspec package name (e.g.
// supacharge). The file does not compile until that token is substituted;
// nothing else in it is app-specific.
//
// Guided-tour runner for the demo build (--dart-define=IS_DEMO=true).
//
// Steps come from tour_steps.g.dart, which CI regenerates from
// tour/app.tour.yaml plus the tour fragments shipped by the composed SDKs
// (see RokctAI/shared-workflows scripts/tour/README.md). Per step the runner
// performs the step's action, lets the screen settle, emits a
// `TOUR_SHOT:<key>` marker and holds the frame still - the host-side
// capture script answers each marker with `adb exec-out screencap -p`.
//
// Marker transport (learned the hard way on runs 32386564857/32456359666):
// under `flutter test`, Dart prints are captured by the test harness and
// forwarded to the HOST console - they never reach the device's logcat. So
// every marker is emitted twice: `debugPrint` for the host-side test output
// (which CI also tails) and `/system/bin/log` for logcat.
//
// Frame pumping: the runner deliberately never calls `tester.pump*`. In
// integration mode the real app drives its own frames, and a live-binding
// `pump` can block indefinitely when the device is under heavy load (both
// wedged CI runs stalled before the first marker with the app healthy and
// rendering). Pure wall-clock waits cannot wedge.
//
// This file only imports stable entrypoints: `package:<app_package>/main.dart`
// exists in every composition (lib/ is composed at CI time from base_sdk's
// templates) and the generated steps file is committed alongside this
// runner.

import 'dart:async';
import 'dart:io';

import 'package:auto_route/auto_route.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

// PLACEHOLDER: replace {app_package} with the app's pubspec package name.
import 'package:{app_package}/main.dart' as app;

import 'tour_steps.g.dart';

void main() {
  final IntegrationTestWidgetsFlutterBinding binding =
      IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  // The live binding's default framePolicy (fadePointers) only builds and
  // paints frames during tester.pump calls - with the no-pump runner that
  // left runApp's widget tree unbuilt and the device stuck on the harness
  // placeholder screen, so run 32486179337 captured ten identical "Test
  // starting..." stills. fullyLive lets the engine's own vsync drive
  // building and painting, which is exactly what a self-running app under
  // wall-clock observation needs.
  binding.framePolicy = LiveTestWidgetsFlutterBindingFramePolicy.fullyLive;

  testWidgets(
    'guided tour',
    (WidgetTester tester) async {
      // Hard watchdog on real timers: whatever wedges inside the tour, the
      // test fails in bounded time so `flutter test` exits and the CI retry
      // leg (fresh AVD) gets its chance instead of burning the job timeout.
      await _runTour(tester).timeout(
        const Duration(minutes: 25),
        onTimeout: () async {
          await _mark('TOUR_ACTION_ERROR:watchdog:tour exceeded 25 minutes');
          throw TimeoutException('guided tour watchdog fired after 25 minutes');
        },
      );
    },
    timeout: const Timeout(Duration(minutes: 30)),
  );
}

Future<void> _runTour(WidgetTester tester) async {
  await _mark('TOUR_ALIVE:test-started');

  try {
    await tourSetup().timeout(const Duration(minutes: 2));
    await _mark('TOUR_ALIVE:setup-done');
  } catch (error) {
    await _mark('TOUR_ACTION_ERROR:setup:${_oneLine(error)}');
  }

  app.main();
  await _mark('TOUR_ALIVE:app-launched');
  // Wait for the app's widget tree to actually attach and build (bounded;
  // finders scan the tree passively, so this cannot wedge). On run
  // 32486179337 every step failed with "Bad state: No element" because
  // the tree never built under the old framePolicy - this both fixes the
  // wait and leaves a breadcrumb if it ever regresses.
  final DateTime navDeadline = DateTime.now().add(const Duration(seconds: 60));
  while (find.byType(Navigator).evaluate().isEmpty &&
      DateTime.now().isBefore(navDeadline)) {
    await Future<void>.delayed(const Duration(milliseconds: 500));
  }
  if (find.byType(Navigator).evaluate().isEmpty) {
    await _mark('TOUR_ACTION_ERROR:navigator:no Navigator after 60s');
  } else {
    await _mark('TOUR_ALIVE:navigator-found');
  }
  // Let the splash flow (backend status, translations, auth check) play
  // out before the first step runs. The app renders on its own; this is a
  // plain wall-clock pause.
  await _settle(10000);
  await _mark('TOUR_ALIVE:initial-settle-done');

  for (final TourStep step in tourSteps) {
    try {
      await step
          .action(tester, _rootRouter(tester))
          .timeout(const Duration(seconds: 90));
    } catch (error) {
      // A single broken step must not sink the whole tour - the marker
      // is reported so CI can annotate it, and the run moves on.
      await _mark('TOUR_ACTION_ERROR:${step.key}:${_oneLine(error)}');
    }
    await _settle(step.settleMs);
    if (step.screenshot) {
      await _mark('TOUR_SHOT:${step.key}');
      // Hold the frame still so the host screencap catches a stable
      // screen (the capture script answers the marker within this
      // window).
      await _hold(3500);
      await _mark('TOUR_STEP_DONE:${step.key}');
    }
  }

  await _mark('TOUR_COMPLETE:${tourSteps.length}');
}

/// The root router, resolved from the root navigator's context. Works from
/// any screen because every page sits under the root RouterScope.
StackRouter _rootRouter(WidgetTester tester) {
  final Element element = tester.element(find.byType(Navigator).first);
  return AutoRouter.of(element);
}

/// Emits a tour marker on both transports: `debugPrint` reaches the host
/// `flutter test` console, and `/system/bin/log` writes the line to the
/// device's logcat for the CI capture watcher. The `log` call is
/// best-effort - if the exec is unavailable the host-side line still tells
/// CI what happened.
Future<void> _mark(String message) async {
  debugPrint(message);
  try {
    await Process.run('log', <String>['-t', 'TOUR', message])
        .timeout(const Duration(seconds: 10));
  } catch (_) {
    // Best-effort; never let marker plumbing break the tour.
  }
}

/// First line of an error, so markers stay single-line for the log parsers.
String _oneLine(Object error) {
  final String text = '$error'.split('\n').first.trim();
  return text.length > 300 ? text.substring(0, 300) : text;
}

/// Real wall-clock settle. The app schedules its own frames in integration
/// mode, so no pumping is needed (or wanted - see the header comment).
Future<void> _settle(int ms) async {
  final DateTime end = DateTime.now().add(Duration(milliseconds: ms));
  while (DateTime.now().isBefore(end)) {
    await Future<void>.delayed(const Duration(milliseconds: 100));
  }
}

/// Real wall-clock pause that leaves the last rendered frame on screen.
Future<void> _hold(int ms) async {
  final DateTime end = DateTime.now().add(Duration(milliseconds: ms));
  while (DateTime.now().isBefore(end)) {
    await Future<void>.delayed(const Duration(milliseconds: 100));
  }
}

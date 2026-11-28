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
//
// Drop-in for the shared-workflows render harness (templates/render-harness).
// Call `await loadPackageFonts();` at the end of loadRealFonts().
//
// Why: the harness template only loads MaterialIcons and leaves package icon
// fonts (Remix, Cupertino, Phosphor, ...) as a commented-out TODO. Any icon
// from a package then draws as a small empty square. This reads every package
// the app depends on (.dart_tool/package_config.json), finds each one's
// declared `flutter: fonts:` in its pubspec, and registers each family under
// the name Flutter really asks for: `packages/<package>/<family>` (and the
// bare family for the app's own pubspec).
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/services.dart';

Future<List<String>> loadPackageFonts({String? appRoot}) async {
  final root = appRoot ?? Directory.current.path;
  final cfgFile = File('$root/.dart_tool/package_config.json');
  if (!cfgFile.existsSync()) {
    throw StateError('No package_config.json under $root - run pub get first.');
  }
  final cfg = jsonDecode(cfgFile.readAsStringSync()) as Map<String, dynamic>;
  final cfgDir = cfgFile.parent.uri;
  final loaded = <String>[];
  for (final pkg in (cfg['packages'] as List).cast<Map<String, dynamic>>()) {
    final name = pkg['name'] as String;
    final pkgDir = Directory.fromUri(cfgDir.resolve(pkg['rootUri'] as String));
    final pubspec = File('${pkgDir.path}/pubspec.yaml');
    if (!pubspec.existsSync()) continue;
    final isApp = pkgDir.absolute.path.replaceAll(RegExp(r'/$'), '') ==
        Directory(root).absolute.path.replaceAll(RegExp(r'/$'), '');
    for (final fam in _fontsIn(pubspec.readAsLinesSync())) {
      final files = [
        for (final a in fam.assets) File('${pkgDir.path}/$a'),
      ].where((f) => f.existsSync()).toList();
      if (files.isEmpty) continue;
      final family = isApp ? fam.family : 'packages/$name/${fam.family}';
      final loader = FontLoader(family);
      for (final f in files) {
        loader.addFont(Future.value(ByteData.view(
            Uint8List.fromList(f.readAsBytesSync()).buffer)));
      }
      await loader.load();
      loaded.add(family);
    }
  }
  return loaded;
}

class _Fam {
  _Fam(this.family);
  final String family;
  final assets = <String>[];
}

/// Tiny reader for the `flutter: fonts:` block (no yaml dependency needed).
List<_Fam> _fontsIn(List<String> lines) {
  final out = <_Fam>[];
  var inFlutter = false, inFonts = false;
  for (final raw in lines) {
    final line = raw.replaceAll(RegExp(r'\s+#.*$'), '');
    if (line.trim().isEmpty) continue;
    final indent = line.length - line.trimLeft().length;
    final t = line.trim();
    if (indent == 0) {
      inFlutter = t == 'flutter:';
      inFonts = false;
      continue;
    }
    if (!inFlutter) continue;
    if (indent <= 2 && t.endsWith(':') && !t.startsWith('-')) {
      inFonts = t == 'fonts:';
      continue;
    }
    if (!inFonts) continue;
    final fm = RegExp(r'^-\s*family:\s*(.+)$').firstMatch(t);
    if (fm != null) {
      out.add(_Fam(fm.group(1)!.trim().replaceAll(RegExp('["\']'), '')));
      continue;
    }
    final am = RegExp(r'^-?\s*asset:\s*(.+)$').firstMatch(t);
    if (am != null && out.isNotEmpty) {
      out.last.assets.add(am.group(1)!.trim().replaceAll(RegExp('["\']'), ''));
    }
  }
  return out;
}

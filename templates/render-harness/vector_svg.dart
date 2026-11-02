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

// EXPERIMENTAL - true vector SVG export of a rendered screen.
//
// The PNG frame is a bitmap; this writes the SAME paint as an SVG of real
// shapes and real text, so a marketing page can scale it without blur and
// copy its words. It is not wired into CI.
//
// How: the render tree is painted a second time into a recording
// PaintingContext whose canvas writes SVG instead of pixels. Every layer push
// (clip, transform, opacity) is turned back into its canvas form, so nothing
// is composited. Shapes become <rect>, <circle>, <path>; a RenderParagraph
// becomes <text> with one x position per character taken from Flutter's own
// layout, in the same font files the harness loaded (embedded as
// @font-face). Anything the SVG cannot express - a gradient shader, a
// colour filter, text with inline widgets, vertices - is drawn by the real
// engine into a small bitmap and placed as an <image>, so the SVG is never
// missing a part of the screen. `VectorSvgRecorder.rasterFallbacks` counts
// them.
//
// Known gaps: ui.Path is opaque, so paths are re-sampled from their contour
// metrics (0.5 px steps, simplified) rather than copied curve-for-curve;
// a TextOverflow.ellipsis "..." glyph is not drawn; blend modes other than
// srcOver are ignored.
//
// Use (after the PNG capture, so the live tree is not disturbed first):
//
//   final rec = VectorSvgRecorder(devicePixelRatio: 3);
//   rec.paint(boundary);                       // synchronous
//   final svg = await tester.runAsync(rec.finish);  // images, fonts

import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/rendering.dart';

/// The font files the harness registered, so the SVG can embed the same
/// faces. Call [register] from loadRealFonts' `load` and [scanDirectory] on
/// any directory of fonts registered some other way (google_fonts).
class VectorSvgFonts {
  static final Map<String, List<File>> _byFamily = <String, List<File>>{};
  static final List<File> _scanned = <File>[];

  static void register(String family, List<File> files) {
    (_byFamily[family] ??= <File>[]).addAll(files);
  }

  static void scanDirectory(Directory dir) {
    if (!dir.existsSync()) return;
    _scanned.addAll(
      dir.listSync().whereType<File>().where(
        (f) => f.path.endsWith('.ttf') || f.path.endsWith('.otf'),
      ),
    );
  }

  static final Map<String, _FaceInfo?> _info = <String, _FaceInfo?>{};

  static _FaceInfo? _read(File file) =>
      _info.putIfAbsent(file.path, () => _FaceInfo.read(file));

  /// Best file for a face, or null when none is known.
  static File? find(
    String flutterFamily,
    String cssFamily,
    int weight,
    bool italic,
  ) {
    final candidates = <File>[
      ...?_byFamily[flutterFamily],
      if (_byFamily[flutterFamily] == null)
        ..._byFamily.entries
            .where((e) => _cssFamily(e.key) == cssFamily)
            .expand((e) => e.value),
      ..._scanned.where((f) => _read(f)?.family == cssFamily),
    ];
    File? best;
    var bestScore = 1 << 30;
    for (final file in candidates) {
      final info = _read(file);
      if (info == null) continue;
      final score =
          (info.weight - weight).abs() + (info.italic == italic ? 0 : 1000);
      if (score < bestScore) {
        best = file;
        bestScore = score;
      }
    }
    return best;
  }
}

/// Family, weight and italic flag read from a TrueType/OpenType file.
class _FaceInfo {
  _FaceInfo(this.family, this.weight, this.italic, this.otf);

  final String family;
  final int weight;
  final bool italic;
  final bool otf;

  static _FaceInfo? read(File file) {
    try {
      final bytes = file.readAsBytesSync();
      final data = ByteData.sublistView(bytes);
      final tables = <String, int>{};
      final count = data.getUint16(4);
      for (var i = 0; i < count; i++) {
        final rec = 12 + i * 16;
        final tag = String.fromCharCodes(bytes.sublist(rec, rec + 4));
        tables[tag] = data.getUint32(rec + 8);
      }
      var weight = 400;
      var italic = false;
      final os2 = tables['OS/2'];
      if (os2 != null) {
        weight = data.getUint16(os2 + 4);
        italic = data.getUint16(os2 + 62) & 1 == 1;
      }
      String? family;
      String? typographic;
      final name = tables['name'];
      if (name != null) {
        final n = data.getUint16(name + 2);
        final strings = name + data.getUint16(name + 4);
        for (var i = 0; i < n; i++) {
          final rec = name + 6 + i * 12;
          final platform = data.getUint16(rec);
          final id = data.getUint16(rec + 6);
          if (platform != 3 || (id != 1 && id != 16)) continue;
          final len = data.getUint16(rec + 8);
          final off = strings + data.getUint16(rec + 10);
          final units = <int>[
            for (var j = 0; j < len; j += 2) data.getUint16(off + j),
          ];
          final value = String.fromCharCodes(units);
          if (id == 16) {
            typographic = value;
          } else {
            family = value;
          }
        }
      }
      final otf = String.fromCharCodes(bytes.sublist(0, 4)) == 'OTTO';
      return _FaceInfo(typographic ?? family ?? '', weight, italic, otf);
    } catch (_) {
      return null;
    }
  }
}

/// CSS family for a Flutter family: `packages/agent_sdk/Nunito` -> `Nunito`,
/// google_fonts' `Inter_700` -> `Inter`.
String _cssFamily(String flutterFamily) {
  var family = flutterFamily;
  if (family.startsWith('packages/')) {
    family = family.split('/').skip(2).join('/');
  }
  final variant = RegExp(r'_(regular|italic|\d{3}(italic)?)$');
  return family.replaceFirst(variant, '');
}

String _n(double v) {
  if (v.isNaN || v.isInfinite) return '0';
  final s = v.toStringAsFixed(2);
  if (!s.contains('.')) return s;
  final trimmed = s.replaceFirst(RegExp(r'\.?0+$'), '');
  return trimmed == '-0' ? '0' : trimmed;
}

String _n4(double v) =>
    v.toStringAsFixed(4).replaceFirst(RegExp(r'\.?0+$'), '');

String _esc(String s) => s
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');

String _hex(Color c) {
  final argb = c.toARGB32();
  return '#${(argb & 0xFFFFFF).toRadixString(16).padLeft(6, '0')}';
}

double _alpha(Color c) => ((c.toARGB32() >> 24) & 0xFF) / 255.0;

/// A group in the output tree.
class _Group {
  _Group(this.open, this.close);

  final String open;
  final String close;
  final List<Object> kids = <Object>[];
}

/// A clip wrapper: consecutive elements under the same clip share one.
class _ClipGroup extends _Group {
  _ClipGroup(this.clipId) : super('<g clip-path="url(#$clipId)">', '</g>');

  final String clipId;
}

/// An `<image>` whose PNG is encoded asynchronously in [VectorSvgRecorder.finish].
class _Deferred {
  _Deferred(this.encode);

  final Future<String> Function() encode;
  String? value;
}

class _State {
  _State(this.ctm, this.clip, {this.layer = false});

  final Matrix4 ctm;
  final String? clip;
  final bool layer;
}

/// Records a render tree's paint as SVG. See the file comment.
class VectorSvgRecorder implements Canvas {
  VectorSvgRecorder({this.devicePixelRatio = 3.0});

  final double devicePixelRatio;

  /// Draw calls drawn as embedded bitmaps because SVG cannot express them.
  int rasterFallbacks = 0;

  /// Texts written as real `<text>`.
  int vectorTexts = 0;

  final List<String> warnings = <String>[];

  late Size _size;
  final _Group _root = _Group('', '');
  late List<_Group> _groups = <_Group>[_root];
  final List<String> _defs = <String>[];
  final Map<String, String> _filters = <String, String>{};
  var _ids = 0;
  late List<_State> _stack = <_State>[_State(Matrix4.identity(), null)];
  final List<(RenderParagraph, Offset)> _paragraphs =
      <(RenderParagraph, Offset)>[];
  final Map<String, ({String flutter, int weight, bool italic})> _faces =
      <String, ({String flutter, int weight, bool italic})>{};

  _State get _top => _stack.last;

  /// Paints [root] (normally the capture RepaintBoundary) into the recorder.
  void paint(RenderObject root) {
    final box = root as RenderBox;
    _size = box.size;
    _groups = <_Group>[_root];
    _stack = <_State>[_State(Matrix4.identity(), null)];
    final context = _SvgPaintingContext(this, Offset.zero & _size);
    root.paint(context, Offset.zero);
  }

  /// Encodes the images, embeds the fonts and returns the SVG document.
  Future<String> finish() async {
    final deferred = <_Deferred>[];
    void collect(_Group g) {
      for (final kid in g.kids) {
        if (kid is _Deferred) deferred.add(kid);
        if (kid is _Group) collect(kid);
      }
    }

    collect(_root);
    for (final d in deferred) {
      d.value = await d.encode();
    }

    final fonts = StringBuffer();
    for (final entry in _faces.entries) {
      final css = entry.key.split('|').first;
      final face = entry.value;
      final file = VectorSvgFonts.find(
        face.flutter,
        css,
        face.weight,
        face.italic,
      );
      if (file == null) {
        warnings.add(
          'no font file for $css ${face.weight}'
          '${face.italic ? ' italic' : ''} - the SVG falls back to a '
          'system face for it',
        );
        continue;
      }
      final info = VectorSvgFonts._read(file);
      final mime = info?.otf == true ? 'font/otf' : 'font/ttf';
      final format = info?.otf == true ? 'opentype' : 'truetype';
      fonts.write(
        "@font-face{font-family:'$css';"
        'font-weight:${face.weight};'
        'font-style:${face.italic ? 'italic' : 'normal'};'
        'src:url(data:$mime;base64,${base64Encode(file.readAsBytesSync())})'
        " format('$format');}",
      );
    }

    final out = StringBuffer()
      ..write(
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" '
        'width="${_n(_size.width)}" height="${_n(_size.height)}" '
        'viewBox="0 0 ${_n(_size.width)} ${_n(_size.height)}">\n',
      );
    out.write(
      '<!-- Vector render of the real Flutter screen '
      '(experimental): $vectorTexts text runs as <text>, '
      '$rasterFallbacks bitmap fallback(s). -->\n',
    );
    if (fonts.isNotEmpty) out.write('<style>$fonts</style>\n');
    if (_defs.isNotEmpty || _filters.isNotEmpty) {
      out.write('<defs>\n');
      for (final d in _defs) {
        out.write('$d\n');
      }
      for (final f in _filters.values) {
        out.write('$f\n');
      }
      out.write('</defs>\n');
    }
    void write(_Group g) {
      for (final kid in g.kids) {
        if (kid is String) {
          out.write('$kid\n');
        } else if (kid is _Deferred) {
          out.write('${kid.value}\n');
        } else if (kid is _Group) {
          out.write('${kid.open}\n');
          write(kid);
          out.write('${kid.close}\n');
        }
      }
    }

    write(_root);
    out.write('</svg>\n');
    return out.toString();
  }

  // -------------------------------------------------------------------------
  // Output helpers
  // -------------------------------------------------------------------------

  String _transformAttr(Matrix4 m) {
    final s = m.storage;
    final identity =
        s[0] == 1 &&
        s[1] == 0 &&
        s[4] == 0 &&
        s[5] == 1 &&
        s[12] == 0 &&
        s[13] == 0;
    if (identity) return '';
    if (s[0] == 1 && s[1] == 0 && s[4] == 0 && s[5] == 1) {
      return ' transform="translate(${_n(s[12])} ${_n(s[13])})"';
    }
    String f(double v) => v.toStringAsFixed(4);
    return ' transform="matrix(${f(s[0])} ${f(s[1])} ${f(s[4])} '
        '${f(s[5])} ${_n(s[12])} ${_n(s[13])})"';
  }

  /// Adds an element (already carrying its own transform) under the clip.
  void _emit(Object element) {
    final group = _groups.last;
    final clip = _top.clip;
    if (clip == null) {
      group.kids.add(element);
      return;
    }
    final last = group.kids.isEmpty ? null : group.kids.last;
    if (last is _ClipGroup && last.clipId == clip) {
      last.kids.add(element);
    } else {
      group.kids.add(_ClipGroup(clip)..kids.add(element));
    }
  }

  void _shape(String tag, Paint paint, {String extra = ''}) {
    if (paint.shader != null ||
        paint.colorFilter != null ||
        paint.imageFilter != null) {
      return; // caller checks _needsRaster first
    }
    final buf = StringBuffer('<$tag$extra${_transformAttr(_top.ctm)}');
    final c = paint.color;
    final a = _alpha(c);
    if (paint.style == PaintingStyle.stroke) {
      final w = paint.strokeWidth == 0
          ? 1 / devicePixelRatio
          : paint.strokeWidth;
      buf.write(' fill="none" stroke="${_hex(c)}" stroke-width="${_n(w)}"');
      if (a < 1) buf.write(' stroke-opacity="${_n(a)}"');
      if (paint.strokeCap != StrokeCap.butt) {
        buf.write(' stroke-linecap="${paint.strokeCap.name}"');
      }
      if (paint.strokeJoin != StrokeJoin.miter) {
        buf.write(' stroke-linejoin="${paint.strokeJoin.name}"');
      } else if (paint.strokeMiterLimit != 4) {
        buf.write(' stroke-miterlimit="${_n(paint.strokeMiterLimit)}"');
      }
    } else {
      buf.write(' fill="${_hex(c)}"');
      if (a < 1) buf.write(' fill-opacity="${_n(a)}"');
    }
    final blur = _blurFilter(paint.maskFilter);
    if (blur != null) buf.write(' filter="url(#$blur)"');
    buf.write('/>');
    _emit(buf.toString());
  }

  /// MaskFilter is opaque; its toString is `MaskFilter.blur(BlurStyle.x, s)`.
  String? _blurFilter(MaskFilter? filter) {
    if (filter == null) return null;
    final m = RegExp(
      r'blur\((?:BlurStyle\.)?(\w+), ([\d.]+)',
    ).firstMatch(filter.toString());
    if (m == null) return null;
    final sigma = double.parse(m.group(2)!);
    final key = _n(sigma);
    return _filters
        .putIfAbsent(key, () {
          return '<filter id="b${key.replaceAll('.', '_')}" x="-50%" y="-50%" '
              'width="200%" height="200%"><feGaussianBlur stdDeviation="$key"/>'
              '</filter>';
        })
        .split('"')[1];
  }

  bool _needsRaster(Paint paint) =>
      paint.shader != null ||
      paint.colorFilter != null ||
      paint.imageFilter != null;

  /// Draws [draw] with the real engine into a bitmap covering [local] and
  /// places it as an `<image>`. The fallback for anything SVG cannot express.
  void _raster(Rect local, void Function(Canvas canvas) draw) {
    rasterFallbacks++;
    final ctm = _top.ctm.clone();
    final device = MatrixUtils.transformRect(
      ctm,
      local,
    ).inflate(2).intersect(Offset.zero & _size);
    if (device.isEmpty || device.width <= 0 || device.height <= 0) return;
    final rect = Rect.fromLTRB(
      device.left.floorToDouble(),
      device.top.floorToDouble(),
      device.right.ceilToDouble(),
      device.bottom.ceilToDouble(),
    );
    final recorder = ui.PictureRecorder();
    final canvas = Canvas(recorder);
    canvas.scale(devicePixelRatio);
    canvas.translate(-rect.left, -rect.top);
    canvas.transform(ctm.storage);
    draw(canvas);
    final picture = recorder.endRecording();
    final dpr = devicePixelRatio;
    _emit(
      _Deferred(() async {
        final image = await picture.toImage(
          (rect.width * dpr).ceil(),
          (rect.height * dpr).ceil(),
        );
        final png = await image.toByteData(format: ui.ImageByteFormat.png);
        image.dispose();
        picture.dispose();
        return '<image x="${_n(rect.left)}" y="${_n(rect.top)}" '
            'width="${_n(rect.width)}" height="${_n(rect.height)}" '
            'preserveAspectRatio="none" xlink:href="data:image/png;base64,'
            '${base64Encode(png!.buffer.asUint8List())}"/>';
      }),
    );
  }

  String _rrectPath(RRect rrect) {
    // Radii larger than the box are scaled down the way Skia does (a 999 px
    // "stadium" radius is a pill, not an ellipse).
    final r = rrect.scaleRadii();
    final b = StringBuffer()
      ..write('M${_n(r.left + r.tlRadiusX)} ${_n(r.top)}')
      ..write('H${_n(r.right - r.trRadiusX)}');
    if (r.trRadiusX > 0 || r.trRadiusY > 0) {
      b.write(
        'A${_n(r.trRadiusX)} ${_n(r.trRadiusY)} 0 0 1 '
        '${_n(r.right)} ${_n(r.top + r.trRadiusY)}',
      );
    }
    b.write('V${_n(r.bottom - r.brRadiusY)}');
    if (r.brRadiusX > 0 || r.brRadiusY > 0) {
      b.write(
        'A${_n(r.brRadiusX)} ${_n(r.brRadiusY)} 0 0 1 '
        '${_n(r.right - r.brRadiusX)} ${_n(r.bottom)}',
      );
    }
    b.write('H${_n(r.left + r.blRadiusX)}');
    if (r.blRadiusX > 0 || r.blRadiusY > 0) {
      b.write(
        'A${_n(r.blRadiusX)} ${_n(r.blRadiusY)} 0 0 1 '
        '${_n(r.left)} ${_n(r.bottom - r.blRadiusY)}',
      );
    }
    b.write('V${_n(r.top + r.tlRadiusY)}');
    if (r.tlRadiusX > 0 || r.tlRadiusY > 0) {
      b.write(
        'A${_n(r.tlRadiusX)} ${_n(r.tlRadiusY)} 0 0 1 '
        '${_n(r.left + r.tlRadiusX)} ${_n(r.top)}',
      );
    }
    b.write('Z');
    return b.toString();
  }

  String _rrectElement(RRect rrect) {
    final r = rrect.scaleRadii();
    final uniform =
        r.tlRadius == r.trRadius &&
        r.tlRadius == r.brRadius &&
        r.tlRadius == r.blRadius;
    if (uniform) {
      final rx = r.tlRadiusX;
      final ry = r.tlRadiusY;
      return 'rect x="${_n(r.left)}" y="${_n(r.top)}" '
          'width="${_n(r.width)}" height="${_n(r.height)}"'
          '${rx > 0 ? ' rx="${_n(rx)}" ry="${_n(ry)}"' : ''}';
    }
    return 'path d="${_rrectPath(r)}"';
  }

  /// SVG path data for an opaque ui.Path, re-sampled from its contours.
  String _pathData(Path path) {
    final b = StringBuffer();
    for (final metric in path.computeMetrics()) {
      final length = metric.length;
      if (length <= 0) continue;
      final steps = math.max(2, (length / 0.5).ceil());
      final points = <Offset>[
        for (var i = 0; i <= steps; i++)
          metric.getTangentForOffset(length * i / steps)!.position,
      ];
      final simple = _simplify(points, 0.04);
      b.write('M${_n(simple.first.dx)} ${_n(simple.first.dy)}');
      for (final p in simple.skip(1)) {
        b.write('L${_n(p.dx)} ${_n(p.dy)}');
      }
      if (metric.isClosed) b.write('Z');
    }
    return b.toString();
  }

  /// Douglas-Peucker polyline simplification.
  static List<Offset> _simplify(List<Offset> pts, double tolerance) {
    if (pts.length < 3) return pts;
    final keep = List<bool>.filled(pts.length, false);
    keep[0] = keep[pts.length - 1] = true;
    final stack = <(int, int)>[(0, pts.length - 1)];
    while (stack.isNotEmpty) {
      final (a, b) = stack.removeLast();
      var maxD = 0.0;
      var index = -1;
      final p = pts[a], q = pts[b];
      final dx = q.dx - p.dx, dy = q.dy - p.dy;
      final len = math.sqrt(dx * dx + dy * dy);
      for (var i = a + 1; i < b; i++) {
        final r = pts[i];
        final d = len == 0
            ? (r - p).distance
            : ((r.dx - p.dx) * dy - (r.dy - p.dy) * dx).abs() / len;
        if (d > maxD) {
          maxD = d;
          index = i;
        }
      }
      if (maxD > tolerance && index > 0) {
        keep[index] = true;
        stack
          ..add((a, index))
          ..add((index, b));
      }
    }
    return <Offset>[
      for (var i = 0; i < pts.length; i++)
        if (keep[i]) pts[i],
    ];
  }

  String _fillRule(Path path) =>
      path.fillType == PathFillType.evenOdd ? ' fill-rule="evenodd"' : '';

  // -------------------------------------------------------------------------
  // Text
  // -------------------------------------------------------------------------

  void _pushParagraph(RenderParagraph p, Offset offset) =>
      _paragraphs.add((p, offset));

  void _popParagraph() => _paragraphs.removeLast();

  bool _hasPlaceholder(InlineSpan span) {
    var found = false;
    span.visitChildren((s) {
      if (s is PlaceholderSpan) found = true;
      return !found;
    });
    return found;
  }

  /// Writes a RenderParagraph as `<text>` runs, one x per character.
  bool _emitParagraph(RenderParagraph rp, Offset offset) {
    final span = rp.text;
    if (_hasPlaceholder(span)) return false;
    final tp = TextPainter(
      text: span,
      textAlign: rp.textAlign,
      textDirection: rp.textDirection,
      textScaler: rp.textScaler,
      maxLines: rp.maxLines,
      ellipsis: rp.overflow == TextOverflow.ellipsis ? '…' : null,
      locale: rp.locale,
      strutStyle: rp.strutStyle,
      textWidthBasis: rp.textWidthBasis,
      textHeightBehavior: rp.textHeightBehavior,
    );
    final constraints = rp.constraints;
    final wraps = rp.softWrap || rp.overflow == TextOverflow.ellipsis;
    tp.layout(
      minWidth: constraints.minWidth,
      maxWidth: wraps ? constraints.maxWidth : double.infinity,
    );

    // Effective style per UTF-16 range.
    final runs = <(int, int, TextStyle)>[];
    var cursor = 0;
    void walk(InlineSpan s, TextStyle? parent) {
      final style = parent == null
          ? (s.style ?? const TextStyle())
          : parent.merge(s.style);
      if (s is TextSpan) {
        final t = s.text ?? '';
        if (t.isNotEmpty) runs.add((cursor, cursor + t.length, style));
        cursor += t.length;
        for (final child in s.children ?? const <InlineSpan>[]) {
          walk(child, style);
        }
      }
    }

    walk(span, null);
    final text = span.toPlainText(includePlaceholders: false);
    final lines = tp.computeLineMetrics();

    for (final (start, end, style) in runs) {
      final color =
          style.foreground?.color ?? style.color ?? const Color(0xFF000000);
      final flutterFamily = style.fontFamily ?? 'Roboto';
      final css = _cssFamily(flutterFamily);
      final weight = style.fontWeight?.value ?? 400;
      final italic = style.fontStyle == FontStyle.italic;
      _faces['$css|$weight|$italic'] = (
        flutter: flutterFamily,
        weight: weight,
        italic: italic,
      );
      final size = rp.textScaler.scale(style.fontSize ?? 14.0);

      // Group the run's characters by line.
      final byLine = <int, (List<String>, List<double>)>{};
      var i = start;
      while (i < end) {
        final unit = text.codeUnitAt(i);
        final len = (unit >= 0xD800 && unit <= 0xDBFF && i + 1 < end) ? 2 : 1;
        final ch = text.substring(i, i + len);
        final boxes = tp.getBoxesForSelection(
          TextSelection(baseOffset: i, extentOffset: i + len),
        );
        i += len;
        if (boxes.isEmpty || ch == '\n') continue;
        final box = boxes.first;
        final mid = (box.top + box.bottom) / 2;
        var line = 0;
        var best = double.infinity;
        for (var l = 0; l < lines.length; l++) {
          final m = lines[l];
          final d = (mid - (m.baseline - (m.ascent - m.descent) / 2)).abs();
          if (d < best) {
            best = d;
            line = l;
          }
        }
        final entry = byLine.putIfAbsent(line, () => (<String>[], <double>[]));
        entry.$1.add(ch);
        entry.$2.add(offset.dx + box.left);
      }

      for (final MapEntry(key: line, value: (chars, xs)) in byLine.entries) {
        if (chars.every((c) => c.trim().isEmpty)) continue;
        final baseline = offset.dy + lines[line].baseline;
        final a = _alpha(color);
        final buf = StringBuffer(
          '<text xml:space="preserve" '
          'x="${xs.map(_n).join(' ')}" y="${_n(baseline)}" '
          "font-family=\"'${_esc(css)}'\" font-size=\"${_n(size)}\"",
        );
        if (weight != 400) buf.write(' font-weight="$weight"');
        if (italic) buf.write(' font-style="italic"');
        buf.write(' fill="${_hex(color)}"');
        if (a < 1) buf.write(' fill-opacity="${_n(a)}"');
        buf.write('${_transformAttr(_top.ctm)}>${_esc(chars.join())}</text>');
        _emit(buf.toString());
        vectorTexts++;
      }
    }
    tp.dispose();
    return true;
  }

  // -------------------------------------------------------------------------
  // Canvas: state
  // -------------------------------------------------------------------------

  @override
  void save() => _stack.add(_State(_top.ctm.clone(), _top.clip));

  @override
  void saveLayer(Rect? bounds, Paint paint) {
    final a = _alpha(paint.color);
    final filter = paint.colorFilter == null
        ? null
        : _colorFilterAttr(paint.colorFilter!);
    _openGroup('${a < 1 ? ' opacity="${_n(a)}"' : ''}${filter ?? ''}');
  }

  /// Opens a group (opacity, filter) that lasts until the matching restore.
  void _openGroup(String attrs) {
    _stack.add(_State(_top.ctm.clone(), _top.clip, layer: true));
    final group = _Group('<g$attrs>', '</g>');
    _groups.last.kids.add(group);
    _groups.add(group);
  }

  /// SVG filter attribute for a ColorFilter, or null if it cannot be
  /// expressed. ColorFilter is opaque; its toString carries the values.
  String? _colorFilterAttr(ColorFilter filter) {
    final text = filter.toString();
    final nums = RegExp(
      r'-?\d+(?:\.\d+)?(?:e-?\d+)?',
    ).allMatches(text).map((m) => double.parse(m.group(0)!)).toList();
    String body;
    if (text.startsWith('ColorFilter.matrix') && nums.length == 20) {
      // Flutter's offsets are 0..255; SVG's are 0..1.
      final values = <String>[
        for (var i = 0; i < 20; i++) _n4(i % 5 == 4 ? nums[i] / 255 : nums[i]),
      ];
      body = '<feColorMatrix type="matrix" values="${values.join(' ')}"/>';
    } else if (text.startsWith('ColorFilter.mode') && nums.length >= 4) {
      final c = Color.from(
        alpha: nums[0],
        red: nums[1],
        green: nums[2],
        blue: nums[3],
      );
      final op = switch (text.split('BlendMode.').last.replaceAll(')', '')) {
        'srcIn' => 'in',
        'srcATop' => 'atop',
        _ => null,
      };
      if (op == null) return null;
      body =
          '<feFlood flood-color="${_hex(c)}" flood-opacity="${_n(_alpha(c))}"/>'
          '<feComposite in2="SourceGraphic" operator="$op"/>';
    } else {
      return null;
    }
    final id = 'f${_ids++}';
    _defs.add(
      '<filter id="$id" x="0" y="0" width="100%" height="100%" '
      'color-interpolation-filters="sRGB">$body</filter>',
    );
    return ' filter="url(#$id)"';
  }

  @override
  void restore() {
    if (_stack.length <= 1) return;
    final popped = _stack.removeLast();
    if (popped.layer) _groups.removeLast();
  }

  @override
  void restoreToCount(int count) {
    while (_stack.length > math.max(1, count)) {
      restore();
    }
  }

  @override
  int getSaveCount() => _stack.length;

  @override
  void translate(double dx, double dy) => _top.ctm.translate(dx, dy);

  @override
  void scale(double sx, [double? sy]) => _top.ctm.scale(sx, sy ?? sx, 1.0);

  @override
  void rotate(double radians) => _top.ctm.rotateZ(radians);

  @override
  void skew(double sx, double sy) =>
      _top.ctm.multiply(Matrix4.skew(math.atan(sx), math.atan(sy)));

  @override
  void transform(Float64List matrix4) =>
      _top.ctm.multiply(Matrix4.fromFloat64List(matrix4));

  @override
  Float64List getTransform() => Float64List.fromList(_top.ctm.storage);

  void _clip(String shape) {
    final id = 'c${_ids++}';
    final parent = _top.clip;
    _defs.add(
      '<clipPath id="$id" clipPathUnits="userSpaceOnUse"'
      '${parent == null ? '' : ' clip-path="url(#$parent)"'}>'
      '<$shape${_transformAttr(_top.ctm)}/></clipPath>',
    );
    final s = _stack.removeLast();
    _stack.add(_State(s.ctm, id, layer: s.layer));
  }

  @override
  void clipRect(
    Rect rect, {
    ui.ClipOp clipOp = ui.ClipOp.intersect,
    bool doAntiAlias = true,
  }) {
    if (clipOp == ui.ClipOp.difference) {
      warnings.add('clipRect(difference) ignored');
      return;
    }
    _clip(
      'rect x="${_n(rect.left)}" y="${_n(rect.top)}" '
      'width="${_n(rect.width)}" height="${_n(rect.height)}"',
    );
  }

  @override
  void clipRRect(RRect rrect, {bool doAntiAlias = true}) =>
      _clip(_rrectElement(rrect));

  @override
  void clipRSuperellipse(
    ui.RSuperellipse rsuperellipse, {
    bool doAntiAlias = true,
  }) => _clip(_rrectElement(_approx(rsuperellipse)));

  @override
  void clipPath(Path path, {bool doAntiAlias = true}) =>
      _clip('path d="${_pathData(path)}"${_fillRule(path)}');

  @override
  Rect getLocalClipBounds() => Offset.zero & _size;

  @override
  Rect getDestinationClipBounds() => Offset.zero & _size;

  RRect _approx(ui.RSuperellipse r) => RRect.fromLTRBAndCorners(
    r.left,
    r.top,
    r.right,
    r.bottom,
    topLeft: r.tlRadius,
    topRight: r.trRadius,
    bottomRight: r.brRadius,
    bottomLeft: r.blRadius,
  );

  // -------------------------------------------------------------------------
  // Canvas: drawing
  // -------------------------------------------------------------------------

  @override
  void drawColor(Color color, BlendMode blendMode) {
    final saved = _top.ctm.clone();
    _top.ctm.setIdentity();
    drawRect(Offset.zero & _size, Paint()..color = color);
    _top.ctm.setFrom(saved);
  }

  @override
  void drawPaint(Paint paint) {
    final saved = _top.ctm.clone();
    _top.ctm.setIdentity();
    drawRect(Offset.zero & _size, paint);
    _top.ctm.setFrom(saved);
  }

  @override
  void drawLine(Offset p1, Offset p2, Paint paint) {
    if (_needsRaster(paint)) {
      return _raster(
        Rect.fromPoints(p1, p2).inflate(paint.strokeWidth),
        (c) => c.drawLine(p1, p2, paint),
      );
    }
    final stroke = Paint()
      ..color = paint.color
      ..style = PaintingStyle.stroke
      ..strokeWidth = paint.strokeWidth
      ..strokeCap = paint.strokeCap
      ..maskFilter = paint.maskFilter;
    _shape(
      'line',
      stroke,
      extra:
          ' x1="${_n(p1.dx)}" y1="${_n(p1.dy)}" '
          'x2="${_n(p2.dx)}" y2="${_n(p2.dy)}"',
    );
  }

  @override
  void drawRect(Rect rect, Paint paint) {
    if (_needsRaster(paint)) {
      return _raster(
        rect.inflate(paint.strokeWidth),
        (c) => c.drawRect(rect, paint),
      );
    }
    _shape(
      'rect',
      paint,
      extra:
          ' x="${_n(rect.left)}" y="${_n(rect.top)}" '
          'width="${_n(rect.width)}" height="${_n(rect.height)}"',
    );
  }

  @override
  void drawRRect(RRect rrect, Paint paint) {
    if (_needsRaster(paint)) {
      return _raster(
        rrect.outerRect.inflate(paint.strokeWidth),
        (c) => c.drawRRect(rrect, paint),
      );
    }
    final el = _rrectElement(rrect);
    final space = el.indexOf(' ');
    _shape(el.substring(0, space), paint, extra: el.substring(space));
  }

  @override
  void drawRSuperellipse(ui.RSuperellipse rsuperellipse, Paint paint) =>
      drawRRect(_approx(rsuperellipse), paint);

  @override
  void drawDRRect(RRect outer, RRect inner, Paint paint) {
    if (_needsRaster(paint)) {
      return _raster(outer.outerRect, (c) => c.drawDRRect(outer, inner, paint));
    }
    _shape(
      'path',
      paint,
      extra:
          ' d="${_rrectPath(outer)}${_rrectPath(inner)}" '
          'fill-rule="evenodd"',
    );
  }

  @override
  void drawOval(Rect rect, Paint paint) {
    if (_needsRaster(paint)) {
      return _raster(
        rect.inflate(paint.strokeWidth),
        (c) => c.drawOval(rect, paint),
      );
    }
    _shape(
      'ellipse',
      paint,
      extra:
          ' cx="${_n(rect.center.dx)}" cy="${_n(rect.center.dy)}" '
          'rx="${_n(rect.width / 2)}" ry="${_n(rect.height / 2)}"',
    );
  }

  @override
  void drawCircle(Offset c, double radius, Paint paint) {
    if (_needsRaster(paint)) {
      return _raster(
        Rect.fromCircle(center: c, radius: radius + paint.strokeWidth),
        (canvas) => canvas.drawCircle(c, radius, paint),
      );
    }
    _shape(
      'circle',
      paint,
      extra: ' cx="${_n(c.dx)}" cy="${_n(c.dy)}" r="${_n(radius)}"',
    );
  }

  @override
  void drawArc(
    Rect rect,
    double startAngle,
    double sweepAngle,
    bool useCenter,
    Paint paint,
  ) {
    if (_needsRaster(paint) || sweepAngle.abs() >= 2 * math.pi) {
      if (!_needsRaster(paint)) return drawOval(rect, paint);
      return _raster(
        rect.inflate(paint.strokeWidth),
        (c) => c.drawArc(rect, startAngle, sweepAngle, useCenter, paint),
      );
    }
    final rx = rect.width / 2, ry = rect.height / 2;
    final cx = rect.center.dx, cy = rect.center.dy;
    Offset at(double t) => Offset(cx + rx * math.cos(t), cy + ry * math.sin(t));
    final p0 = at(startAngle), p1 = at(startAngle + sweepAngle);
    final large = sweepAngle.abs() > math.pi ? 1 : 0;
    final sweep = sweepAngle > 0 ? 1 : 0;
    final d = StringBuffer();
    if (useCenter) {
      d.write('M${_n(cx)} ${_n(cy)}L${_n(p0.dx)} ${_n(p0.dy)}');
    } else {
      d.write('M${_n(p0.dx)} ${_n(p0.dy)}');
    }
    d.write('A${_n(rx)} ${_n(ry)} 0 $large $sweep ${_n(p1.dx)} ${_n(p1.dy)}');
    if (useCenter) d.write('Z');
    _shape('path', paint, extra: ' d="$d"');
  }

  @override
  void drawPath(Path path, Paint paint) {
    if (_needsRaster(paint)) {
      return _raster(
        path.getBounds().inflate(paint.strokeWidth),
        (c) => c.drawPath(path, paint),
      );
    }
    final d = _pathData(path);
    if (d.isEmpty) return;
    _shape('path', paint, extra: ' d="$d"${_fillRule(path)}');
  }

  @override
  void drawImage(ui.Image image, Offset offset, Paint paint) => drawImageRect(
    image,
    Rect.fromLTWH(0, 0, image.width.toDouble(), image.height.toDouble()),
    offset & Size(image.width.toDouble(), image.height.toDouble()),
    paint,
  );

  @override
  void drawImageRect(ui.Image image, Rect src, Rect dst, Paint paint) {
    if (_needsRaster(paint)) {
      return _raster(dst, (c) => c.drawImageRect(image, src, dst, paint));
    }
    final img = image.clone();
    final transform = _transformAttr(_top.ctm);
    final a = _alpha(paint.color);
    _emit(
      _Deferred(() async {
        final png = await img.toByteData(format: ui.ImageByteFormat.png);
        final w = img.width, h = img.height;
        img.dispose();
        return '<svg x="${_n(dst.left)}" y="${_n(dst.top)}" '
            'width="${_n(dst.width)}" height="${_n(dst.height)}" '
            'viewBox="${_n(src.left)} ${_n(src.top)} ${_n(src.width)} '
            '${_n(src.height)}" preserveAspectRatio="none" overflow="hidden"'
            '${a < 1 ? ' opacity="${_n(a)}"' : ''}$transform>'
            '<image width="$w" height="$h" xlink:href="data:image/png;base64,'
            '${base64Encode(png!.buffer.asUint8List())}"/></svg>';
      }),
    );
  }

  @override
  void drawImageNine(ui.Image image, Rect center, Rect dst, Paint paint) =>
      _raster(dst, (c) => c.drawImageNine(image, center, dst, paint));

  @override
  void drawPicture(ui.Picture picture) =>
      _raster(Offset.zero & _size, (c) => c.drawPicture(picture));

  @override
  void drawParagraph(ui.Paragraph paragraph, Offset offset) {
    if (_paragraphs.isNotEmpty) {
      final (rp, at) = _paragraphs.last;
      if (_emitParagraph(rp, at)) return;
    }
    _raster(
      offset & Size(paragraph.width, paragraph.height),
      (c) => c.drawParagraph(paragraph, offset),
    );
  }

  @override
  void drawPoints(ui.PointMode pointMode, List<Offset> points, Paint paint) {
    if (points.isEmpty) return;
    if (_needsRaster(paint)) {
      var bounds = Rect.fromPoints(points.first, points.first);
      for (final p in points) {
        bounds = bounds.expandToInclude(Rect.fromPoints(p, p));
      }
      return _raster(
        bounds.inflate(paint.strokeWidth),
        (c) => c.drawPoints(pointMode, points, paint),
      );
    }
    switch (pointMode) {
      case ui.PointMode.points:
        final r = paint.strokeWidth / 2;
        final dot = Paint()..color = paint.color;
        for (final p in points) {
          if (paint.strokeCap == StrokeCap.round) {
            drawCircle(p, r, dot);
          } else {
            drawRect(Rect.fromCircle(center: p, radius: r), dot);
          }
        }
      case ui.PointMode.lines:
        for (var i = 0; i + 1 < points.length; i += 2) {
          drawLine(points[i], points[i + 1], paint);
        }
      case ui.PointMode.polygon:
        final stroke = Paint()
          ..color = paint.color
          ..style = PaintingStyle.stroke
          ..strokeWidth = paint.strokeWidth
          ..strokeCap = paint.strokeCap
          ..strokeJoin = paint.strokeJoin;
        _shape(
          'polyline',
          stroke,
          extra:
              ' points="'
              '${points.map((p) => '${_n(p.dx)},${_n(p.dy)}').join(' ')}"',
        );
    }
  }

  @override
  void drawRawPoints(ui.PointMode pointMode, Float32List points, Paint paint) =>
      drawPoints(pointMode, <Offset>[
        for (var i = 0; i + 1 < points.length; i += 2)
          Offset(points[i], points[i + 1]),
      ], paint);

  @override
  void drawVertices(ui.Vertices vertices, BlendMode blendMode, Paint paint) =>
      _raster(
        Offset.zero & _size,
        (c) => c.drawVertices(vertices, blendMode, paint),
      );

  @override
  void drawAtlas(
    ui.Image atlas,
    List<RSTransform> transforms,
    List<Rect> rects,
    List<Color>? colors,
    BlendMode? blendMode,
    Rect? cullRect,
    Paint paint,
  ) => _raster(
    Offset.zero & _size,
    (c) => c.drawAtlas(
      atlas,
      transforms,
      rects,
      colors,
      blendMode,
      cullRect,
      paint,
    ),
  );

  @override
  void drawRawAtlas(
    ui.Image atlas,
    Float32List rstTransforms,
    Float32List rects,
    Int32List? colors,
    BlendMode? blendMode,
    Rect? cullRect,
    Paint paint,
  ) => _raster(
    Offset.zero & _size,
    (c) => c.drawRawAtlas(
      atlas,
      rstTransforms,
      rects,
      colors,
      blendMode,
      cullRect,
      paint,
    ),
  );

  @override
  void drawShadow(
    Path path,
    Color color,
    double elevation,
    bool transparentOccluder,
  ) {
    if (elevation <= 0) return;
    // Material shadows are a light-source model; this is the usual soft
    // approximation: the shape, offset down and blurred.
    save();
    translate(0, elevation * 0.5);
    drawPath(
      path,
      Paint()
        ..color = color.withValues(alpha: _alpha(color) * 0.45)
        ..maskFilter = MaskFilter.blur(BlurStyle.normal, elevation * 0.6),
    );
    restore();
  }
}

/// A PaintingContext that paints every layer push back into its canvas form
/// on a [VectorSvgRecorder], so the whole tree lands in one SVG.
class _SvgPaintingContext extends PaintingContext {
  _SvgPaintingContext(this.svg, Rect bounds) : super(ContainerLayer(), bounds);

  final VectorSvgRecorder svg;

  @override
  Canvas get canvas => svg;

  @override
  void paintChild(RenderObject child, Offset offset) {
    // A repaint boundary keeps some of its effect in its own layer rather
    // than in paint() - RenderOpacity at a partial alpha is one. Ask it for
    // that layer and apply it as a group.
    if (child.isRepaintBoundary) {
      // ignore: invalid_use_of_protected_member
      final layer = child.updateCompositedLayer(oldLayer: null);
      if (layer is OpacityLayer && (layer.alpha ?? 255) < 255) {
        svg.saveLayer(
          null,
          Paint()..color = Color.fromARGB(layer.alpha!, 0, 0, 0),
        );
        _paint(child, offset);
        svg.restore();
        return;
      }
    }
    _paint(child, offset);
  }

  void _paint(RenderObject child, Offset offset) {
    if (child is RenderParagraph) {
      svg._pushParagraph(child, offset);
      try {
        child.paint(this, offset);
      } finally {
        svg._popParagraph();
      }
      return;
    }
    child.paint(this, offset);
  }

  @override
  PaintingContext createChildContext(ContainerLayer childLayer, Rect bounds) =>
      _SvgPaintingContext(svg, bounds);

  @override
  void pushLayer(
    ContainerLayer childLayer,
    PaintingContextCallback painter,
    Offset offset, {
    Rect? childPaintBounds,
  }) {
    if (childLayer is OpacityLayer) {
      svg.saveLayer(
        null,
        Paint()..color = Color.fromARGB(childLayer.alpha ?? 255, 0, 0, 0),
      );
      painter(this, offset);
      svg.restore();
      return;
    }
    if (childLayer is TransformLayer && childLayer.transform != null) {
      svg.save();
      svg.transform(childLayer.transform!.storage);
      painter(this, offset);
      svg.restore();
      return;
    }
    if (childLayer is! OffsetLayer || childLayer.runtimeType != OffsetLayer) {
      // Effects (backdrop / image filters, shader masks, leader/follower)
      // are painted without their effect.
      svg.warnings.add('layer effect ignored: ${childLayer.runtimeType}');
    }
    painter(this, offset);
  }

  @override
  void addLayer(Layer layer) {
    svg.warnings.add('raw layer not exported: ${layer.runtimeType}');
  }

  @override
  ClipRectLayer? pushClipRect(
    bool needsCompositing,
    Offset offset,
    Rect clipRect,
    PaintingContextCallback painter, {
    Clip clipBehavior = Clip.hardEdge,
    ClipRectLayer? oldLayer,
  }) {
    super.pushClipRect(
      false,
      offset,
      clipRect,
      painter,
      clipBehavior: clipBehavior,
    );
    return oldLayer;
  }

  @override
  ClipRRectLayer? pushClipRRect(
    bool needsCompositing,
    Offset offset,
    Rect bounds,
    RRect clipRRect,
    PaintingContextCallback painter, {
    Clip clipBehavior = Clip.antiAlias,
    ClipRRectLayer? oldLayer,
  }) {
    super.pushClipRRect(
      false,
      offset,
      bounds,
      clipRRect,
      painter,
      clipBehavior: clipBehavior,
    );
    return oldLayer;
  }

  @override
  ClipRSuperellipseLayer? pushClipRSuperellipse(
    bool needsCompositing,
    Offset offset,
    Rect bounds,
    ui.RSuperellipse clipRSuperellipse,
    PaintingContextCallback painter, {
    Clip clipBehavior = Clip.antiAlias,
    ClipRSuperellipseLayer? oldLayer,
  }) {
    super.pushClipRSuperellipse(
      false,
      offset,
      bounds,
      clipRSuperellipse,
      painter,
      clipBehavior: clipBehavior,
    );
    return oldLayer;
  }

  @override
  ClipPathLayer? pushClipPath(
    bool needsCompositing,
    Offset offset,
    Rect bounds,
    Path clipPath,
    PaintingContextCallback painter, {
    Clip clipBehavior = Clip.antiAlias,
    ClipPathLayer? oldLayer,
  }) {
    super.pushClipPath(
      false,
      offset,
      bounds,
      clipPath,
      painter,
      clipBehavior: clipBehavior,
    );
    return oldLayer;
  }

  @override
  TransformLayer? pushTransform(
    bool needsCompositing,
    Offset offset,
    Matrix4 transform,
    PaintingContextCallback painter, {
    TransformLayer? oldLayer,
  }) {
    super.pushTransform(false, offset, transform, painter);
    return oldLayer;
  }

  @override
  OpacityLayer pushOpacity(
    Offset offset,
    int alpha,
    PaintingContextCallback painter, {
    OpacityLayer? oldLayer,
  }) {
    svg.saveLayer(null, Paint()..color = Color.fromARGB(alpha, 0, 0, 0));
    painter(this, offset);
    svg.restore();
    return oldLayer ?? OpacityLayer(alpha: alpha, offset: offset);
  }

  @override
  ColorFilterLayer pushColorFilter(
    Offset offset,
    ColorFilter colorFilter,
    PaintingContextCallback painter, {
    ColorFilterLayer? oldLayer,
  }) {
    final attr = svg._colorFilterAttr(colorFilter);
    if (attr == null) {
      svg.warnings.add('colour filter ignored: $colorFilter');
      painter(this, offset);
    } else {
      svg._openGroup(attr);
      painter(this, offset);
      svg.restore();
    }
    return oldLayer ?? ColorFilterLayer(colorFilter: colorFilter);
  }
}

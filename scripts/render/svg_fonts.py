#!/usr/bin/env python3
# Copyright (c) 2026 ROKCT INTELLIGENCE (PTY) LTD
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Shrink the fonts inside a vector render SVG, or turn its text into shapes.

The harness's vector export (templates/render-harness/vector_svg.dart) writes
each face the screen uses as a whole @font-face file, so a frame is ~1.4 MB
of which ~95% is font (an icon font alone is ~700 KB). Two ways out:

  subset  (default) keep real, selectable <text>, but cut every embedded face
          down to the characters the frame actually draws, as WOFF. Typical
          frame: ~1.4 MB -> ~100 KB.
  outline replace every <text> with the glyph outlines as <path>, and drop
          the fonts. Looks the same everywhere, including design tools that
          ignore embedded fonts (Figma, Illustrator); text is no longer text.

Characters keep the exact x positions Flutter laid out, so neither mode
changes the layout. Needs fontTools (`pip install fonttools`); without it the
file is left as is and the script says so.

Run:  python scripts/render/svg_fonts.py in.vector.svg out.vector.svg
      python scripts/render/svg_fonts.py --outline in.vector.svg out.svg
"""

import argparse
import base64
import html
import io
import re
import sys

FACE = re.compile(
    r"@font-face\{font-family:'(?P<family>[^']+)';"
    r"font-weight:(?P<weight>\d+);font-style:(?P<style>\w+);"
    r"src:url\(data:(?P<mime>[^;]+);base64,(?P<data>[^)]+)\)"
    r" format\('(?P<format>\w+)'\);\}")
TEXT = re.compile(r'<text (?P<attrs>[^>]*)>(?P<body>[^<]*)</text>')
ATTR = re.compile(r'([\w:-]+)="([^"]*)"')


def _key(family, weight, style):
    return (family, int(weight), style)


def _text_key(attrs):
    family = attrs.get('font-family', '').strip("'\"")
    return _key(family, attrs.get('font-weight', '400'),
                attrs.get('font-style', 'normal'))


def _faces(svg):
    faces = {}
    for m in FACE.finditer(svg):
        faces[_key(m['family'], m['weight'], m['style'])] = m
    return faces


def _texts(svg):
    for m in TEXT.finditer(svg):
        yield m, dict(ATTR.findall(m['attrs'])), html.unescape(m['body'])


def subset(svg):
    """Every embedded face cut down to the characters drawn in it, as WOFF."""
    from fontTools import subset as ft_subset
    from fontTools.ttLib import TTFont

    used = {}
    for _m, attrs, body in _texts(svg):
        used.setdefault(_text_key(attrs), set()).update(body)

    def replace(m):
        chars = used.get(_key(m['family'], m['weight'], m['style']))
        if not chars:
            return ''  # a face no text uses
        # recalcBBoxes=False: some fonts (Remix) ship a glyph bbox that does
        # not match the outline, and renderers place TrueType glyphs from
        # bbox minus side bearing - recomputing the bbox shifts every icon.
        font = TTFont(io.BytesIO(base64.b64decode(m['data'])),
                      recalcBBoxes=False)
        options = ft_subset.Options()
        options.flavor = 'woff'
        options.layout_features = []  # positions are explicit; no shaping
        options.name_IDs = [1, 2]
        options.notdef_outline = True
        subsetter = ft_subset.Subsetter(options)
        subsetter.populate(unicodes=[ord(c) for c in chars])
        subsetter.subset(font)
        out = io.BytesIO()
        font.flavor = 'woff'
        font.save(out)
        data = base64.b64encode(out.getvalue()).decode('ascii')
        return (f"@font-face{{font-family:'{m['family']}';"
                f"font-weight:{m['weight']};font-style:{m['style']};"
                f"src:url(data:font/woff;base64,{data}) format('woff');}}")

    return FACE.sub(replace, svg)


def outline(svg):
    """Every <text> as <path> glyph outlines; the fonts are dropped."""
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.transformPen import TransformPen
    from fontTools.ttLib import TTFont

    fonts = {}
    for key, m in _faces(svg).items():
        fonts[key] = TTFont(io.BytesIO(base64.b64decode(m['data'])))

    missing = set()

    def replace(m):
        attrs = dict(ATTR.findall(m['attrs']))
        key = _text_key(attrs)
        font = fonts.get(key)
        if font is None:
            missing.add(key)
            return m.group(0)
        body = html.unescape(m['body'])
        xs = [float(v) for v in attrs['x'].split()]
        y = float(attrs['y'])
        size = float(attrs['font-size'])
        scale = size / font['head'].unitsPerEm
        cmap = font.getBestCmap() or {}
        glyphs = font.getGlyphSet()
        pen = SVGPathPen(glyphs, ntos=lambda v: f'{v:.2f}'.rstrip('0')
                         .rstrip('.'))
        for ch, x in zip(body, xs):
            name = cmap.get(ord(ch))
            if name is None or ch.isspace():
                continue
            glyphs[name].draw(TransformPen(pen, (scale, 0, 0, -scale, x, y)))
        d = pen.getCommands()
        if not d:
            return ''
        keep = ''.join(
            f' {k}="{attrs[k]}"' for k in ('fill', 'fill-opacity', 'transform')
            if k in attrs)
        label = html.escape(body.strip(), quote=True)
        return f'<path d="{d}"{keep} aria-label="{label}"/>'

    out = TEXT.sub(replace, svg)
    if missing:
        print('[WARNING] no embedded face for '
              + ', '.join(f'{f} {w} {s}' for f, w, s in sorted(missing))
              + ' - that text stays as <text>', file=sys.stderr)
    else:
        out = re.sub(r'<style>.*?</style>\n?', '', out, flags=re.S)
    return out


def process(svg, mode='subset'):
    try:
        import fontTools  # noqa: F401
    except ImportError:
        print('[WARNING] fontTools is not installed (pip install fonttools); '
              'the SVG keeps its full embedded fonts.', file=sys.stderr)
        return svg
    return outline(svg) if mode == 'outline' else subset(svg)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('src')
    parser.add_argument('dst')
    parser.add_argument('--outline', action='store_true',
                        help='turn text into glyph outlines and drop the fonts')
    args = parser.parse_args()
    with open(args.src, encoding='utf-8') as handle:
        svg = handle.read()
    out = process(svg, 'outline' if args.outline else 'subset')
    with open(args.dst, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(out)
    print(f'[INFO] {args.src} ({len(svg) // 1024} KB) -> {args.dst} '
          f'({len(out) // 1024} KB)')
    return 0


if __name__ == '__main__':
    sys.exit(main())

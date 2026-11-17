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
"""Build the review strip from the guided tour's own stills.

The screen list is the tour's: every visible step in tour.resolved.json that
has a captured still becomes a frame, in tour order. Remove a step from the
tour and its frame disappears from the strip on the next run. Nothing is
registered by hand.

Chips are optional and hand-placed. An overlay file (default
``tour/chips.json``) is keyed by tour step key::

    {
      "schedule": [
        {"label": "lesson card", "x": 120, "y": 340, "w": 300, "h": 90}
      ]
    }

``x``/``y``/``w``/``h`` are pixels on the still. An overlay entry whose step
is no longer in the tour is ignored and logged as stale. A step with no
overlay entry gets a frame with no chips.

Outputs, written to ``--work-dir``:

  * ``strip.json`` - a strip config for compose_strip.py;
  * ``<key>.rects.json`` - a per-frame rect sidecar in the render harness
    format, so the composer's numbering, legend and quality gate apply
    unchanged.

Run compose_strip.py on ``strip.json`` to get the page.
"""

import argparse
import json
import os
import re
import struct
import sys

STILL_RE = re.compile(r'^(\d+)-(.+)\.png$')


def log(message):
    print(f'[tour-strip] {message}', flush=True)


def png_size(path):
    """Width and height from the PNG IHDR chunk, without decoding the image."""
    with open(path, 'rb') as handle:
        header = handle.read(24)
    if len(header) < 24 or header[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError(f'{path} is not a PNG')
    return struct.unpack('>II', header[16:24])


def plain(text):
    """Caption text without the tour's *highlight* markers."""
    return str(text or '').replace('*', '').strip()


def index_stills(shots_dir):
    """Map step key -> still path, from the tour's NN-key.png names."""
    stills = {}
    for name in os.listdir(shots_dir):
        match = STILL_RE.match(name)
        if match:
            stills[match.group(2)] = os.path.join(shots_dir, name)
    return stills


def load_chips(path):
    if not path or not os.path.isfile(path):
        return {}
    with open(path, encoding='utf-8') as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise SystemExit(f'{path}: chips overlay must be a JSON object keyed by step key')
    return data


def build(args):
    with open(args.resolved, encoding='utf-8') as handle:
        resolved = json.load(handle)

    steps = resolved.get('steps') or []
    stills = index_stills(args.shots)
    chips = load_chips(args.chips)

    step_keys = {step['key'] for step in steps}
    for key in sorted(set(chips) - step_keys):
        log(f'WARNING: chips for "{key}" ignored - no such tour step (stale overlay entry)')

    os.makedirs(args.work_dir, exist_ok=True)
    frames = []
    for step in steps:
        key = step['key']
        png = stills.get(key)
        if png is None:
            log(f'WARNING: no still for tour step "{key}" - no frame')
            continue

        width, height = png_size(png)
        elements = []
        for index, chip in enumerate(chips.get(key) or []):
            elements.append({
                'key': f'tour.{key}.{index + 1}',
                'label': str(chip['label']),
                'x': float(chip['x']),
                'y': float(chip['y']),
                'w': float(chip['w']),
                'h': float(chip['h']),
            })

        rects_name = f'{key}.rects.json'
        with open(os.path.join(args.work_dir, rects_name), 'w', encoding='utf-8') as handle:
            json.dump({
                'variant': key,
                'logicalWidth': width,
                'logicalHeight': height,
                'devicePixelRatio': 1.0,
                'elements': elements,
            }, handle, indent=2)
            handle.write('\n')

        frames.append({
            'section': step.get('chapter') or 'Tour',
            'caption': plain(step.get('title')) or key,
            'status': 'SHIPPED',
            'png': os.path.abspath(png),
            'rects': rects_name,
            'note': plain(step.get('caption')),
        })

    if not frames:
        raise SystemExit('no tour step has a captured still - nothing to compose')

    config = {
        'title': args.title,
        'kicker': args.kicker,
        'lede': args.lede,
        'fonts': 'system',
        'chips_default': True,
        'base_dir': '.',
        'frames': frames,
    }
    config_path = os.path.join(args.work_dir, 'strip.json')
    with open(config_path, 'w', encoding='utf-8') as handle:
        json.dump(config, handle, indent=2)
        handle.write('\n')
    log(f'wrote {config_path} ({len(frames)} frames from {len(steps)} tour steps)')
    return config_path


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--resolved', default='tour.resolved.json')
    parser.add_argument('--shots', default='tour_screenshots',
                        help='directory of the tour still NN-key.png files')
    parser.add_argument('--chips', default=os.path.join('tour', 'chips.json'),
                        help='optional hand-placed chip overlay keyed by step key')
    parser.add_argument('--work-dir', default='tour_strip')
    parser.add_argument('--title', default='Tour walkthrough')
    parser.add_argument('--kicker', default='guided tour - real stills')
    parser.add_argument('--lede', default='Every screen the guided tour captures, in tour order.')
    args = parser.parse_args(argv)
    build(args)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

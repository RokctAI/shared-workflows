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

import json
import os
import struct
import sys
import tempfile
import unittest
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'render'))

import tour_strip  # noqa: E402


def _png(width, height):
    raw = b''.join(
        b'\x00' + b''.join(bytes([(x * 255 // width) % 256, (y * 255 // height) % 256,
                                   ((x + y) * 7) % 256]) for x in range(width))
        for y in range(height))

    def chunk(tag, data):
        body = tag + data
        return struct.pack('>I', len(data)) + body + struct.pack(
            '>I', zlib.crc32(body) & 0xffffffff)

    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack(
        '>IIBBBBB', width, height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw))
        + chunk(b'IEND', b''))


class TourStripTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.shots = os.path.join(self.dir, 'shots')
        os.makedirs(self.shots)
        for name in ('01-welcome.png', '02-schedule.png', '03-orphan.png'):
            with open(os.path.join(self.shots, name), 'wb') as handle:
                handle.write(_png(120, 240))
        self.resolved = os.path.join(self.dir, 'tour.resolved.json')
        with open(self.resolved, 'w') as handle:
            json.dump({'steps': [
                {'key': 'welcome', 'title': 'Welcome', 'caption': 'Hi *there*', 'chapter': 'auth'},
                {'key': 'schedule', 'title': 'Today', 'caption': 'Your day', 'chapter': 'lms'},
            ]}, handle)
        self.chips = os.path.join(self.dir, 'chips.json')
        with open(self.chips, 'w') as handle:
            json.dump({
                'schedule': [{'label': 'lesson card', 'x': 10, 'y': 20, 'w': 50, 'h': 30}],
                'removed_step': [{'label': 'stale', 'x': 1, 'y': 1, 'w': 1, 'h': 1}],
            }, handle)
        self.work = os.path.join(self.dir, 'work')

    def run_build(self, chips=None):
        args = tour_strip.argparse.Namespace(
            resolved=self.resolved, shots=self.shots,
            chips=self.chips if chips is None else chips,
            work_dir=self.work, title='t', kicker='k', lede='l')
        tour_strip.build(args)
        with open(os.path.join(self.work, 'strip.json')) as handle:
            return json.load(handle)

    def test_frames_follow_the_tour_not_the_stills_folder(self):
        config = self.run_build()
        self.assertEqual([f['caption'] for f in config['frames']], ['Welcome', 'Today'])
        self.assertNotIn('orphan', json.dumps(config))

    def test_removing_a_tour_step_removes_its_frame(self):
        with open(self.resolved) as handle:
            resolved = json.load(handle)
        resolved['steps'] = resolved['steps'][:1]
        with open(self.resolved, 'w') as handle:
            json.dump(resolved, handle)
        config = self.run_build()
        self.assertEqual([f['caption'] for f in config['frames']], ['Welcome'])

    def test_chips_land_on_their_step_and_stale_chips_are_ignored(self):
        self.run_build()
        with open(os.path.join(self.work, 'schedule.rects.json')) as handle:
            rects = json.load(handle)
        self.assertEqual(rects['logicalWidth'], 120)
        self.assertEqual(rects['logicalHeight'], 240)
        self.assertEqual([e['label'] for e in rects['elements']], ['lesson card'])
        with open(os.path.join(self.work, 'welcome.rects.json')) as handle:
            self.assertEqual(json.load(handle)['elements'], [])

    def test_missing_overlay_is_fine(self):
        config = self.run_build(chips=os.path.join(self.dir, 'absent.json'))
        self.assertEqual(len(config['frames']), 2)

    def test_markup_is_stripped_from_captions(self):
        config = self.run_build()
        self.assertEqual(config['frames'][0]['note'], 'Hi there')


if __name__ == '__main__':
    unittest.main()

#!/usr/bin/env python3
# Copyright (c) 2026 ROKCT INTELLIGENCE (PTY) LTD
# (MIT licence, see the header of sdk_validator.py)

"""Tests for the tablet planes check in sdk_validator.py.

Run:  python scripts/tests/test_sdk_validator_tablet_planes.py
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import sdk_validator as v  # noqa: E402


def _sdk(files):
    d = Path(tempfile.mkdtemp())
    for rel, text in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf-8')
    return d


class TabletPlanesTest(unittest.TestCase):
    def run_check(self, files):
        d = _sdk(files)
        return [n for _, _, n in
                v.find_single_plane_routes(d, v.index_dart_classes([d]))]

    def test_stretched_route_fails(self):
        bad = self.run_check({'lib/a.dart': (
            "@RoutePage()\nclass LibraryPage extends StatelessWidget {\n"
            "  Widget build(c) => Scaffold(body: ListView());\n}\n")})
        self.assertEqual(bad, ['LibraryPage'])

    def test_direct_plane_host_passes(self):
        self.assertEqual(self.run_check({'lib/a.dart': (
            "@RoutePage()\nclass OrdersPage extends StatelessWidget {\n"
            "  Widget build(c) => PlaneHost(pages: [PlanePage()]);\n}\n")}), [])

    def test_plane_through_state_and_child_passes(self):
        self.assertEqual(self.run_check({
            'lib/a.dart': (
                "@RoutePage()\nclass TasksPage extends StatefulWidget {\n"
                "  State createState() => _TasksPageState();\n}\n"
                "class _TasksPageState extends State<TasksPage> {\n"
                "  Widget build(c) => const TasksBody();\n}\n"),
            'lib/b.dart': (
                "class TasksBody extends StatelessWidget {\n"
                "  Widget build(c) => KitchenPlaneFlow();\n}\n")}), [])

    def test_opt_out_marker_passes(self):
        self.assertEqual(self.run_check({'lib/a.dart': (
            "// planes: single kids mode is full-screen by design\n"
            "@RoutePage()\nclass KidsPage extends StatelessWidget {}\n")}), [])

    def test_unrouted_widget_ignored(self):
        self.assertEqual(self.run_check({'lib/a.dart': (
            "class Card extends StatelessWidget {}\n")}), [])


if __name__ == '__main__':
    unittest.main()

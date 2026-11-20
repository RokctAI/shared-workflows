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
"""Merge the per-SDK render fragments into one generated screen list.

Each SDK may ship ``<sdk>/dart/templates/render/<name>.render.yaml`` next to
its tour fragment and demo data. A fragment lists the SDK's screens::

    screens:
      - name: tutors                  # unique id, used in file names
        caption: Tutors               # frame caption
        widget: TutorDiscoveryRouteView
        import: package:{package}/presentation/routes/lms_route_pages.dart
        construct: const TutorDiscoveryRouteView()   # optional

``{package}`` is replaced with the shell's package name (pubspec.yaml). The
app shell keeps its harness; this script writes the screen list it loops over:

  * ``<out-dir>/render_screens.g.dart`` - ``kGeneratedScreens`` (name ->
    builder + finder), imported by the shell's render test;
  * ``<out-dir>/strip.frames.g.json`` - one light and one dark strip.json frame
    per screen, to append to the shell's ``frames``.

With ``--tour-resolved`` (the guided tour's tour.resolved.json) the TOUR is the
screen list. A fragment screen is bound to a tour step by name - ``name`` must
equal the step key - so nothing is registered by hand a second time:

  * a tour step with a same-named fragment screen is rendered (dark + light);
  * a tour step with none is SKIPPED with a logged reason, never a failure;
  * a fragment screen that is not a tour step is ignored (logged).

``--strip-config`` + ``--out-strip-config`` also write the shell's strip config
with the generated frames appended, tour order, after its explicit frames (a
generated frame whose png the explicit config already names is not repeated).
Generated frames carry ``"generated": true``; after the render,
``--prune-config`` drops the ones whose PNG/sidecar the harness did not write
(a screen it cannot render headlessly) with a logged reason, so the composer
never sees a missing file. Explicit frames are never pruned.

Fragments are read from the composed SDK cache (``.rokct/cache/*/templates/
render/*.render.yaml``). A composed SDK with no fragment is skipped with a log
line, never a failure - SDKs adopt gradually. The in-app tutorial layer is not
drawn: a fragment names a real screen widget only.
"""
import argparse
import glob
import json
import os
import re
import sys

yaml = None  # imported lazily: with no fragments the script must not need PyYAML

NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
REQUIRED = ("name", "widget", "import")


def require_yaml():
    global yaml
    try:
        import yaml as _yaml
    except ImportError:
        print("::error::merge_render_fragments.py requires pyyaml (pip install pyyaml)")
        sys.exit(2)
    yaml = _yaml


def package_name(pubspec):
    with open(pubspec, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    name = data.get("name")
    if not name:
        raise SystemExit(f"::error::{pubspec} has no package name")
    return str(name)


def find_fragments(cache_dir):
    return sorted(glob.glob(os.path.join(cache_dir, "*", "**", "render", "*.render.yaml"), recursive=True))


def load_screens(paths, package):
    seen, screens = {}, []
    for path in paths:
        with open(path, encoding="utf-8") as f:
            doc = yaml.safe_load(f) or {}
        for raw in doc.get("screens") or []:
            for key in REQUIRED:
                if not raw.get(key):
                    raise SystemExit(f"::error::{path}: screen missing '{key}': {raw}")
            name = str(raw["name"])
            if not NAME_RE.match(name):
                raise SystemExit(f"::error::{path}: bad screen name '{name}' (use lower_snake)")
            if not IDENT_RE.match(str(raw["widget"])):
                raise SystemExit(f"::error::{path}: bad widget '{raw['widget']}'")
            if name in seen:
                raise SystemExit(f"::error::screen '{name}' in {path} duplicates {seen[name]}")
            seen[name] = path
            screens.append({
                "name": name,
                "caption": str(raw.get("caption") or name.replace("_", " ")),
                "widget": str(raw["widget"]),
                "import": str(raw["import"]).replace("{package}", package),
                "construct": str(raw.get("construct") or f"const {raw['widget']}()"),
                "source": os.path.relpath(path),
            })
    return screens


def emit_dart(screens):
    imports = sorted({s["import"] for s in screens})
    lines = [
        "// GENERATED by shared-workflows scripts/render/merge_render_fragments.py",
        "// from the composed SDKs' *.render.yaml fragments. Do not edit.",
        "// ignore_for_file: type=lint",
        "import 'package:flutter/widgets.dart';",
        "import 'package:flutter_test/flutter_test.dart';",
        *[f"import '{i}';" for i in imports],
        "",
        "class GeneratedScreen {",
        "  const GeneratedScreen(this.build, this.finder);",
        "  final Widget Function() build;",
        "  final Finder Function() finder;",
        "}",
        "",
        "final Map<String, GeneratedScreen> kGeneratedScreens = <String, GeneratedScreen>{",
    ]
    for s in screens:
        lines.append(
            f"  '{s['name']}': GeneratedScreen(() => {s['construct']}, "
            f"() => find.byType({s['widget']})),"
        )
    lines.append("};")
    return "\n".join(lines) + "\n"


def select_tour_screens(screens, steps):
    """Bind fragment screens to tour steps by name, in tour order.

    Returns (selected, skipped) where skipped is a list of (key, reason).
    """
    by_name = {s["name"]: s for s in screens}
    selected, skipped, seen = [], [], set()
    for step in steps:
        key = step.get("key")
        if not key or key in seen:
            continue
        seen.add(key)
        screen = by_name.get(key)
        if screen is not None:
            selected.append(screen)
            continue
        kind = step.get("action") or "step"
        skipped.append((key, (
            f"tour step '{key}' ({kind}) has no render fragment screen named '{key}' "
            "in the composed SDKs (<sdk>/templates/render/*.render.yaml); "
            "its still is a device capture, not a widget the harness can build"
        )))
    for name in sorted(set(by_name) - seen):
        print(f"[render-fragments] ignoring fragment screen '{name}': not a tour step", flush=True)
    return selected, skipped


def merge_strip_config(config_path, frames):
    """The shell's strip config with the generated frames appended."""
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)
    explicit = config.get("frames") or []
    have = {fr.get("png") for fr in explicit}
    # An explicit frame wins over the auto one for the same tour screen, so its
    # hand-placed chips apply: same png name (<key>_<dark|light>.png) or an
    # explicit "tour": "<key>" on the frame (covers both modes).
    claimed = {fr.get("tour") for fr in explicit if fr.get("tour")}
    added = [dict(fr, generated=True) for fr in frames
             if fr["png"] not in have and fr.get("tour") not in claimed]
    config["frames"] = list(config.get("frames") or []) + added
    return config, len(added)


def prune_config(config_path, base_dir, out_path):
    """Drop generated frames the harness did not render; return (kept, dropped)."""
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)
    kept, dropped = [], []
    for fr in config.get("frames") or []:
        if fr.get("generated"):
            missing = [k for k in ("png", "rects")
                       if not os.path.isfile(os.path.join(base_dir, fr.get(k, "")))]
            if missing:
                dropped.append(fr)
                print(
                    f"[render-fragments] skipped '{fr.get('caption')}': the harness wrote no "
                    f"{'/'.join(missing)} in {base_dir} (screen not wired into the shell's render "
                    "test, or it needs state the harness cannot supply)", flush=True)
                continue
        kept.append(fr)
    config["frames"] = kept
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
    return len(kept), len(dropped)


TOUR_SKIPPED_FILE = "tour_skipped.g.json"


def short_reason(text, limit=160):
    """First line of an error, trimmed, for a one-line list entry."""
    line = " ".join(str(text).strip().splitlines()[:1]).strip()
    return line if len(line) <= limit else line[: limit - 3].rstrip() + "..."


def write_skipped_list(out_path, tour_skipped_path, harness_skipped_path):
    """Write the plain-language list of tour screens that were not drawn.

    Two sources: the tour steps with no render fragment (tour_skipped_path, a
    JSON list of {key, reason}) and the screens the harness failed to draw
    (harness_skipped_path, JSON lines of {key, mode, reason}). Either may be
    missing. Returns the number of screens listed.
    """
    no_page = []
    if tour_skipped_path and os.path.isfile(tour_skipped_path):
        with open(tour_skipped_path, encoding="utf-8") as f:
            no_page = [e["key"] for e in json.load(f)]
    failed = {}  # key -> {"modes": [...], "reason": str}, in first-seen order
    if harness_skipped_path and os.path.isfile(harness_skipped_path):
        with open(harness_skipped_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                entry = failed.setdefault(e.get("key", "?"), {"modes": [], "reason": e.get("reason", "")})
                if e.get("mode") and e["mode"] not in entry["modes"]:
                    entry["modes"].append(e["mode"])
    lines = ["# Tour screens not drawn", ""]
    if not no_page and not failed:
        lines.append("All tour screens drawn.")
    if no_page:
        lines += ["## No standalone page (opens from a tap)", ""]
        lines += [f"- {k} - no standalone page (opens from a tap)" for k in no_page]
        lines.append("")
    if failed:
        lines += ["## Failed to draw", ""]
        for k, e in failed.items():
            modes = f" ({', '.join(e['modes'])})" if e["modes"] else ""
            lines.append(f"- {k}{modes} - failed to draw: {short_reason(e['reason'])}")
        lines.append("")
    parent = os.path.dirname(out_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines).rstrip("\n") + "\n")
    return len(no_page) + len(failed)


def emit_frames(screens):
    frames = []
    for s in screens:
        for mode in ("dark", "light"):
            frames.append({
                "section": "Shipped - SDK render fragments",
                "caption": f"{s['caption']} - {mode}",
                "status": "SHIPPED",
                "png": f"{s['name']}_{mode}.png",
                "tour": s["name"],
                "rects": f"{s['name']}_{mode}.json",
                "note": f"from {s['source']}",
            })
    return frames


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--cache-dir", default=".rokct/cache")
    p.add_argument("--pubspec", default="pubspec.yaml")
    p.add_argument("--out-dir", default="test/render")
    p.add_argument("--tour-resolved", help="tour.resolved.json: make the tour the screen list")
    p.add_argument("--strip-config", help="the shell's strip.json to append generated frames to")
    p.add_argument("--out-strip-config", help="where to write the merged strip config")
    p.add_argument("--prune-config", help="merged config to prune after the render (own mode)")
    p.add_argument("--base-dir", default="out", help="--prune-config: where the harness wrote its PNGs")
    p.add_argument("--write-skipped-md", help="write the not-drawn list to this path (own mode)")
    p.add_argument("--tour-skipped", help="--write-skipped-md: the tour_skipped.g.json from the merge step")
    p.add_argument("--harness-skipped", help="--write-skipped-md: the harness's skipped.jsonl")
    args = p.parse_args()

    if args.write_skipped_md:
        n = write_skipped_list(args.write_skipped_md, args.tour_skipped, args.harness_skipped)
        print(f"ℹ️  {n} tour screen(s) not drawn; list written to {args.write_skipped_md}.")
        return 0

    if args.prune_config:
        if not args.out_strip_config:
            p.error("--prune-config needs --out-strip-config")
        kept, dropped = prune_config(args.prune_config, args.base_dir, args.out_strip_config)
        print(f"✅ Strip config: {kept} frame(s) kept, {dropped} generated frame(s) skipped.")
        return 0

    steps = None
    if args.tour_resolved:
        with open(args.tour_resolved, encoding="utf-8") as f:
            steps = json.load(f).get("steps") or []

    paths = find_fragments(args.cache_dir)
    screens = []
    if paths:
        require_yaml()
        screens = load_screens(paths, package_name(args.pubspec))
    else:
        print("ℹ️  No render fragments found in the composed SDKs.")

    skipped = []
    if steps is not None:
        screens, skipped = select_tour_screens(screens, steps)
        for key, reason in skipped:
            print(f"[render-fragments] skipped tour step '{key}': {reason}", flush=True)
        print(f"ℹ️  Tour has {len(steps)} screen(s): {len(screens)} renderable, {len(skipped)} skipped.")
        os.makedirs(args.out_dir, exist_ok=True)
        with open(os.path.join(args.out_dir, TOUR_SKIPPED_FILE), "w", encoding="utf-8", newline="\n") as f:
            json.dump([{"key": k, "reason": r} for k, r in skipped], f, indent=2)
            f.write("\n")

    if not screens:
        print("ℹ️  No screens to render from fragments - nothing generated.")
        return 0
    frames = emit_frames(screens)
    os.makedirs(args.out_dir, exist_ok=True)
    with open(os.path.join(args.out_dir, "render_screens.g.dart"), "w", encoding="utf-8", newline="\n") as f:
        f.write(emit_dart(screens))
    with open(os.path.join(args.out_dir, "strip.frames.g.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(frames, f, indent=2)
        f.write("\n")
    if args.strip_config and args.out_strip_config:
        config, added = merge_strip_config(args.strip_config, frames)
        with open(args.out_strip_config, "w", encoding="utf-8", newline="\n") as f:
            json.dump(config, f, indent=2)
            f.write("\n")
        print(f"✅ Strip config: {added} generated frame(s) appended to {args.strip_config}.")
    print(f"✅ {len(screens)} screen(s) from {len(paths)} fragment(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# Copyright (c) 2026 RokctAI
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
"""Merge an app shell's guided-tour manifest with per-SDK tour fragments.

Every SDK template repo may ship a brand-neutral tour fragment next to its
demo data (e.g. agent's ``lms/dart/templates/tour/lms.tour.yaml``). The app
shell repo keeps only a thin manifest (``tour/app.tour.yaml``) naming which
fragments to include, in what order, plus any app-specific steps and all
branded wording (app name, tagline, video hook). This script resolves the
fragments, substitutes placeholders (``{app_name}``, ``{app_tagline}``) into
fragment captions, and emits:

  * a resolved JSON plan (consumed by capture/assemble) — each step is
    tagged with its chapter (the fragment it came from; app-shell steps
    join the chapter they precede) so assemble.py renders one video per
    chapter, and video colours default to the composed app's AppStyle
    palette when the manifest sets none, and
  * a generated Dart steps file for the app's committed integration_test
    runner (``integration_test/tour_steps.g.dart``).

Fragment resolution order (per fragment name ``F``):
  1. the composed SDK cache: ``.rokct/cache/F/templates/tour/F.tour.yaml``
     (any ``*.tour.yaml`` in that directory is accepted as a fallback);
  2. the SDK's source repo via the GitHub contents API, first at
     ``--fragments-ref`` and then at ``--fallback-ref`` (repo + subpath are
     read from the app's composer.json) — this covers windows where a
     fragment exists on a branch but the composed cache pin predates it;
  3. otherwise the fragment is SKIPPED with a loud log line, never a
     failure — apps adopt fragments gradually.

Schema documentation lives in scripts/tour/README.md.
"""

import argparse
import base64
import glob
import json
import os
import re
import sys
import urllib.error
import urllib.request

try:
    import yaml
except ImportError:  # pragma: no cover - CI installs pyyaml explicitly
    print("::error::merge_fragments.py requires pyyaml (pip install pyyaml)")
    sys.exit(1)

KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
HIGHLIGHT_RE = re.compile(r"\*([^*\n]+)\*")
VALID_ACTIONS = ("wait", "route", "dart")
DEFAULT_SETTLE_SECONDS = 5
# One caption beat per still in the video (WhatsApp-status pacing);
# video.beat_seconds in the manifest overrides it.
DEFAULT_BEAT_SECONDS = 4.0
# Brand-colour derivation from the composed app sources: named Color args
# inside the app's AppStyle.injectBrandColors(...) call, and base_sdk's own
# AppStyle field defaults (`static Color _primary = const Color(0xFFFF6600)`).
COLOR_ARG_RE = re.compile(r"(\w+)\s*:\s*(?:const\s+)?Color\(\s*0x([0-9A-Fa-f]{8})\s*\)")
APP_STYLE_COLOR_RE = re.compile(
    r"static\s+Color\s+_?(primary|surfaceDark)\s*=\s*(?:const\s+)?Color\(\s*0x([0-9A-Fa-f]{8})\s*\)"
)


def log(msg):
    print(f"[tour-merge] {msg}", flush=True)


def warn(msg):
    # GitHub annotation when running in Actions, plain line otherwise.
    prefix = "::warning::" if os.environ.get("GITHUB_ACTIONS") else "[tour-merge][warn] "
    print(f"{prefix}{msg}", flush=True)


def fail(msg):
    prefix = "::error::" if os.environ.get("GITHUB_ACTIONS") else "[tour-merge][error] "
    print(f"{prefix}{msg}", flush=True)
    sys.exit(1)


def clean_sdk_name(name):
    """Mirror the composer's clean_sdk_name (lms_sdk -> lms)."""
    if name.endswith("_sdk"):
        return name[: -len("_sdk")]
    if name.endswith("_sdks"):
        return name[: -len("_sdks")]
    return name


def load_yaml(path_or_text, source):
    try:
        if isinstance(path_or_text, bytes):
            data = yaml.safe_load(path_or_text.decode("utf-8"))
        elif os.path.exists(path_or_text):
            with open(path_or_text, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        else:
            data = yaml.safe_load(path_or_text)
    except yaml.YAMLError as e:
        fail(f"invalid YAML in {source}: {e}")
    if not isinstance(data, dict):
        fail(f"{source} must be a YAML mapping, got {type(data).__name__}")
    return data


def composer_sdk_index(composer_path):
    """clean sdk name -> {owner_repo, subpath} from composer.json."""
    index = {}
    if not composer_path or not os.path.exists(composer_path):
        return index
    try:
        with open(composer_path, "r", encoding="utf-8") as f:
            composer = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        warn(f"could not read composer.json ({e}); remote fragment fallback disabled")
        return index
    for sdk in composer.get("sdks", []):
        if not isinstance(sdk, dict) or not sdk.get("enabled", True):
            continue
        git_url = sdk.get("git", "")
        m = re.search(r"github\.com[:/]+([^/]+)/([^/.]+)", git_url)
        if not m:
            continue
        owner, repo = m.group(1), m.group(2)
        # path like ../agent/lms/dart -> subpath lms/dart
        path = (sdk.get("path") or "").replace("\\", "/")
        parts = [p for p in path.split("/") if p not in ("", "..", ".")]
        if parts and parts[0] == repo:
            parts = parts[1:]
        index[clean_sdk_name(sdk.get("name", ""))] = {
            "owner": owner,
            "repo": repo,
            "subpath": "/".join(parts),
        }
    return index


def fetch_remote_fragment(entry, name, refs, token):
    """Fetch <subpath>/templates/tour/<name>.tour.yaml from GitHub, trying refs in order."""
    if not entry:
        return None
    rel = f"{entry['subpath']}/templates/tour/{name}.tour.yaml".lstrip("/")
    for ref in refs:
        if not ref:
            continue
        url = (
            f"https://api.github.com/repos/{entry['owner']}/{entry['repo']}"
            f"/contents/{rel}?ref={ref}"
        )
        req = urllib.request.Request(url)
        req.add_header("Accept", "application/vnd.github.v3+json")
        req.add_header("User-Agent", "rokct-guided-tour")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.load(resp)
            content = base64.b64decode(payload.get("content", ""))
            log(f"fragment '{name}': fetched from {entry['owner']}/{entry['repo']}@{ref} ({rel})")
            return load_yaml(content, f"{entry['owner']}/{entry['repo']}@{ref}:{rel}")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                log(f"fragment '{name}': not found at {entry['owner']}/{entry['repo']}@{ref}")
                continue
            warn(f"fragment '{name}': HTTP {e.code} fetching {url}")
        except (urllib.error.URLError, OSError, ValueError) as e:
            warn(f"fragment '{name}': fetch error from {url}: {e}")
    return None


def resolve_fragment(name, cache_dir, sdk_index, refs, token):
    # 1. composed cache — the SDK named after the fragment first
    tour_dir = os.path.join(cache_dir, name, "templates", "tour")
    exact = os.path.join(tour_dir, f"{name}.tour.yaml")
    if os.path.exists(exact):
        log(f"fragment '{name}': using composed cache copy {exact}")
        return load_yaml(exact, exact)
    candidates = sorted(glob.glob(os.path.join(tour_dir, "*.tour.yaml")))
    if candidates:
        log(f"fragment '{name}': using composed cache copy {candidates[0]}")
        return load_yaml(candidates[0], candidates[0])
    # 1b. any composed SDK may ship the fragment: one SDK can carry several
    # (e.g. lms's templates/tour/ holds lms.tour.yaml AND
    # lms_partner.tour.yaml), so scan the whole cache for <name>.tour.yaml.
    matches = sorted(
        glob.glob(os.path.join(cache_dir, "*", "**", "tour", f"{name}.tour.yaml"), recursive=True)
    )
    owners = sorted({os.path.relpath(m, cache_dir).split(os.sep)[0] for m in matches})
    if len(owners) > 1:
        fail(
            f"fragment '{name}': shipped by multiple composed SDKs ({', '.join(owners)}) — "
            f"fragment file names must be unique across the composed SDKs"
        )
    if matches:
        log(f"fragment '{name}': using composed cache copy {matches[0]} (SDK '{owners[0]}')")
        return load_yaml(matches[0], matches[0])
    # 2. remote
    fragment = fetch_remote_fragment(sdk_index.get(name), name, refs, token)
    if fragment is not None:
        return fragment
    # 3. skip
    warn(
        f"fragment '{name}': no tour fragment found in the composed cache or the SDK repo — "
        f"skipping its steps (this SDK has not adopted guided tours yet)"
    )
    return None


def read_text(path):
    """File content, or '' when unreadable — colour derivation is best-effort."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def inject_call_args(text):
    """Named Color args inside the first injectBrandColors(...) call."""
    idx = text.find("injectBrandColors(")
    if idx < 0:
        return {}
    start = idx + len("injectBrandColors(")
    depth, end = 1, start
    while end < len(text) and depth > 0:
        if text[end] == "(":
            depth += 1
        elif text[end] == ")":
            depth -= 1
        end += 1
    return {m.group(1): m.group(2) for m in COLOR_ARG_RE.finditer(text[start : end - 1])}


def derive_brand_colors(cache_dir, theme_path):
    """Derive video brand/accent colours from the composed app sources.

    Used only for colour keys the manifest does not set explicitly. Two
    sources, per-app values first:

      1. the app's composed theme shim (lib/presentation/theme/theme.dart),
         whose AppStyle.injectBrandColors(...) call carries the app's own
         palette overrides;
      2. base_sdk's AppStyle field defaults in the composed cache
         (<cache-dir>/base/lib/src/presentation/theme/app_style.dart).

    accent_color <- primary, brand_color <- surfaceDark (ARGB hex in Dart,
    emitted as #RRGGBB). Returns a possibly-empty dict; assemble.py keeps
    its built-in defaults for anything missing.
    """
    app_args = inject_call_args(read_text(theme_path)) if theme_path else {}
    app_style_path = os.path.join(
        cache_dir, "base", "lib", "src", "presentation", "theme", "app_style.dart"
    )
    defaults = {m.group(1): m.group(2) for m in APP_STYLE_COLOR_RE.finditer(read_text(app_style_path))}
    derived = {}
    for out_key, dart_name in (("accent_color", "primary"), ("brand_color", "surfaceDark")):
        argb = app_args.get(dart_name) or defaults.get(dart_name)
        if argb:
            source = theme_path if dart_name in app_args else app_style_path
            derived[out_key] = "#" + argb[-6:].upper()
            log(f"video {out_key}: {derived[out_key]} derived from AppStyle {dart_name} ({source})")
    return derived


def substitute(text, placeholders):
    if not isinstance(text, str):
        return text
    for key, value in placeholders.items():
        text = text.replace("{" + key + "}", value)
    return text


def extract_highlight(caption, origin, key):
    """Pull one *marked* phrase out of a caption.

    ``caption: "Rewatch *past lessons* whenever you like."`` renders the
    marked words in the brand accent colour in the tour video. The markers
    are stripped here, so the guide, the resolved captions and captions
    without any markup all stay plain text exactly as before.
    """
    matches = HIGHLIGHT_RE.findall(caption)
    if not matches:
        return caption, ""
    if len(matches) > 1:
        warn(f"{origin}: step '{key}' marks {len(matches)} phrases — only the first is highlighted")
    plain = HIGHLIGHT_RE.sub(lambda m: m.group(1), caption)
    return plain, matches[0].strip()


def normalize_step(raw, origin, placeholders):
    if not isinstance(raw, dict):
        fail(f"{origin}: step must be a mapping")
    key = raw.get("key")
    if not key or not KEY_RE.match(str(key)):
        fail(f"{origin}: step key {key!r} must match {KEY_RE.pattern}")
    action = raw.get("action", "wait")
    if action not in VALID_ACTIONS:
        fail(f"{origin}: step '{key}' has unknown action {action!r} (valid: {VALID_ACTIONS})")
    route = raw.get("route")
    if action == "route":
        if not isinstance(route, str) or not route.startswith("/"):
            fail(f"{origin}: step '{key}' action=route needs a route starting with '/'")
        if "'" in route or "\\" in route or "$" in route:
            fail(f"{origin}: step '{key}' route contains characters not allowed in a route literal")
    dart = raw.get("dart")
    if action == "dart" and not (isinstance(dart, str) and dart.strip()):
        fail(f"{origin}: step '{key}' action=dart needs a non-empty dart block")
    try:
        settle = float(raw.get("settle", DEFAULT_SETTLE_SECONDS))
    except (TypeError, ValueError):
        fail(f"{origin}: step '{key}' settle must be a number of seconds")
    settle = max(0.0, min(60.0, settle))
    screenshot = bool(raw.get("screenshot", True))
    caption, highlight = extract_highlight(
        substitute(raw.get("caption") or "", placeholders).strip(), origin, key
    )
    return {
        "key": str(key),
        "title": substitute(raw.get("title") or "", placeholders).strip(),
        "caption": caption,
        "highlight": highlight,
        "action": action,
        "route": route if action == "route" else None,
        "dart": dart if action == "dart" else None,
        "settle_ms": int(settle * 1000),
        "screenshot": screenshot,
        "origin": origin,
    }


DART_HEADER = """\
// GENERATED FILE - DO NOT EDIT BY HAND.
//
// Generated by RokctAI/shared-workflows scripts/tour/merge_fragments.py from
// this app's tour/app.tour.yaml plus the tour fragments shipped by the
// composed SDKs (each SDK's templates/tour/<sdk>.tour.yaml). CI regenerates
// it on every guided-tour run; the committed copy exists so the repo
// analyzes and compiles without running the merge first.
//
// ignore_for_file: unused_import, always_specify_types, avoid_redundant_argument_values
// ignore_for_file: unawaited_futures, use_build_context_synchronously
// ignore_for_file: implementation_imports, directives_ordering, depend_on_referenced_packages

import 'package:auto_route/auto_route.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
"""


def indent_block(code, pad):
    lines = []
    for line in code.rstrip("\n").split("\n"):
        lines.append((pad + line) if line.strip() else "")
    return "\n".join(lines)


def emit_dart(steps, setup, extra_imports):
    out = [DART_HEADER]
    for imp in sorted(set(extra_imports)):
        out.append(imp)
    out.append("")
    out.append(
        "typedef TourAction = Future<void> Function(\n"
        "    WidgetTester tester, StackRouter router);"
    )
    out.append("")
    out.append("class TourStep {")
    out.append("  const TourStep(this.key, this.settleMs, this.screenshot, this.action);")
    out.append("")
    out.append("  final String key;")
    out.append("  final int settleMs;")
    out.append("")
    out.append("  /// False for steps that only perform an action (no still captured).")
    out.append("  final bool screenshot;")
    out.append("  final TourAction action;")
    out.append("}")
    out.append("")
    out.append("/// Runs once before the app is launched.")
    out.append("Future<void> tourSetup() async {")
    if setup and setup.get("dart"):
        out.append(indent_block(setup["dart"], "  "))
    else:
        out.append("  // No app-level setup declared in tour/app.tour.yaml.")
    out.append("}")
    out.append("")
    out.append("final List<TourStep> tourSteps = <TourStep>[")
    for step in steps:
        shoot = "true" if step["screenshot"] else "false"
        out.append(
            f"  TourStep('{step['key']}', {step['settle_ms']}, {shoot},"
            f" (WidgetTester tester, StackRouter router) async {{"
        )
        if step["action"] == "route":
            out.append(f"    router.replaceNamed('{step['route']}');")
        elif step["action"] == "dart":
            out.append(indent_block(step["dart"], "    "))
        else:
            out.append("    // wait: settle only.")
        out.append("  }),")
    out.append("];")
    out.append("")
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-manifest", default="tour/app.tour.yaml")
    parser.add_argument("--composer", default="composer.json")
    parser.add_argument("--cache-dir", default=os.path.join(".rokct", "cache"))
    parser.add_argument(
        "--app-theme",
        default=os.path.join("lib", "presentation", "theme", "theme.dart"),
        help="composed theme shim parsed for brand colours when the manifest sets none",
    )
    parser.add_argument("--fragments-ref", default="")
    parser.add_argument("--fallback-ref", default="main")
    parser.add_argument("--token-env", default="MONOREPO_PAT")
    parser.add_argument("--out-json", default="tour.resolved.json")
    parser.add_argument("--out-dart", default="integration_test/tour_steps.g.dart")
    args = parser.parse_args()

    if not os.path.exists(args.app_manifest):
        fail(f"app tour manifest not found: {args.app_manifest}")
    manifest = load_yaml(args.app_manifest, args.app_manifest)

    app = manifest.get("app") or {}
    app_name = str(app.get("name") or "This app")
    app_tagline = str(app.get("tagline") or "")
    placeholders = {"app_name": app_name, "app_tagline": app_tagline}

    video = manifest.get("video") or {}
    setup = manifest.get("setup") or {}

    sdk_index = composer_sdk_index(args.composer)
    token = os.environ.get(args.token_env, "") or os.environ.get("GITHUB_TOKEN", "")
    refs = [args.fragments_ref, args.fallback_ref]

    steps = []
    imports = list(setup.get("imports") or [])
    entries = manifest.get("tour")
    if not isinstance(entries, list) or not entries:
        fail(f"{args.app_manifest}: 'tour' must be a non-empty list of steps/fragments")

    for entry in entries:
        if not isinstance(entry, dict):
            fail(f"{args.app_manifest}: each tour entry must be a mapping with 'step' or 'fragment'")
        if "fragment" in entry:
            name = clean_sdk_name(str(entry["fragment"]))
            fragment = resolve_fragment(name, args.cache_dir, sdk_index, refs, token)
            if fragment is None:
                continue
            imports.extend(fragment.get("imports") or [])
            for raw in fragment.get("steps") or []:
                step = normalize_step(raw, f"fragment '{name}'", placeholders)
                step["chapter"] = name
                steps.append(step)
        elif "step" in entry:
            step = normalize_step(entry["step"], args.app_manifest, placeholders)
            step["chapter"] = None  # app-shell step: chapter assigned below
            steps.append(step)
        else:
            fail(f"{args.app_manifest}: tour entry needs 'step' or 'fragment', got {list(entry)}")

    # Chapter assignment for app-shell steps: each video covers ONE chapter
    # (the steps contributed by one fragment). An app-shell step joins the
    # chapter it precedes (a welcome step before `fragment: auth` opens the
    # auth chapter); trailing app-shell steps join the chapter before them;
    # a tour with no fragments at all is a single 'app' chapter.
    next_chapter = None
    for step in reversed(steps):
        if step["chapter"]:
            next_chapter = step["chapter"]
        else:
            step["chapter"] = next_chapter
    prev_chapter = None
    for step in steps:
        if step["chapter"]:
            prev_chapter = step["chapter"]
        else:
            step["chapter"] = prev_chapter or "app"

    if not steps:
        fail("no tour steps resolved — nothing to run")
    seen = set()
    for step in steps:
        if step["key"] in seen:
            fail(f"duplicate step key '{step['key']}' (from {step['origin']})")
        seen.add(step["key"])

    visible = [s for s in steps if s["screenshot"]]
    if not visible:
        fail("every resolved step is screenshot: false — the tour would produce no stills")

    # Branding colours: explicit manifest keys win; otherwise they are
    # derived from the composed app's AppStyle (see derive_brand_colors),
    # and assemble.py's built-in defaults cover anything still missing.
    brand_color = str(video.get("brand_color") or "").strip()
    accent_color = str(video.get("accent_color") or "").strip()
    if not (brand_color and accent_color):
        derived = derive_brand_colors(args.cache_dir, args.app_theme)
        brand_color = brand_color or derived.get("brand_color", "")
        accent_color = accent_color or derived.get("accent_color", "")

    resolved = {
        "app": {
            "name": app_name,
            "tagline": app_tagline,
            # Optional repo-relative logo path for the video end card;
            # assemble.py skips the image gracefully when it does not exist.
            "logo": str(app.get("logo") or "").strip(),
        },
        "video": {
            # No hook means no hook card — assemble.py skips it gracefully.
            "hook": substitute(str(video.get("hook") or ""), placeholders).strip(),
            # One ~4s caption beat per still (WhatsApp-status pacing);
            # video.beat_seconds overrides. The old video.seconds_per_step
            # key (fixed-total-window pacing) is ignored.
            "beat_seconds": float(video.get("beat_seconds") or DEFAULT_BEAT_SECONDS),
            "brand_color": brand_color,
            "accent_color": accent_color,
            # Optional one-line offer/CTA; with a logo or an offer present
            # each chapter video closes on a ~3s end card.
            "offer": substitute(str(video.get("offer") or ""), placeholders).strip(),
        },
        "steps": [
            {
                "index": i + 1,
                "key": s["key"],
                "title": s["title"] or s["key"].replace("_", " ").title(),
                "caption": s["caption"],
                "highlight": s["highlight"],
                "settle_ms": s["settle_ms"],
                "action": s["action"],
                "route": s["route"],
                "chapter": s["chapter"],
            }
            for i, s in enumerate(visible)
        ],
        "total_steps_including_hidden": len(steps),
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.out_json)), exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(resolved, f, indent=2)
        f.write("\n")
    log(f"wrote {args.out_json} ({len(visible)} screenshot steps, {len(steps)} total)")

    dart = emit_dart(steps, setup, imports)
    os.makedirs(os.path.dirname(os.path.abspath(args.out_dart)), exist_ok=True)
    with open(args.out_dart, "w", encoding="utf-8", newline="\n") as f:
        f.write(dart)
    log(f"wrote {args.out_dart}")

    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a", encoding="utf-8") as f:
            f.write(f"expected_screenshots={len(visible)}\n")
            f.write(f"total_steps={len(steps)}\n")


if __name__ == "__main__":
    main()

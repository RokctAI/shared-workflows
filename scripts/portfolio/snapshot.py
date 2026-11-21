#!/usr/bin/env python3
# Copyright 2026 ROKCT INTELLIGENCE (PTY) LTD
"""Weekly, change-only snapshot of the CORTEX portfolio (hosting_sdk 1.27.0 /portfolio).

Run by .github/workflows/portfolio-weekly.yml against a checkout of the
registry repo (RokctAI/hosting). It reads every showcase card the sites
announced (showcase/*.json, curated in each site's own repo) and the print
work kept on the CORTEX site itself (portfolio/print.json), fetches every
picture a card names, and compares the lot with the last version
(portfolio/current.json).

  * Nothing changed  -> nothing is written; `changed=false`.
  * Something changed -> a new version YYYY.WW (ISO week) is written to
    portfolio/current.json and portfolio/versions/<version>.json, and every
    picture is copied to <assets>/<version>/ so the version is frozen: a
    site changing its screenshots later never changes an old version.

Sanity checks (Ray 2026-11-21: public work needs no approval gate, but a
broken site must not reach a tender PDF): every picture must answer 200,
look like an image and not be tiny. A card that fails keeps its last good
version; a new card that fails is left out until it passes. Both are named
in the version's notes, never silently dropped.

Usage: snapshot.py --registry DIR --assets DIR --assets-base URL [--today YYYY-MM-DD]
Prints `changed=true|false` and `version=<id>` for $GITHUB_OUTPUT.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

MIN_BYTES = 2048
IMAGE_EXT = {"webp": "image/webp", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "avif": "image/avif"}
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def raw(repo: str, branch: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{path.lstrip('/')}"


def pictures(card: dict) -> dict[str, str]:
    """Every picture a card names, as {slot: url}. Same rules as studio-showcase.ts."""
    repo = card.get("repo", "")
    out: dict[str, str] = {}
    shots = card.get("shots") if isinstance(card.get("shots"), dict) else {}
    branch = shots.get("branch")
    for slot in ("desktop", "phone"):
        if branch and isinstance(shots.get(slot), str):
            out[slot] = raw(repo, branch, shots[slot])
    logo = card.get("logo") if isinstance(card.get("logo"), dict) else None
    if logo:
        lb = logo.get("branch") or branch
        for slot in ("light", "dark"):
            if lb and isinstance(logo.get(slot), str):
                out[f"logo-{slot}"] = raw(repo, lb, logo[slot])
    for i, app in enumerate(card.get("apps") or []):
        if isinstance(app, dict) and isinstance(app.get("phone"), str):
            out[f"app-{i}"] = raw(app.get("repo") or repo, app.get("branch") or "main", app["phone"])
    return out


def fetch(url: str) -> bytes | None:
    """The picture's bytes, or None when it is missing, not an image, or too small."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "cortex-portfolio-snapshot"})
        with urllib.request.urlopen(req, timeout=30) as r:
            if r.status != 200:
                return None
            ctype = r.headers.get("Content-Type", "")
            body = r.read()
    except Exception:
        return None
    ext = url.rsplit(".", 1)[-1].lower()
    if ext not in IMAGE_EXT and not ctype.startswith("image/"):
        return None
    return body if len(body) >= MIN_BYTES else None


def version_id(today: dt.date) -> str:
    y, w, _ = today.isocalendar()
    return f"{y}.{w:02d}"


def load_json(p: Path, default):
    try:
        return json.loads(p.read_text("utf8"))
    except Exception:
        return default


def snapshot(registry: Path, assets: Path, assets_base: str, today: dt.date, fetcher=fetch) -> tuple[bool, str, dict | None]:
    prev = load_json(registry / "portfolio" / "current.json", None)
    prev_items = {i["repo"].lower(): i for i in (prev or {}).get("items", []) if isinstance(i, dict) and "repo" in i}
    version = version_id(today)
    if prev and prev.get("version", "").split("-")[0] == version:
        # A second change in the same week (a rerun): keep the week, add a letter.
        last = prev.get("version", "")
        letter = last[-1] if "-" in last else "a"
        version = f"{version}-{chr(ord(letter) + 1)}"

    items: list[dict] = []
    notes: list[str] = []
    staged: dict[str, bytes] = {}
    for f in sorted((registry / "showcase").glob("*.json")):
        card = load_json(f, None)
        if not isinstance(card, dict) or not REPO_RE.match(str(card.get("repo", ""))):
            continue
        key = card["repo"].lower()
        pics = pictures(card)
        h = hashlib.sha256(json.dumps(card, sort_keys=True).encode())
        got: dict[str, bytes] = {}
        bad = []
        for slot, url in sorted(pics.items()):
            body = fetcher(url)
            if body is None:
                bad.append(slot)
            else:
                got[slot] = body
                h.update(slot.encode() + hashlib.sha256(body).digest())
        if bad:
            if key in prev_items:
                items.append(prev_items[key])
                notes.append(f"{card.get('name', key)}: kept last good version ({', '.join(bad)} failed the check)")
            else:
                notes.append(f"{card.get('name', key)}: left out until its pictures pass ({', '.join(bad)} failed)")
            continue
        digest = h.hexdigest()
        if key in prev_items and prev_items[key].get("hash") == digest:
            items.append(prev_items[key])
            continue
        frozen = {}
        for slot, body in got.items():
            ext = pics[slot].rsplit(".", 1)[-1].lower()
            name = f"{key.replace('/', '__')}-{slot}.{ext if ext in IMAGE_EXT else 'png'}"
            staged[name] = body
            frozen[slot] = f"{assets_base.rstrip('/')}/{version}/{name}"
        items.append({"repo": card["repo"], "hash": digest, "since": version, "card": card, "pictures": frozen})

    print_work = load_json(registry / "portfolio" / "print.json", [])
    if not isinstance(print_work, list):
        print_work = []

    now_keys = {i["repo"].lower(): i for i in items}
    changes: list[str] = []
    for k, i in now_keys.items():
        name = i["card"].get("name", i["repo"])
        if k not in prev_items:
            changes.append(f"Added {name}")
        elif prev_items[k].get("hash") != i.get("hash"):
            changes.append(f"Updated {name}")
    for k, i in prev_items.items():
        if k not in now_keys:
            changes.append(f"Removed {i['card'].get('name', i['repo'])}")
    if prev is not None and json.dumps(print_work, sort_keys=True) != json.dumps(prev.get("print", []), sort_keys=True):
        changes.append("Updated print work")

    if prev is not None and not changes:
        return False, prev.get("version", ""), None

    doc = {
        "version": version,
        "date": today.isoformat(),
        "previous": (prev or {}).get("version"),
        "changes": changes or ["First version"],
        "notes": notes,
        "items": items,
        "print": print_work,
    }
    out_dir = assets / version
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, body in staged.items():
        (out_dir / name).write_bytes(body)
    text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    (registry / "portfolio" / "versions").mkdir(parents=True, exist_ok=True)
    (registry / "portfolio" / "current.json").write_text(text, "utf8")
    (registry / "portfolio" / "versions" / f"{version}.json").write_text(text, "utf8")
    return True, version, doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", required=True)
    ap.add_argument("--assets", required=True)
    ap.add_argument("--assets-base", required=True)
    ap.add_argument("--today")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.today) if a.today else dt.datetime.now(dt.timezone.utc).date()
    changed, version, doc = snapshot(Path(a.registry), Path(a.assets), a.assets_base, today)
    print(f"changed={'true' if changed else 'false'}")
    print(f"version={version}")
    if doc:
        for line in doc["changes"] + doc["notes"]:
            print(f"# {line}", file=sys.stderr)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as fh:
            fh.write(f"changed={'true' if changed else 'false'}\nversion={version}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

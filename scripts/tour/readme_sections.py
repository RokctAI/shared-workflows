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
"""Regenerate the README's marker-delimited generated sections.

Run by universal-guided-tour.yml just before the tour's output commit, so
the README always reflects the assets that same commit ships. It owns TWO
marker blocks in the caller repo's README.md and never touches a byte
outside them (same contract as the composer's ``@generated-recompose``
block):

``@generated-store-description-start/end``
    The Play listing's full description, taken from
    ``marketing/store/listing/en-US/full_description.txt`` with the file's
    leading comment/blank lines stripped (the same convention
    universal-play-deploy uses), rendered under a ``## About`` heading and
    wrapped to 80 columns. While the listing file holds only comments the
    block stays empty; the real copy appears here automatically on the
    tour run after it lands.

``@generated-tour-gallery-start/end``
    A pure-Markdown 3-column gallery of the tour's styled store stills
    (``marketing/tour/store/NN-key.png``; falls back to the naked
    ``marketing/tour/screenshots/`` only when store/ has no stills).
    Captions derive from the filename slug (``06-schedule`` -> "Schedule").
    An optional curation manifest next to the media,
    ``marketing/tour/readme_gallery.yml``, can exclude stills and override
    captions - see MANIFEST FORMAT below. Everything not excluded is
    included, so new tour steps appear in the README automatically.

Blocks whose source is missing entirely (no listing file / no stills) are
skipped: an existing marker block is left untouched and none is created.
Output is deterministic and idempotent (LF endings, every generated line
<= 80 columns so default markdownlint MD013 passes; no inline HTML beyond
the marker comments, so MD033 passes too). If the markers are absent they
are inserted before the first ``## `` heading (description first, gallery
after it), or appended at the end of the README.

MANIFEST FORMAT (a deliberately tiny YAML subset - full-line comments,
one ``exclude:`` list and one ``captions:`` map; no nesting, no inline
collections, values may be quoted)::

    exclude:
      - 04-auth_reset_password      # .png suffix optional
    captions:
      07-courses: Subjects

Usage::

    python3 readme_sections.py [--repo-root PATH]
"""

import argparse
import re
import sys
import textwrap
from pathlib import Path

WIDTH = 80

DESC_START = "<!-- @generated-store-description-start -->"
DESC_END = "<!-- @generated-store-description-end -->"
GALLERY_START = "<!-- @generated-tour-gallery-start -->"
GALLERY_END = "<!-- @generated-tour-gallery-end -->"

LISTING = Path("marketing/store/listing/en-US/full_description.txt")
STORE_DIR = Path("marketing/tour/store")
SCREENSHOTS_DIR = Path("marketing/tour/screenshots")
MANIFEST = Path("marketing/tour/readme_gallery.yml")
FEATURE_GUIDE = Path("marketing/tour/feature-guide.md")

STILL_RE = re.compile(r"^\d+[-_].+\.png$")
COLUMNS = 3


# ---------------------------------------------------------------------------
# Curation manifest (tiny YAML subset; see module docstring).
# ---------------------------------------------------------------------------

def _unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def _key(name):
    """Normalise a still name for matching: basename, no .png suffix."""
    name = name.rsplit("/", 1)[-1]
    return name[:-4] if name.endswith(".png") else name


def load_manifest(path):
    """Return (excludes, captions) from the optional curation manifest."""
    excludes, captions = set(), {}
    if not path.is_file():
        return excludes, captions
    section = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if not raw[0].isspace():
            head = raw.split(":", 1)[0].strip()
            section = head if head in ("exclude", "captions") else None
            continue
        line = raw.strip()
        if section == "exclude" and line.startswith("- "):
            excludes.add(_key(_unquote(line[2:].split("  #", 1)[0])))
        elif section == "captions" and ":" in line:
            key, _, value = line.partition(":")
            captions[_key(_unquote(key))] = _unquote(value)
    return excludes, captions


# ---------------------------------------------------------------------------
# Store-description block.
# ---------------------------------------------------------------------------

def strip_leading_comments(text):
    """Drop LEADING comment/blank lines - the play-deploy convention."""
    lines = text.splitlines()
    start = 0
    while start < len(lines) and (
        not lines[start].strip() or lines[start].lstrip().startswith("#")
    ):
        start += 1
    return "\n".join(lines[start:]).rstrip()


_BULLET_RE = re.compile(r"^([-*•‣▪]|\d+[.)])\s+")


def wrap_description(text):
    """Wrap description text to WIDTH columns, preserving paragraphs.

    Play copy is plain text: paragraphs are blank-line separated, and any
    line starting with a bullet-ish marker (•, -, *, 1.) is one item of a
    list. Bullet runs become real Markdown lists (dash bullets; numbered
    markers kept) surrounded by blank lines, so default markdownlint
    (MD032 and friends) passes and readers get real bullets.
    """
    out = []
    for paragraph in re.split(r"\n\s*\n", text):
        para_lines = [l.strip() for l in paragraph.splitlines() if l.strip()]
        runs = []  # (is_bullet_run, [lines])
        for line in para_lines:
            is_bullet = bool(_BULLET_RE.match(line))
            if runs and runs[-1][0] == is_bullet:
                runs[-1][1].append(line)
            else:
                runs.append((is_bullet, [line]))
        for is_bullet, run in runs:
            if out:
                out.append("")
            wrap = lambda s, indent: textwrap.wrap(  # noqa: E731
                s,
                width=WIDTH,
                subsequent_indent=indent,
                break_long_words=False,
                break_on_hyphens=False,
            )
            if is_bullet:
                for item in run:
                    match = _BULLET_RE.match(item)
                    marker = match.group(1)
                    rest = item[match.end() :].strip()
                    prefix = f"{marker} " if marker[0].isdigit() else "- "
                    out.extend(wrap(prefix + rest, "  "))
            else:
                out.extend(wrap(" ".join(run), ""))
    return out


def build_description_block(repo_root):
    """Return the description block's inner lines, or None to skip."""
    src = repo_root / LISTING
    if not src.is_file():
        return None
    body = strip_leading_comments(src.read_text(encoding="utf-8"))
    if not body:
        return []
    return ["## About", ""] + wrap_description(body)


# ---------------------------------------------------------------------------
# Tour-gallery block.
# ---------------------------------------------------------------------------

def derive_caption(stem):
    slug = re.sub(r"^\d+[-_]*", "", stem) or stem
    words = [w for w in re.split(r"[-_]+", slug) if w]
    return " ".join(w[:1].upper() + w[1:] for w in words)


def fit_row(texts, render):
    """Front-trim the longest multi-word cell text until the row fits."""
    texts = list(texts)
    while len(render(texts)) > WIDTH:
        candidates = [
            (len(t), i) for i, t in enumerate(texts) if len(t.split()) > 1
        ]
        if not candidates:
            break
        _, index = max(candidates)
        texts[index] = " ".join(texts[index].split()[1:])
    return texts


def build_gallery_block(repo_root):
    """Return the gallery block's inner lines, or None to skip."""
    rel_dir = None
    for candidate in (STORE_DIR, SCREENSHOTS_DIR):
        directory = repo_root / candidate
        if directory.is_dir() and any(
            STILL_RE.match(p.name) for p in directory.iterdir()
        ):
            rel_dir = candidate
            break
    if rel_dir is None:
        return None

    excludes, captions = load_manifest(repo_root / MANIFEST)
    stills = sorted(
        p.name
        for p in (repo_root / rel_dir).iterdir()
        if STILL_RE.match(p.name) and _key(p.name) not in excludes
    )
    if not stills:
        return []

    entries = []  # (ref, caption, path)
    used_refs = set()
    for index, name in enumerate(stills):
        stem = _key(name)
        digits = re.match(r"\d+", stem)
        ref = "s" + (digits.group(0) if digits else str(index + 1))
        while ref in used_refs:
            ref += "x"
        used_refs.add(ref)
        entries.append(
            (ref, captions.get(stem) or derive_caption(stem), f"{rel_dir}/{name}")
        )

    def row(cells):
        # An empty (padding) cell renders as `| |` - two spaces there is an
        # MD060 table-column-style violation under the default rules.
        return "".join("| " + (c + " " if c else "") for c in cells) + "|"

    lines = [
        "## App tour",
        "",
        "Styled stills from the committed guided tour - regenerated on every",
        "tour run, so new screens appear here automatically.",
        "",
    ]
    for chunk_start in range(0, len(entries), COLUMNS):
        chunk = entries[chunk_start : chunk_start + COLUMNS]
        pad = COLUMNS - len(chunk)
        caps = [c for _, c, _ in chunk]
        refs = [r for r, _, _ in chunk]
        if chunk_start == 0:
            header = fit_row(caps, lambda t: row(t + [""] * pad))
            lines.append(row(header + [""] * pad))
            lines.append(row([":---:"] * COLUMNS))
        else:
            bolded = fit_row(
                caps, lambda t: row([f"**{c}**" for c in t] + [""] * pad)
            )
            lines.append(row([f"**{c}**" for c in bolded] + [""] * pad))
        alts = fit_row(
            caps,
            lambda t: row(
                [f"![{a}][{r}]" for a, r in zip(t, refs)] + [""] * pad
            ),
        )
        lines.append(
            row([f"![{a}][{r}]" for a, r in zip(alts, refs)] + [""] * pad)
        )
    lines.append("")
    if (repo_root / FEATURE_GUIDE).is_file():
        lines += [
            f"The full tour lives in the [feature guide]({FEATURE_GUIDE}),",
            f"with walkthrough videos alongside it in"
            f" [`{Path('marketing/tour')}/`](marketing/tour).",
        ]
    else:
        lines.append(
            "More tour outputs live in [`marketing/tour/`](marketing/tour)."
        )
    lines.append("")
    for ref, _, path in entries:
        lines.append(f"[{ref}]: {path}")
    return lines


# ---------------------------------------------------------------------------
# Marker-block surgery.
# ---------------------------------------------------------------------------

def render_block(start, end, inner):
    if inner:
        return [start] + inner + [end]
    return [start, end]


def apply_block(lines, start, end, inner, insert_after=None):
    """Replace the start..end marker block, or insert it if absent.

    ``insert_after`` is a line index to insert after (-1 for start of
    file); when None the block goes before the first ``## `` heading, or
    at the end of the file. Returns (lines, block_end_index).
    """
    block = render_block(start, end, inner)
    if start in lines and end in lines:
        first, last = lines.index(start), lines.index(end)
        if first < last:
            lines[first : last + 1] = block
            return lines, first + len(block) - 1
    if insert_after is None:
        anchor = next(
            (i for i, l in enumerate(lines) if l.startswith("## ")), len(lines)
        )
        # Step back over the blank run so the block sits one blank line
        # after the previous content.
        while anchor > 0 and not lines[anchor - 1].strip():
            anchor -= 1
    else:
        anchor = insert_after + 1
    insertion = ([""] if anchor > 0 and lines[anchor - 1].strip() else []) + block
    tail_gap = [""] if anchor < len(lines) and lines[anchor].strip() else []
    lines[anchor:anchor] = insertion + tail_gap
    return lines, anchor + len(insertion) - 1


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Regenerate the README's generated marker sections."
    )
    parser.add_argument("--repo-root", default=".", help="repo checkout root")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root)

    readme = repo_root / "README.md"
    if not readme.is_file():
        print("No README.md - nothing to do.")
        return 0

    original = readme.read_text(encoding="utf-8")
    lines = original.splitlines()

    description = build_description_block(repo_root)
    gallery = build_gallery_block(repo_root)

    desc_end_index = None
    if description is None:
        print(f"No {LISTING} - store-description block skipped.")
    else:
        lines, desc_end_index = apply_block(
            lines, DESC_START, DESC_END, description
        )
        state = "populated" if description else "empty (listing has no copy yet)"
        print(f"Store-description block {state}.")

    if gallery is None:
        print("No tour stills - gallery block skipped.")
    else:
        lines, _ = apply_block(
            lines, GALLERY_START, GALLERY_END, gallery, insert_after=desc_end_index
        )
        print(f"Tour-gallery block refreshed ({max(len(gallery) - 1, 0)} lines).")

    for line in (description or []) + (gallery or []):
        if len(line) > WIDTH and not re.match(r"\[s\w+\]: ", line):
            raise SystemExit(
                f"generated README line exceeds {WIDTH} columns: {line!r}"
            )

    updated = "\n".join(lines).rstrip("\n") + "\n"
    if updated != original:
        readme.write_text(updated, encoding="utf-8", newline="\n")
        print("README.md updated.")
    else:
        print("README.md already up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

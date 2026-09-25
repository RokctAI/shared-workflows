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
#
# Emits a Markdown "Build context" section for build-failure PRs/issues:
#   - the SDKs the app composed (composer.json sdks[] + installed versions
#     from .rokct/cache/install_state.json + resolved clone SHAs when present)
#   - the platform API `cmd` names referenced by the failing files / log
#   - an emulator screenshot link when one was produced (SCREENSHOT_URL env
#     or a local verification.png)
# Best effort by design: every source is optional and nothing here may ever
# fail the calling step. Usage: python3 build_failure_context.py [out.md]

import json
import os
import re
import subprocess
import sys

CMD_PATTERNS = [
    re.compile(r"""['"]?cmd['"]?\s*[:=]\s*['"]([A-Za-z_][\w.]*)['"]"""),
    re.compile(r"""/api/method/([A-Za-z_][\w.]*)"""),
]
ERROR_FILE = re.compile(r"(lib/[\w/.\-]+\.dart)")


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""


def clone_sha(name):
    for d in (f".rokct/cache/{name}", f".rokct/cache/{name}_sdk"):
        if os.path.isdir(os.path.join(d, ".git")):
            try:
                return subprocess.run(
                    ["git", "-C", d, "rev-parse", "--short", "HEAD"],
                    capture_output=True, text=True, timeout=10,
                ).stdout.strip()
            except Exception:
                return ""
    return ""


def sdk_section():
    composer = load_json("composer.json") or {}
    state = load_json(".rokct/cache/install_state.json") or {}
    installed = state.get("packages") or {}
    sdks = [s for s in (composer.get("sdks") or []) if isinstance(s, dict) and s.get("enabled")]
    names = [s.get("name") for s in sdks if s.get("name")]
    names += [n for n in installed if n not in names]
    if not names:
        return ["_No composed SDKs found (no composer.json sdks[] or install_state.json)._"]
    by_name = {s.get("name"): s for s in sdks}
    out = ["| SDK | Installed version | Source | Ref |", "|---|---|---|---|"]
    for n in names:
        s = by_name.get(n, {})
        p = installed.get(n) or {}
        ver = p.get("version", "-") if isinstance(p, dict) else "-"
        git = (s.get("git") or "").rstrip("/").removesuffix(".git").split("/")[-1]
        path = s.get("path") or ""
        while path.startswith(("../", "./")):
            path = path.split("/", 1)[1]
        if git and path.split("/", 1)[0].lower() == git.lower():
            path = path.split("/", 1)[1] if "/" in path else ""
        src = f"{git}/{path}".rstrip("/") if git else (path or "-")
        ref = s.get("ref") or s.get("branch") or "-"
        sha = clone_sha(n)
        if sha:
            ref = f"{ref} @ {sha}"
        out.append(f"| `{n}` | {ver} | `{src}` | `{ref}` |")
    if state.get("home_sdk"):
        out.append("")
        out.append(f"Home SDK: `{state.get('home_sdk')}`")
    return out


def cmd_section():
    log = read("build_log.txt")
    files = sorted(set(ERROR_FILE.findall(log)))
    cmds = {}
    for src, text in [("build log", log)] + [(f, read(f)) for f in files]:
        for pat in CMD_PATTERNS:
            for m in pat.findall(text):
                cmds.setdefault(m, set()).add(src)
    if not cmds:
        return ["_No platform API `cmd` names found in the build log or the failing files._"]
    out = []
    for c in sorted(cmds):
        where = ", ".join(f"`{w}`" if w != "build log" else w for w in sorted(cmds[c]))
        out.append(f"- `{c}` (in {where})")
    return out


def screenshot_section():
    url = os.environ.get("SCREENSHOT_URL", "").strip()
    if url:
        return [f"- Emulator screenshot: {url}"]
    if os.path.isfile("verification.png"):
        return ["- Emulator screenshot: `verification.png` (uploaded with this run's artifacts)"]
    return ["_No emulator screenshot was produced by this build._"]


def main():
    lines = ["", "## Build context", "", "### Composed SDK versions", ""]
    for fn in (sdk_section, cmd_section, screenshot_section):
        try:
            body = fn()
        except Exception as e:  # never fail the caller
            body = [f"_Could not collect: {e}_"]
        if fn is cmd_section:
            lines += ["", "### Platform API `cmd` names involved", ""]
        elif fn is screenshot_section:
            lines += ["", "### Emulator screenshot", ""]
        lines += body
    text = "\n".join(lines) + "\n"
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()

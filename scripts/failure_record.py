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
# Structured failure record for consumer build / verify / emulator jobs.
#
#   write   collects what the run knows into failure-record.json
#   render  turns a record (plus optional overlay fields) into Markdown for
#           failure PRs, the central build-failure issue and the SDK poller
#
# The record is additive: unknown fields stay null. Nothing here may ever
# fail the calling step - every error is swallowed and the script exits 0.
#
# Usage:
#   python3 failure_record.py write --out failure-record.json --stage build \
#       [--log build_log.txt] [--class build] [--screenshot-artifact NAME]
#   python3 failure_record.py render failure-record.json [--overlay JSON] \
#       [--out file.md]

import argparse
import json
import os
import re
import sys

SCHEMA_VERSION = 1
LOG_TAIL_LINES = 200
FAILURE_CLASSES = ("build", "runtime", "api", "contract", "compliance", "infra")

# An API failure only counts when the log shows both an endpoint and an
# error signal on the same line (or the line right after it).
# Every platform call goes through the gateway:
#   POST /api/v1/method/rokct.platform.api  {"cmd": "<name>", ...}
# The bare /api/method/<name> pattern is only a fallback.
GATEWAY_ENDPOINT = re.compile(
    r"/api/v1/method/rokct\.platform\.api\b(?:\?([^\s'\"]*))?"
)
GATEWAY_CMD = re.compile(r"""['"]?\bcmd['"]?\s*[:=]\s*['"]?([A-Za-z_][\w.]*)""")
GATEWAY_WINDOW = 3
API_ENDPOINT = re.compile(r"/api/method/([A-Za-z_][\w.]*)(?:\?([^\s'\"]*))?")
API_ERROR = re.compile(
    r"DioException|DioError|HTTP\s*[45]\d\d|status code (?:of )?[45]\d\d|"
    r"statusCode[:=]\s*[45]\d\d|\b[45]\d\d (?:Bad Request|Unauthorized|Forbidden|Not Found|"
    r"Internal Server Error|Bad Gateway|Service Unavailable)",
    re.IGNORECASE,
)
INFRA_SIGNALS = re.compile(
    r"Could not resolve host|ETIMEDOUT|ECONNRESET|No space left on device|"
    r"Timeout waiting for emulator|emulator.*(?:timed out|did not boot)|Broken pipe|"
    r"adb: device offline|rate limit exceeded|The runner has received a shutdown",
    re.IGNORECASE,
)
CONTRACT_SIGNALS = re.compile(
    r"contract (?:check|test|violation)|schema mismatch", re.IGNORECASE
)
COMPLIANCE_SIGNALS = re.compile(
    r"compliance (?:check|scan|violation)|license header", re.IGNORECASE
)
ERROR_LINE = re.compile(
    r"^(?:E \w+ on lib/|.*\bError:|.*\berror:|FAILURE:|.*Exception:|.*FAILED|.*❌)",
    re.IGNORECASE,
)


def _env(name):
    value = os.environ.get(name, "").strip()
    return value or None


def _read_lines(path):
    if not path:
        return []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()
    except Exception:
        return []


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def find_api_call(lines):
    """Return {"cmd", "args"} for the last API call that the log shows failing."""
    found = None
    for i, line in enumerate(lines):
        window = lines[i : i + 1 + GATEWAY_WINDOW]
        if not any(API_ERROR.search(w) for w in window):
            continue
        call = gateway_call(line, window) or fallback_call(line)
        if call:
            found = call
    return found


def gateway_call(line, window):
    m = GATEWAY_ENDPOINT.search(line)
    if not m:
        return None
    query_args = parse_args(m.group(1)) or {}
    query_cmd = query_args.pop("cmd", None)
    query_args = query_args or None
    for text in window:
        body = json_body(text)
        if body and body.get("cmd"):
            args = {k: v for k, v in body.items() if k != "cmd"}
            return {"cmd": str(body["cmd"]), "args": args or query_args}
    if query_cmd:
        return {"cmd": query_cmd, "args": query_args}
    for text in window:
        c = GATEWAY_CMD.search(text)
        if c:
            return {"cmd": c.group(1), "args": query_args}
    return None


def json_body(text):
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        body = json.loads(text[start : end + 1])
    except Exception:
        return None
    return body if isinstance(body, dict) else None


def fallback_call(line):
    m = API_ENDPOINT.search(line)
    if not m:
        return None
    return {"cmd": m.group(1), "args": parse_args(m.group(2))}


def parse_args(query):
    if not query:
        return None
    args = {}
    for part in query.split("&"):
        if not part:
            continue
        key, _, value = part.partition("=")
        args[key] = value
    return args or None


def error_summary(lines):
    for line in lines:
        if ERROR_LINE.search(line.strip()):
            return line.strip()[:500]
    for line in reversed(lines):
        if line.strip():
            return line.strip()[:500]
    return None


def classify(lines, default, api_call):
    text = "\n".join(lines[-LOG_TAIL_LINES * 5 :])
    if INFRA_SIGNALS.search(text):
        return "infra"
    if api_call:
        return "api"
    if CONTRACT_SIGNALS.search(text):
        return "contract"
    if COMPLIANCE_SIGNALS.search(text):
        return "compliance"
    return default if default in FAILURE_CLASSES else None


def composed_sdks():
    """Composed SDKs from composer.json + install_state.json, when present."""
    composer = _load_json("composer.json") or {}
    state = _load_json(".rokct/cache/install_state.json") or {}
    installed = state.get("packages") or {}
    out = []
    for s in composer.get("sdks") or []:
        if not isinstance(s, dict) or not s.get("enabled"):
            continue
        pkg = installed.get(s.get("name")) or {}
        out.append(
            {
                "name": s.get("name"),
                "git": s.get("git"),
                "ref": s.get("ref") or s.get("branch"),
                "version": pkg.get("version") if isinstance(pkg, dict) else None,
            }
        )
    return out


def runner_info():
    info = {
        "os": _env("RUNNER_OS"),
        "arch": _env("RUNNER_ARCH"),
        "name": _env("RUNNER_NAME"),
        "image": _env("ImageOS"),
        "image_version": _env("ImageVersion"),
    }
    emulator = {
        "api_level": _env("EMULATOR_API_LEVEL"),
        "target": _env("EMULATOR_TARGET"),
        "arch": _env("EMULATOR_ARCH"),
    }
    if any(emulator.values()):
        info["emulator"] = emulator
    return info


def build_record(opts):
    lines = _read_lines(opts.log)
    api_call = find_api_call(lines)
    screenshot = opts.screenshot_artifact
    if screenshot and opts.screenshot_file and not os.path.isfile(opts.screenshot_file):
        screenshot = None
    repo = _env("GITHUB_REPOSITORY")
    server = _env("GITHUB_SERVER_URL") or "https://github.com"
    run_id = _env("GITHUB_RUN_ID")
    return {
        "schema_version": SCHEMA_VERSION,
        "sdk": {
            "name": _env("SDK_NAME"),
            "from_version": _env("SDK_FROM_VERSION"),
            "to_version": _env("SDK_TO_VERSION"),
        },
        "composed_sdks": composed_sdks() or None,
        "consumer": {
            "repo": repo,
            "commit": _env("GITHUB_SHA"),
            "ref": _env("GITHUB_REF_NAME"),
        },
        "workflow": _env("GITHUB_WORKFLOW"),
        "job": opts.job or _env("GITHUB_JOB"),
        "stage": opts.stage,
        "run_url": f"{server}/{repo}/actions/runs/{run_id}"
        if repo and run_id
        else None,
        "cmd": api_call["cmd"] if api_call else None,
        "args": api_call["args"] if api_call else None,
        "error_summary": error_summary(lines),
        "log_tail": "\n".join(lines[-LOG_TAIL_LINES:]) or None,
        "screenshot_artifact": screenshot,
        "runner": runner_info(),
        "failure_class": classify(lines, opts.failure_class, api_call),
    }


def merge(base, overlay):
    """Overlay non-null values onto the record (nested one level)."""
    for key, value in (overlay or {}).items():
        if value is None:
            continue
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            for k, v in value.items():
                if v is not None:
                    base[key][k] = v
        else:
            base[key] = value
    return base


def _v(value):
    return f"`{value}`" if value not in (None, "", {}) else "_unknown_"


def render(record):
    r = record or {}
    sdk = r.get("sdk") or {}
    consumer = r.get("consumer") or {}
    runner = r.get("runner") or {}
    rows = [
        ("Failure class", r.get("failure_class")),
        ("SDK", sdk.get("name")),
        ("SDK version", _version_span(sdk)),
        ("Consumer", consumer.get("repo")),
        ("Commit", consumer.get("commit")),
        (
            "Workflow / job",
            " / ".join(x for x in (r.get("workflow"), r.get("job")) if x) or None,
        ),
        ("Stage", r.get("stage")),
        ("API cmd", r.get("cmd")),
        ("Screenshot artifact", r.get("screenshot_artifact")),
        ("Runner", _runner_text(runner)),
    ]
    out = ["", "## Failure record", "", "| Field | Value |", "|---|---|"]
    out += [f"| {k} | {_v(v)} |" for k, v in rows]
    if r.get("run_url"):
        out.append(f"| Run | {r['run_url']} |")
    if r.get("args"):
        out += ["", "**API args:** `" + json.dumps(r["args"], sort_keys=True) + "`"]
    out += _sdk_table(r.get("composed_sdks"))
    out += ["", "### Error summary", "", _v(r.get("error_summary"))]
    if r.get("log_tail"):
        tail = r["log_tail"].replace("````", "'```")
        out += [
            "",
            "<details><summary>Log tail</summary>",
            "",
            "````",
            tail,
            "````",
            "",
            "</details>",
        ]
    return "\n".join(out) + "\n"


def _version_span(sdk):
    a, b = sdk.get("from_version"), sdk.get("to_version")
    if a and b:
        return f"{a} -> {b}"
    return b or a


def _runner_text(runner):
    parts = [
        runner.get(k) for k in ("os", "arch", "image", "image_version") if runner.get(k)
    ]
    emu = runner.get("emulator") or {}
    if any(emu.values()):
        parts.append("emulator api " + "/".join(str(v) for v in emu.values() if v))
    return ", ".join(parts) or None


def _sdk_table(sdks):
    if not sdks:
        return []
    out = [
        "",
        "### Composed SDKs",
        "",
        "| SDK | Installed version | Source | Ref |",
        "|---|---|---|---|",
    ]
    for s in sdks:
        out.append(
            f"| {_v(s.get('name'))} | {_v(s.get('version'))} | {_v(s.get('git'))} | {_v(s.get('ref'))} |"
        )
    return out


def _write_text(path, text):
    if path:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    else:
        sys.stdout.write(text)


def cmd_write(opts):
    record = build_record(opts)
    _write_text(opts.out, json.dumps(record, indent=2, ensure_ascii=False) + "\n")


def cmd_render(opts):
    record = _load_json(opts.record) or {}
    overlay = None
    if opts.overlay:
        try:
            overlay = json.loads(opts.overlay)
        except Exception:
            overlay = None
    _write_text(opts.out, render(merge(record, overlay)))


def parse(argv):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command")
    w = sub.add_parser("write")
    w.add_argument("--out", default="failure-record.json")
    w.add_argument("--stage")
    w.add_argument("--job")
    w.add_argument("--log")
    w.add_argument("--class", dest="failure_class", default="build")
    w.add_argument("--screenshot-artifact")
    w.add_argument("--screenshot-file", default="verification.png")
    r = sub.add_parser("render")
    r.add_argument("record")
    r.add_argument("--overlay")
    r.add_argument("--out")
    return p.parse_args(argv)


def main(argv=None):
    try:
        opts = parse(argv if argv is not None else sys.argv[1:])
        if opts.command == "write":
            cmd_write(opts)
        elif opts.command == "render":
            cmd_render(opts)
    except SystemExit:
        pass
    except Exception as e:  # never fail the caller
        sys.stderr.write(f"failure_record: {e}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

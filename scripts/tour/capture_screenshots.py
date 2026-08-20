#!/usr/bin/env python3
# Copyright 2026 RokctAI
"""Watch adb logcat for guided-tour markers and capture a screenshot per step.

The integration_test tour runner prints ``TOUR_SHOT:<key>`` to logcat when a
screen has settled and then holds the frame still for a few seconds;
this watcher answers each marker with ``adb exec-out screencap -p`` (the
screencap path already proven by universal-flutter-verify on the same
headless-emulator setup). ``TOUR_COMPLETE:<n>`` ends the run.

Exit code is 0 whenever at least one screenshot was captured (partial tours
are committed with a warning; the calling shell decides what is fatal), and
1 when nothing at all was captured or the watcher itself failed.
"""

import argparse
import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time

SHOT_RE = re.compile(r"TOUR_SHOT:([A-Za-z0-9_]+)")
DONE_RE = re.compile(r"TOUR_COMPLETE:(\d+)")
ERROR_RE = re.compile(r"TOUR_ACTION_ERROR:([A-Za-z0-9_]+):(.*)")
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def log(msg):
    print(f"[tour-capture] {msg}", flush=True)


def warn(msg):
    prefix = "::warning::" if os.environ.get("GITHUB_ACTIONS") else "[tour-capture][warn] "
    print(f"{prefix}{msg}", flush=True)


def adb(args, serial, **kwargs):
    cmd = ["adb"]
    if serial:
        cmd += ["-s", serial]
    return subprocess.run(cmd + args, **kwargs)


def screencap(serial, dest, attempts=4):
    """Capture the device framebuffer to dest; returns True on a valid PNG."""
    for attempt in range(1, attempts + 1):
        try:
            result = adb(
                ["exec-out", "screencap", "-p"],
                serial,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            data = result.stdout or b""
            if result.returncode == 0 and data.startswith(PNG_MAGIC) and len(data) > 1024:
                with open(dest, "wb") as f:
                    f.write(data)
                return True
            log(
                f"screencap attempt {attempt}/{attempts} invalid "
                f"(rc={result.returncode}, {len(data)} bytes) — retrying"
            )
        except subprocess.TimeoutExpired:
            log(f"screencap attempt {attempt}/{attempts} timed out — retrying")
        time.sleep(1.5)
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="tour_screenshots")
    parser.add_argument("--expected", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=2100, help="overall seconds to wait")
    parser.add_argument("--serial", default=os.environ.get("ANDROID_SERIAL", ""))
    parser.add_argument("--logcat-dump", default="", help="write full logcat here on exit")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)

    # The driving shell sends SIGTERM once flutter test has exited (no more
    # markers are coming then) - treat it as a graceful "wrap up now" so the
    # manifest and the logcat dump below still get written.
    stop_requested = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop_requested.set())

    proc = None
    try:
        adb(["logcat", "-c"], args.serial, timeout=30)
    except Exception as e:  # noqa: BLE001 - stale buffer is not fatal
        log(f"logcat -c failed (continuing): {e}")

    cmd = ["adb"]
    if args.serial:
        cmd += ["-s", args.serial]
    cmd += ["logcat", "-v", "brief"]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        bufsize=1,
    )

    lines = queue.Queue()

    def reader():
        try:
            for line in proc.stdout:
                lines.put(line)
        except ValueError:
            pass
        lines.put(None)

    threading.Thread(target=reader, daemon=True).start()

    captured = []  # ordered list of keys
    manifest = {}
    complete = False
    deadline = time.monotonic() + args.timeout
    log(f"watching logcat for tour markers (expected={args.expected}, timeout={args.timeout}s)")

    while time.monotonic() < deadline:
        if stop_requested.is_set():
            log("stop requested (driver signalled test exit) — wrapping up")
            break
        try:
            line = lines.get(timeout=5)
        except queue.Empty:
            continue
        if line is None:
            log("logcat stream ended")
            break

        err = ERROR_RE.search(line)
        if err:
            warn(f"tour step '{err.group(1)}' action error on device: {err.group(2).strip()}")

        shot = SHOT_RE.search(line)
        if shot:
            key = shot.group(1)
            if key in manifest:
                log(f"duplicate marker for '{key}' — ignoring")
            else:
                index = len(captured) + 1
                dest = os.path.join(args.out, f"{index:02d}-{key}.png")
                if screencap(args.serial, dest):
                    captured.append(key)
                    manifest[key] = os.path.basename(dest)
                    log(f"captured {dest}")
                else:
                    warn(f"failed to capture a valid screenshot for step '{key}'")
            continue

        done = DONE_RE.search(line)
        if done:
            log(f"tour completed on device ({done.group(1)} steps ran)")
            complete = True
            break

    if not complete and not stop_requested.is_set() and time.monotonic() >= deadline:
        warn(f"tour capture timed out after {args.timeout}s")

    if proc and proc.poll() is None:
        proc.terminate()

    if args.logcat_dump:
        try:
            with open(args.logcat_dump, "w", encoding="utf-8", errors="replace") as f:
                dump = adb(
                    ["logcat", "-d"], args.serial,
                    stdout=subprocess.PIPE, timeout=60, text=True, errors="replace",
                )
                f.write(dump.stdout or "")
            log(f"full logcat written to {args.logcat_dump}")
        except Exception as e:  # noqa: BLE001
            log(f"logcat dump failed: {e}")

    with open(os.path.join(args.out, "capture_manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"captured": manifest, "order": captured, "complete": complete}, f, indent=2)
        f.write("\n")

    log(f"done: {len(captured)} screenshots captured (expected {args.expected})")
    if args.expected and len(captured) < args.expected:
        warn(f"captured {len(captured)}/{args.expected} tour screenshots")
    return 0 if captured else 1


if __name__ == "__main__":
    sys.exit(main())

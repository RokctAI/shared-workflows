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
"""Watch for guided-tour markers and capture a screenshot per step.

The integration_test tour runner emits ``TOUR_SHOT:<key>`` when a screen has
settled and then holds the frame still for a few seconds; this watcher
answers each marker with ``adb exec-out screencap -p`` (the screencap path
already proven by universal-flutter-verify on the same headless-emulator
setup). ``TOUR_COMPLETE:<n>`` ends the run.

Markers arrive on two transports and both are tailed:

* the device's logcat (the runner writes markers via ``/system/bin/log``);
* the host-side ``flutter test`` output (``--stdout-log FILE``, written by
  ``tee`` in the driving shell). Under ``flutter test`` Dart prints reach
  the HOST console rather than logcat, so this transport is the proven
  fallback (run 32386564857 showed markers host-side while logcat stayed
  empty).

Duplicate markers for the same key (one per transport) are ignored.

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
# AppNotRespondingDialog sets its window title to "Application Not
# Responding: <process>" and AppErrorDialog to "Application Error:
# <process>" (AOSP services/core/java/com/android/server/am/), so these two
# strings appear in a window dump ONLY while such a dialog is really in the
# stack - no other window prints them, which is what keeps this from firing
# on a clean run.
ANR_WINDOW_RE = re.compile(r"Application (?:Not Responding|Error): ?([^\s}]*)")
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


def anr_log(msg):
    print(f"[tour-anr] {msg}", flush=True)


def anr_warn(msg):
    prefix = "::warning::" if os.environ.get("GITHUB_ACTIONS") else ""
    print(f"{prefix}[tour-anr] WARNING: {msg}", flush=True)


def anr_error(msg):
    prefix = "::error::" if os.environ.get("GITHUB_ACTIONS") else ""
    print(f"{prefix}[tour-anr] ERROR: {msg}", flush=True)


def dumpsys_window(serial):
    """Return `dumpsys window`'s text, or None when it could not be read.

    `windows` is the narrow sub-command (just the window stack) and is what
    every current platform version answers; the bare form is the fallback for
    an image whose dump sub-commands differ, since it contains the same
    section. None means the check itself failed - never that the stack is
    clean.
    """
    for sub in (["shell", "dumpsys", "window", "windows"], ["shell", "dumpsys", "window"]):
        try:
            result = adb(
                sub, serial,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=30, text=True, errors="replace",
            )
        except (subprocess.TimeoutExpired, OSError):
            continue
        out = result.stdout or ""
        if result.returncode == 0 and out.strip():
            return out
    return None


def anr_dialog(serial):
    """The ANR/crash dialog sitting in the window stack right now.

    Returns "" when the stack is clean, the dialog's window title when one is
    up, and None when the check could not be made.

    `dumpsys window` is the primitive because it reports what is actually IN
    THE WINDOW STACK - which is precisely what a whole-framebuffer
    `adb exec-out screencap -p` will burn into the still. `dumpsys activity
    processes` was the alternative, but it reports process-level ANR
    BOOKKEEPING that outlives the dialog (an ANR already dismissed still shows
    there), so it answers a different question and would fail clean runs.
    """
    out = dumpsys_window(serial)
    if out is None:
        return None
    match = ANR_WINDOW_RE.search(out)
    return match.group(0).strip() if match else ""


def anr_guard(serial, key, dest, tally):
    """Verify the still just written to `dest` was not taken behind an ANR.

    Returns "" to keep the capture and the dialog's window title when the
    still was rejected (the file is renamed out of the way, never left where
    assemble.py could pick it up).

    Ordering is deliberate: the check runs AFTER `screencap`, not before. The
    tour holds each frame still for only a few seconds after emitting its
    marker, and putting a `dumpsys` round-trip in front of the capture would
    eat into that window on a loaded emulator - so the capture keeps exactly
    the timing it has today and the verdict is reached a moment later, while
    the dialog (which is modal and stays up until it is dismissed) is still
    there to be seen.

    One dismissal and one recapture are attempted before rejecting: the ANR
    dialog holds focus, so BACK goes to the dialog rather than the app, and its
    BACK action is "wait", which does not kill the process under test. A
    dialog that clears was transient, and clearing it also rescues every
    REMAINING still of the leg instead of losing the whole run to one hiccup.
    Exactly one attempt; a dialog that survives it rejects the still and fails
    the leg.

    Deliberately NOT `settings put global hide_error_dialogs 1`: that would
    take the dialog out of the frame while leaving the app just as hung, so
    the stills would look fine and a real regression would ship invisibly -
    the same trap the POST_NOTIFICATIONS grant avoids by granting one
    permission instead of `adb install -g`.
    """
    title = anr_dialog(serial)
    if title is None:
        tally["unchecked"] += 1
        anr_warn(
            f"could not check for an ANR dialog around step '{key}' "
            "(`dumpsys window` returned nothing usable) - the still is kept UNVERIFIED"
        )
        return ""
    if not title:
        tally["clean"] += 1
        return ""

    anr_log(f"'{title}' is in the window stack at step '{key}' - dismissing it and retrying the capture once")
    try:
        adb(
            ["shell", "input", "keyevent", "KEYCODE_BACK"], serial,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        anr_log(f"dismissal keyevent failed at step '{key}': {e}")
    time.sleep(2)

    # A failed RECHECK counts as still present: an ANR was just proven to be
    # up, and an unprovable dismissal is not grounds for keeping the frame.
    if anr_dialog(serial) == "" and screencap(serial, dest):
        tally["rescued"] += 1
        anr_warn(
            f"dismissed '{title}' at step '{key}' and recaptured with the window "
            "stack clean - no contaminated still was kept"
        )
        return ""

    tally["blocked"] += 1
    reject_still(dest)
    return title


def reject_still(dest):
    """Move a contaminated still out of the way of assemble.py.

    Renamed rather than deleted: assemble.py globs `<shots>/*.png`, so the
    `.rejected` suffix is enough to keep it out of every published asset,
    while the shots directory (which is uploaded whole as a job artifact and
    is never committed) still carries the evidence for whoever reads the run.
    """
    try:
        os.replace(dest, f"{dest}.rejected")
    except OSError as e:
        anr_warn(f"could not set aside {dest}: {e} - removing it instead")
        try:
            os.remove(dest)
        except OSError:
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="tour_screenshots")
    parser.add_argument("--expected", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=2100, help="overall seconds to wait")
    parser.add_argument("--serial", default=os.environ.get("ANDROID_SERIAL", ""))
    parser.add_argument("--logcat-dump", default="", help="write full logcat here on exit")
    parser.add_argument(
        "--stdout-log",
        default="",
        help="also tail this host-side file (tee'd flutter test output) for markers",
    )
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

    if args.stdout_log:
        def follow_stdout_log():
            # The file appears once the driving shell starts flutter test;
            # follow it tail -F style until the watcher stops.
            pos = 0
            while not stop_requested.is_set():
                try:
                    with open(args.stdout_log, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(pos)
                        chunk = f.read()
                        pos = f.tell()
                    for line in chunk.splitlines():
                        lines.put(line + "\n")
                except FileNotFoundError:
                    pass
                except OSError:
                    pass
                time.sleep(0.5)

        threading.Thread(target=follow_stdout_log, daemon=True).start()
        log(f"also tailing host test output: {args.stdout_log}")

    captured = []  # ordered list of keys
    manifest = {}
    complete = False
    # Whole-framebuffer captures + an in-process `flutter test` mean a blocking
    # Android system dialog sits OVER the app while the test keeps passing and
    # still reports its full expected count, so the run concludes `success`
    # with the dialog burned into every still. Guard each capture and keep a
    # tally the driving shell can turn into an honest verdict.
    anr_tally = {"clean": 0, "unchecked": 0, "rescued": 0, "blocked": 0}
    anr_steps = []
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
            if args.stdout_log:
                # The host test-output tail is still a live transport; keep
                # watching it even if the logcat stream died.
                log("logcat stream ended — continuing on host test output only")
                continue
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
                if not screencap(args.serial, dest):
                    warn(f"failed to capture a valid screenshot for step '{key}'")
                    continue
                blocker = anr_guard(args.serial, key, dest, anr_tally)
                if blocker:
                    anr_steps.append(key)
                    anr_error(
                        f"ANR dialog present at step '{key}' ('{blocker}') - the "
                        "still was REJECTED rather than published. A capture with "
                        "the system dialog in frame reaches the Play listing "
                        "through assemble.py and store/, so this leg fails instead."
                    )
                else:
                    captured.append(key)
                    manifest[key] = os.path.basename(dest)
                    log(f"captured {dest}")
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
        json.dump(
            {
                "captured": manifest,
                "order": captured,
                "complete": complete,
                "anr": dict(anr_tally, steps=anr_steps),
            },
            f,
            indent=2,
        )
        f.write("\n")

    # Sidecar for the driving shell, same shape and same place as the leg's
    # "<out>.status" file. Written on EVERY path (including the SIGTERM
    # wrap-up) so its absence means the check never ran, not that it passed.
    try:
        with open(f"{args.out}.anr", "w", encoding="utf-8", newline="\n") as f:
            f.write(f"TOUR_ANR_BLOCKED={anr_tally['blocked']}\n")
            f.write(f"TOUR_ANR_RESCUED={anr_tally['rescued']}\n")
            f.write(f"TOUR_ANR_CHECKED={anr_tally['clean']}\n")
            f.write(f"TOUR_ANR_UNCHECKED={anr_tally['unchecked']}\n")
            f.write(f"TOUR_ANR_STEPS={','.join(anr_steps)}\n")
    except OSError as e:  # the leg-level check in run_tour.sh still backstops
        anr_warn(f"could not write {args.out}.anr: {e}")

    if anr_tally["blocked"]:
        anr_error(
            f"ANR dialog present at step {', '.join(anr_steps)} - "
            f"{anr_tally['blocked']} screenshot(s) refused rather than committed "
            "with the system dialog in frame."
        )
    elif anr_tally["rescued"]:
        anr_warn(
            f"{anr_tally['rescued']} ANR dialog(s) were dismissed and the frames "
            "recaptured clean; no contaminated still was kept."
        )
    elif anr_tally["clean"]:
        # The POSITIVE line: a grep can tell "checked, no ANR" from "never
        # checked", the same way the POST_NOTIFICATIONS grant logs its success.
        anr_log(
            f"no ANR dialog detected ({anr_tally['clean']} capture(s) checked, "
            f"{anr_tally['unchecked']} unchecked)"
        )
    else:
        # Nothing was ever successfully checked - say so rather than let the
        # positive line above imply a clean bill of health nobody established.
        anr_warn(
            f"no capture could be checked for an ANR dialog "
            f"({anr_tally['unchecked']} unchecked) - this leg's stills are UNVERIFIED"
        )

    log(f"done: {len(captured)} screenshots captured (expected {args.expected})")
    if args.expected and len(captured) < args.expected:
        warn(f"captured {len(captured)}/{args.expected} tour screenshots")
    return 0 if captured else 1


if __name__ == "__main__":
    sys.exit(main())

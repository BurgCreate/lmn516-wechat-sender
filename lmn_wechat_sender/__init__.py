"""Small macOS WeChat sender built around the LMN516 five-step keyboard workflow.

No OCR, screenshots, window geometry, private APIs, or bundled account data.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

BUNDLE_ID = "com.tencent.xinWeChat"
DATA_DIR = Path(os.environ.get("LMN_WECHAT_SENDER_HOME", Path.home() / "Library/Application Support/lmn516-wechat-sender"))


class SenderError(Exception):
    pass


def digest_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _error_text(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    return str(value or "").strip()


class MacBackend:
    """Uses standard macOS Accessibility automation; no LMN516 private binaries."""

    def __init__(self, app_path=None, pause=0.35, run=None, sleep=None):
        self.app_path = app_path or os.environ.get("WECHAT_APP_PATH")
        self.pause = pause
        self.run = run or subprocess.run
        self.sleep = sleep or time.sleep

    def _exec(self, cmd, payload=None):
        try:
            result = self.run(cmd, input=payload, capture_output=True, timeout=12, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SenderError("%s failed: %s" % (cmd[0], exc))
        if result.returncode != 0:
            raise SenderError("%s failed: %s" % (cmd[0], _error_text(result.stderr)))
        return result

    def activate(self):
        args = ["open", "-a", self.app_path] if self.app_path else ["open", "-b", BUNDLE_ID]
        self._exec(args)
        self.sleep(max(0.2, self.pause))

    def press(self, actions):
        # No contact or message text is interpolated into AppleScript.
        script = (
            'tell application "System Events"\n'
            '  set currentProcess to first application process whose frontmost is true\n'
            '  if (bundle identifier of currentProcess) is not "' + BUNDLE_ID + '" then\n'
            '    error "wechat-not-frontmost"\n'
            '  end if\n'
            + "\n".join("  " + line for line in actions.splitlines())
            + '\nend tell'
        )
        self._exec(["osascript", "-e", script])

    def paste(self, text):
        self._exec(["pbcopy"], payload=text.encode("utf-8"))
        self.press('keystroke "v" using {command down}')

    def wait(self):
        self.sleep(self.pause)


def _send_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    descriptor = open(path, "a")
    os.chmod(path, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        descriptor.close()
        raise SenderError("another-send-is-in-progress")
    return descriptor


def send_message(contact, message, exact=True, source_sha256=None, dry_run=False,
                 backend=None, lock_path=None, app_path=None):
    """Attempt one message, with no automatic retry after final Enter.

    A successful final keypress is NOT proof of delivery or reading.
    """
    if not isinstance(contact, str) or not contact.strip():
        raise ValueError("contact must be a non-empty exact display name")
    if not isinstance(message, str) or not message:
        raise ValueError("message must be non-empty")
    if not exact:
        raise ValueError("only exact-contact mode is supported")
    actual_sha = digest_text(message)
    if source_sha256 and source_sha256.lower() != actual_sha:
        raise ValueError("source-sha256-mismatch")

    result = {
        "ok": True, "contact": contact, "content_sha256": actual_sha,
        "attempted": False, "accepted_by_client": False,
        "visually_verified": False, "verification_skipped": True,
        "delivery_state": "dry-run" if dry_run else "not-attempted",
    }
    if dry_run:
        result["steps"] = [
            "Cmd+F, clear search, paste exact contact", "Enter opens chat",
            "Cmd+A, Delete clears composer", "paste exact message",
            "Enter attempts send",
        ]
        return result
    if backend is None and sys.platform != "darwin":
        raise SenderError("macOS is required for GUI sends")
    backend = backend or MacBackend(app_path=app_path)
    lock_path = Path(lock_path or DATA_DIR / "send.lock")
    lock = _send_lock(lock_path)
    final_enter_started = False
    try:
        try:
            backend.activate()
            # Step 1: find the exact requested contact (no fuzzy-name substitution).
            backend.press('keystroke "f" using {command down}')
            backend.wait()
            backend.press('keystroke "a" using {command down}\nkey code 51')
            backend.paste(contact)
            backend.wait()
            # Step 2: open the chat.
            backend.press("key code 36")
            backend.wait()
            # Step 3: clear composer; step 4: paste exact message.
            backend.press('keystroke "a" using {command down}\nkey code 51')
            backend.paste(message)
            backend.wait()
            # Step 5: final Enter. Any error from here is ambiguous.
            final_enter_started = True
            backend.press("key code 36")
            result["attempted"] = True
            result["delivery_state"] = "enter-dispatched-unverified"
        except Exception as exc:
            result["ok"] = False
            result["attempted"] = final_enter_started
            result["delivery_state"] = (
                "ambiguous-do-not-resend" if final_enter_started else "not-attempted"
            )
            result["error"] = _error_text(exc)
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
    return result


def _content_flags(parser):
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--text", help="exact message body (visible in shell history)")
    group.add_argument("--stdin", action="store_true", help="read exact message from stdin")
    parser.add_argument("--contact", required=True, help="exact WeChat display name")
    parser.add_argument("--source-sha256", help="optional SHA-256 content lock")
    parser.add_argument("--exact", action="store_true", help="compatibility flag; exact is always enforced")


def _read_body(args):
    return sys.stdin.read() if args.stdin else args.text


def parser():
    p = argparse.ArgumentParser(description="LMN516 WeChat Sender (macOS, five-step mode)")
    sub = p.add_subparsers(dest="command", required=True)
    send = sub.add_parser("send", help="one immediate send attempt")
    _content_flags(send)
    send.add_argument("--app-path", help="optional custom WeChat .app path")
    send.add_argument("--dry-run", action="store_true", help="show plan, never activate WeChat")
    send.add_argument("--delay", type=float, default=0.35, help="pause between steps")
    once = sub.add_parser("schedule-once", help="record one local scheduled attempt")
    _content_flags(once)
    when = once.add_mutually_exclusive_group(required=True)
    when.add_argument("--at", help="timezone-aware ISO 8601 timestamp")
    when.add_argument("--after-minutes", type=float)
    sub.add_parser("schedule-list", help="list jobs without message bodies")
    cancel = sub.add_parser("schedule-cancel")
    cancel.add_argument("--id", required=True)
    due = sub.add_parser("run-due", help="run pending jobs; invoke from launchd")
    due.add_argument("--dry-run", action="store_true")
    due.add_argument("--app-path")
    return p


def main(argv=None):
    from . import scheduler
    args = parser().parse_args(argv)
    try:
        if args.command == "send":
            result = send_message(
                args.contact, _read_body(args), source_sha256=args.source_sha256,
                dry_run=args.dry_run, backend=(
                    None if args.dry_run else MacBackend(app_path=args.app_path, pause=max(0.0, args.delay))
                ),
            )
        elif args.command == "schedule-once":
            result = scheduler.schedule_once(
                args.contact, _read_body(args), at=args.at, after_minutes=args.after_minutes,
                source_sha256=args.source_sha256,
            )
        elif args.command == "schedule-list":
            result = scheduler.list_jobs()
        elif args.command == "schedule-cancel":
            result = scheduler.cancel_job(args.id)
        else:
            result = scheduler.run_due(dry_run=args.dry_run, app_path=args.app_path)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 3
    except (SenderError, ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "attempted": False, "error": _error_text(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

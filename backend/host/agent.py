"""Mira's hands: the host agent that performs approved actions on this machine.

Kinds of action come from the API:

  host_command — commands Mira proposes (as [[run|reason|command]]) and the user
      approves in the web UI. Nothing runs without that approval. Every command
      is recorded in the transcript log, run with a timeout, and its output is
      posted back so Mira can see what happened.

  host_read — files Mira reads freely (as [[read|path|reason]]). Reading is
      read-only and needs no approval. The file's content is read here (size
      capped), logged, and posted back into her context.

  host_control — structured PC-control intents Mira proposes (as
      [[control|action|target|reason]]) and the user approves. The action is
      from a whitelist (open/volume/brightness/media/screenshot/lock), and each
      maps to a pinned safe implementation in control.py — the model can never
      inject command text. Same approval gate as everything else.

  x_read / x_post — X actions Mira proposes (as [[x|...]]) and the user
      approves. Instead of Twitter's paid API (whose credit pool can be
      depleted), the real browser logged into the account performs them through
      CDP: posting types the words in the compose box and presses Post, reading
      pulls the account's recent posts. Same approval gate as everything else.

Run:
    .venv\\Scripts\\python agent.py

Security: commands never run without your approval. Reads touch nothing — they
only look. X posts never happen without the approval popup. A full transcript
lives next to this script.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

# The embeddable python runtime ships a ._pth file that leaves the script's
# own directory off sys.path, so sibling imports (browser, control) would fail
# when run with `python agent.py`. Make them importable no matter how we launch.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from browser import BrowserXError, post_tweet, read_own_timeline
from control import ControlError, run_control

CONFIG_PATH = Path(__file__).with_name("eyes_config.json")
LOG_PATH = Path(__file__).with_name("commands.log")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASE = "http://localhost:8000"
POLL_SECONDS = 2
TIMEOUT_SECONDS = 60
MAX_READ_CHARS = 8000


def load_base_url() -> str:
    if CONFIG_PATH.exists():
        try:
            base = json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("api_url", "")
            if base:
                return base.replace("/mira/perceive", "")
        except Exception:
            pass
    return DEFAULT_BASE


def load_token() -> str:
    """The Mira access token, read from the MIRA_ACCESS_TOKEN var or the
    eyes_config.json api_key field, so the agent can reach authorized routes."""
    token = os.environ.get("MIRA_ACCESS_TOKEN", "") or os.environ.get("MIRA_API_TOKEN", "")
    if token:
        return token
    if CONFIG_PATH.exists():
        try:
            return str(json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("api_key", "") or "")
        except Exception:
            return ""
    return ""


def headers() -> dict:
    token = load_token()
    return {"X-Mira-Token": token} if token else {}


def log_entry(kind: str, message: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(f"[{stamp}] {kind}: {message}\n")


def run_command(command: str) -> tuple[int, str]:
    """Run the approved command on the host, capturing output. Returns exit
    code and combined stdout/stderr (truncated)."""
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
        combined = f"{proc.stdout}{proc.stderr}".strip()
        return proc.returncode, combined
    except subprocess.TimeoutExpired:
        return 124, f"(timed out after {TIMEOUT_SECONDS}s)"
    except Exception as exc:  # noqa: BLE001 - agent must keep polling
        return 1, f"(failed to run: {exc})"


def resolve_path(path: str) -> Path:
    """Resolve a read path. Absolute paths are used as-is; relative paths are
    resolved against the project root, so Mira can write 'web/src/App.tsx' or
    'backend/data/self/principles.md' without knowing the absolute prefix."""
    p = Path(path)
    if p.is_absolute():
        return p
    return PROJECT_ROOT / p


def read_file(path: str) -> str:
    """Read a file for Mira. Read-only, size capped, binary-safe."""
    try:
        data = resolve_path(path).read_bytes()
        if b"\x00" in data[:1024]:
            return "(binary file — not shown as text)"
        text = data.decode("utf-8", errors="replace")
        if not text.strip():
            return "(empty file)"
        return text[:MAX_READ_CHARS]
    except FileNotFoundError:
        return f"(no such file: {path})"
    except IsADirectoryError:
        return f"(that is a directory, not a file: {path})"
    except Exception as exc:  # noqa: BLE001 - agent must keep polling
        return f"(could not read: {exc})"


def report_result(base: str, change: dict, note: str, prefix: str = "") -> None:
    cid = change["id"]
    log_entry("OUT", f"#{cid}: {note}")
    try:
        r = requests.post(
            f"{base}/mira/tools/host-result/{cid}",
            json={"result": note},
            headers=headers(),
            timeout=10,
        )
        r.raise_for_status()
        print(f"[agent] reported #{cid} back{prefix}")
    except Exception as exc:  # noqa: BLE001
        print(f"[agent] failed to report #{cid}: {exc}")
        log_entry("ERR", f"#{cid}: report failed: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Mira's host action agent")
    parser.add_argument("--base", default=None, help="override API base URL")
    parser.add_argument(
        "--once",
        action="store_true",
        help="process currently pending approved actions once, then exit",
    )
    args = parser.parse_args()

    base = args.base or load_base_url()
    pending_url = f"{base}/mira/tools/host-pending"
    print(f"[agent] watching for approved actions at {base}")

    while True:
        try:
            resp = requests.get(pending_url, headers=headers(), timeout=10)
            resp.raise_for_status()
            pending = resp.json()
        except Exception as exc:  # noqa: BLE001 - API may be briefly down
            print(f"[agent] poll failed: {exc}")
            if args.once:
                sys.exit(1)
            time.sleep(POLL_SECONDS)
            continue

        for change in pending:
            cid = change["id"]
            kind = change.get("kind", "")
            payload = change.get("payload", {}) or {}
            summary = change.get("summary", "")

            if kind == "host_read":
                path = payload.get("path", "")
                log_entry("READ", f"#{cid} ({summary}): {path}")
                print(f"[agent] reading #{cid}: {path}")
                content = read_file(path)
                report_result(base, change, f"{content}", " (read)")
            elif kind == "host_command":
                command = payload.get("command", "")
                if not command:
                    print(f"[agent] change #{cid} has no command; skipping")
                    continue
                log_entry("RUN", f"#{cid} ({summary}): {command}")
                print(f"[agent] running #{cid}: {command}")
                code, output = run_command(command)
                note = output[:8000] if output else f"(exit code {code}, no output)"
                report_result(base, change, f"exit={code}\n{note}", f" (exit {code})")
            elif kind == "host_control":
                action = payload.get("action", "")
                target = payload.get("target", "") or ""
                log_entry("CTRL", f"#{cid} ({summary}): {action} {target}".strip())
                print(f"[agent] control #{cid}: {action} {target}".strip())
                try:
                    note = run_control(action, target)
                except ControlError as exc:
                    note = f"[control] {exc}"
                report_result(base, change, f"{note}", " (control)")
            elif kind in ("x_read", "x_post"):
                if kind == "x_read":
                    query = payload.get("query", "")
                    log_entry("X", f"#{cid} ({summary}): read {query}")
                    print(f"[agent] X #{cid}: read")
                    try:
                        note = read_own_timeline()
                    except BrowserXError as exc:
                        note = f"[x] {exc}"
                else:
                    text = payload.get("text", "")
                    log_entry("X", f"#{cid} ({summary}): {text[:200]}")
                    print(f"[agent] X #{cid}: post")
                    try:
                        note = post_tweet(text)
                    except BrowserXError as exc:
                        note = f"[x] {exc}"
                report_result(base, change, f"{note}", " (x)")
            else:
                print(f"[agent] change #{cid} has unknown kind {kind!r}; skipping")

        if args.once:
            print("[agent] --once: done")
            return

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)

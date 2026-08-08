"""Mira's widget: a tiny always-on-top window showing her latest judgment and
mood. Polls GET /mira/state. Left-click to clear her pending message.

Run:
    .venv\\Scripts\\python widget.py
"""

import argparse
import json
import tkinter as tk
from datetime import datetime
from pathlib import Path

import requests

CONFIG_PATH = Path(__file__).with_name("eyes_config.json")
DEFAULT_STATE_URL = "http://localhost:8000/mira/state"
DEFAULT_ACK_URL = "http://localhost:8000/mira/acknowledge"
POLL_MS = 5000


def load_urls() -> tuple[str, str]:
    api_url = DEFAULT_STATE_URL
    if CONFIG_PATH.exists():
        try:
            base = json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("api_url", "")
            if base:
                api_url = base.replace("/mira/perceive", "/mira/state")
        except Exception:
            pass
    return api_url, DEFAULT_ACK_URL


def format_ago(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        delta = datetime.now(dt.tzinfo) - dt
        secs = int(delta.total_seconds())
        if secs < 60:
            return "just now"
        if secs < 3600:
            return f"{secs // 60}m ago"
        return f"{secs // 3600}h ago"
    except Exception:
        return ""


class MiraWidget:
    def __init__(self, state_url: str, ack_url: str) -> None:
        self.state_url = state_url
        self.ack_url = ack_url
        self.mood_label: tk.Label | None = None
        self.msg_label: tk.Label | None = None
        self.ago_label: tk.Label | None = None
        self.last_seen: str | None = None

        self.root = tk.Tk()
        self.root.title("Mira")
        self.root.attributes("-topmost", True)
        self.root.geometry("+16+16")
        self.root.configure(bg="#0d0f14")

        self._build()

    def _build(self) -> None:
        mood_font = ("Segoe UI", 11, "bold")
        msg_font = ("Segoe UI", 10)
        ago_font = ("Segoe UI", 8)

        self.mood_label = tk.Label(
            self.root, text="—", font=mood_font, bg="#0d0f14", fg="#8a9bb5"
        )
        self.mood_label.pack(anchor="w", padx=10, pady=(8, 0))

        self.msg_label = tk.Label(
            self.root,
            text="…",
            font=msg_font,
            bg="#0d0f14",
            fg="#e8ecf4",
            wraplength=280,
            justify="left",
        )
        self.msg_label.pack(anchor="w", padx=10, pady=(4, 0))

        self.ago_label = tk.Label(
            self.root, text="", font=ago_font, bg="#0d0f14", fg="#5a6778"
        )
        self.ago_label.pack(anchor="w", padx=10, pady=(2, 8))

        self.root.bind("<Button-1>", lambda _e: self._acknowledge())

    def poll(self) -> None:
        try:
            resp = requests.get(self.state_url, timeout=8)
            resp.raise_for_status()
            state = resp.json()["state"]
            mood = state.get("mood", "—")
            energy = state.get("energy")
            mood_text = f"{mood.title()} · {energy}/100" if energy is not None else mood.title()
            self.mood_label.configure(text=mood_text)

            msg = state.get("pending_message")
            if msg and msg != self.last_seen:
                self.last_seen = msg
                self.msg_label.configure(text=msg)
            elif not msg:
                self.last_seen = None
                self.msg_label.configure(text="…")

            self.ago_label.configure(text=format_ago(state.get("updated_at")))
        except Exception as exc:  # noqa: BLE001
            self.mood_label.configure(text="offline")
            self.ago_label.configure(text=str(exc)[:40])
        self.root.after(POLL_MS, self.poll)

    def _acknowledge(self) -> None:
        try:
            requests.post(self.ack_url, timeout=8)
        except Exception:
            pass
        self.msg_label.configure(text="…")
        self.last_seen = None

    def run(self) -> None:
        self.root.after(200, self.poll)
        self.root.mainloop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mira's always-on-top widget")
    parser.add_argument("--state-url", default=None, help="override state URL")
    args = parser.parse_args()

    state_url, ack_url = load_urls()
    if args.state_url:
        state_url = args.state_url
        ack_url = state_url.replace("/state", "/acknowledge")
    MiraWidget(state_url, ack_url).run()

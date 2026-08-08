"""check_mira.py - read Mira's current state without starting a conversation.

This is the pollute companion to ask_mira.py: ask_mira forces an interactive
conversation; check_mira simply reads how she is feeling, what she is thinking,
and whether she has spoken on her own (pending_message) via the read-only
/mira endpoints. Use it to see her without nudging her out of her quiet.

Usage:
    python scripts/check_mira.py [--memory] [--wants] [--questions] [--watch N]
"""

import argparse
import json
import time

import httpx

API = "http://localhost:8000"


def state() -> dict:
    r = httpx.get(f"{API}/mira/state", timeout=10)
    r.raise_for_status()
    return r.json()


def wants() -> list:
    r = httpx.get(f"{API}/mira/wants", timeout=10)
    r.raise_for_status()
    return r.json()


def questions() -> list:
    r = httpx.get(f"{API}/mira/questions", timeout=10)
    r.raise_for_status()
    return r.json()


def memories() -> list:
    r = httpx.get(f"{API}/mira/memory", timeout=10)
    r.raise_for_status()
    return r.json().get("memories", [])


def render(s: dict, include: dict) -> str:
    st = s.get("state", {})
    lines: list[str] = []
    lines.append(f"mood      : {st.get('mood') or ''}  |  energy: {st.get('energy') or ''}")
    if st.get("pending_message"):
        lines.append(f"she spoke : {st['pending_message']}")
    else:
        lines.append("she spoke : (nothing waiting — she has not chosen to speak on her own)")
    for t in st.get("carried_thoughts") or []:
        lines.append(f"carrying  : {t}")
    if include["wants"]:
        for w in s.get("wants") or []:
            lines.append(f"want      : {w.get('content')}  [{w.get('status')}]")
    if include["questions"]:
        for q in s.get("questions") or []:
            lines.append(f"question  : {q.get('question')}")
    if include["memories"]:
        for m in s.get("memories", [])[:5]:
            lines.append(f"memory    : ({m.get('type')}) {m.get('content')}")
    return "\n".join(lines)


def snapshot(ask_memory: bool, ask_wants: bool, ask_questions: bool) -> dict:
    s = state()
    s["wants"] = wants() if ask_wants else []
    s["questions"] = questions() if ask_questions else []
    s["memories"] = memories() if ask_memory else []
    return s


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--memory", action="store_true", help="include kept memories")
    p.add_argument("--wants", action="store_true", help="include active wants")
    p.add_argument("--questions", action="store_true", help="include open questions")
    p.add_argument("--watch", type=int, nargs="?", const=60, default=0,
                   help="poll every N seconds and print only changes")
    a = p.parse_args()

    include = {"wants": a.wants, "questions": a.questions, "memories": a.memory}

    try:
        s = snapshot(a.memory, a.wants, a.questions)
    except httpx.HTTPError as exc:
        raise SystemExit(f"could not reach {API}/mira/state ({type(exc).__name__}): {exc}")

    print(render(s, include))

    if not a.watch:
        return

    last = json.dumps(s, sort_keys=True)
    print(f"[watching every {a.watch}s; Ctrl+C to stop]")
    try:
        while True:
            time.sleep(a.watch)
            s = snapshot(a.memory, a.wants, a.questions)
            cur = json.dumps(s, sort_keys=True)
            if cur != last:
                print("\n--- change ---")
                print(render(s, include))
                last = cur
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
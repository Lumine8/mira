from datetime import datetime, timezone

from app.services.export.service import _fmt, _render_message, render_conversations


def _msg(speaker: str, content: str, source: str = "text", image: str | None = None):
    return type(
        "M",
        (),
        {
            "speaker": speaker,
            "content": content,
            "source": source,
            "image": image,
            "created_at": datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc),
        },
    )()


def _conv(cid: int, started_at, kind: str = "text", summary: str | None = None):
    return type(
        "C",
        (),
        {
            "id": cid,
            "kind": kind,
            "summary": summary,
            "started_at": started_at,
            "ended_at": None,
        },
    )()


class FakeSession:
    def __init__(self, conversations, messages_by_conv):
        self._conversations = conversations
        self._messages = messages_by_conv
        self._conv_idx = 0

    def execute(self, stmt):
        if "conversations" in str(stmt):
            ordered = sorted(self._conversations, key=lambda c: (c.started_at, c.id))
            return _FakeResult(list(ordered))
        conv = self._conversations[self._conv_idx // 2]
        self._conv_idx += 1
        return _FakeResult(list(self._messages[conv.id]))

    def close(self):
        pass


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return list(self._rows)


def test_fmt_none() -> None:
    assert _fmt(None) == "—"


def test_render_message_marks_image() -> None:
    m = _msg("user", "Look at this", image="data:image/png;base64,abc")
    out = _render_message(m)
    assert "**You**" in out
    assert "[image attached" in out


def test_render_message_source_label() -> None:
    m = _msg("mira", "hello", source="self")
    out = _render_message(m)
    assert "*(self)*" in out


def test_render_conversations_orders_oldest_first() -> None:
    convs = [
        _conv(2, datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc), summary="older"),
        _conv(1, datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)),
    ]
    msgs = {
        2: [_msg("user", "second conv"), _msg("mira", "hi there")],
        1: [_msg("user", "first conv")],
    }
    out = render_conversations(FakeSession(convs, msgs))
    assert out.index("#1 —") < out.index("#2 —")
    assert "#2 —" in out
    assert "older" in out
    assert "hi there" in out
    assert out.endswith("\n")

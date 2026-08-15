from collections import deque

import pytest

import app.services.self.service as self_service


class FakeProvider:
    async def complete(self, *args, **kwargs):  # pragma: no cover
        return "{}"


class FakeSettings:
    self_model_enabled = True


def _reset_queue_state() -> None:
    self_service._DIGEST_QUEUE.clear()
    worker = self_service._DIGEST_WORKER
    if worker is not None and hasattr(worker, "done") and not worker.done():
        try:
            worker.cancel()
        except AttributeError:  # pragma: no cover
            pass
    self_service._DIGEST_WORKER = None


@pytest.mark.asyncio
async def test_schedule_digest_bounds_queue_and_keeps_newest(monkeypatch) -> None:
    _reset_queue_state()
    monkeypatch.setattr(self_service, "get_settings", lambda: FakeSettings())
    # Never let the worker actually run (no DB in unit tests): stub out the
    # worker task with a fake that reports done() so schedule_digest just
    # enqueues and we can inspect the queue.
    class FakeTask:
        def done(self) -> bool:
            return False

        def cancel(self) -> None:
            return None

    monkeypatch.setattr(self_service.asyncio, "ensure_future", lambda coro: FakeTask())
    # The real _digest_worker is never awaited in tests; close over the coroutine
    # so no dangling coroutine warnings are emitted.
    monkeypatch.setattr(self_service, "_digest_worker", lambda: object())

    # First two turns are kept; the third pushes the oldest out.
    for n in range(3):
        self_service.schedule_digest(FakeProvider(), n, 1, f"in {n}", f"reply {n}", [])

    queue = self_service._DIGEST_QUEUE
    assert isinstance(queue, deque)
    assert len(queue) == self_service._DIGEST_QUEUE_MAX
    kept_ids = [item[1] for item in queue]
    assert kept_ids == [1, 2], "oldest digest should be dropped, newest two kept"


@pytest.mark.asyncio
async def test_schedule_digest_skipped_when_self_model_disabled(monkeypatch) -> None:
    _reset_queue_state()
    disabled = FakeSettings()
    disabled.self_model_enabled = False
    monkeypatch.setattr(self_service, "get_settings", lambda: disabled)

    self_service.schedule_digest(FakeProvider(), 42, 1, "in", "reply", [])
    assert len(self_service._DIGEST_QUEUE) == 0

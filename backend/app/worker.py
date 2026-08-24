"""Standalone worker process: claims and executes background jobs.

Run with: python -m app.worker
Or via: MIRA_WORKER_MODE=true python -m app.main
"""

import asyncio
import logging
import signal
import time

from app.services.jobs.service import JobService

logger = logging.getLogger("mira.worker")
_running = True


def _shutdown(sig, frame):
    global _running
    _running = False
    logger.info("worker shutting down")


signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGTERM, _shutdown)


def run():
    service = JobService()
    logger.info("worker started")
    while _running:
        job = service.claim(kinds=["mind_reflection", "mote_tick", "reminder_fire"])
        if job is None:
            time.sleep(5)
            continue
        try:
            _execute(job)
            service.complete(job.id, "ok")
        except Exception as exc:
            logger.warning("job %d failed: %s", job.id, exc)
            service.fail(job.id, str(exc))


def _execute(job):
    if job.kind == "mind_reflection":
        from app.services.mind.service import MindLoop
        from app.deps import get_provider

        loop = MindLoop(get_provider())
        asyncio.run(loop._tick_work())
    elif job.kind == "mote_tick":
        from app.services.mote.service import MoteLoop

        loop = MoteLoop()
        asyncio.run(loop._tick_work())
    elif job.kind == "reminder_fire":
        from app.services.reminders.service import ReminderLoop

        loop = ReminderLoop()
        asyncio.run(loop._tick_work())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    run()

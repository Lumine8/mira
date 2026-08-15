"""The runner — how a skill executes and how its runs prove themselves.

Files on the shelf are the source of truth; these tables are the ledger that
shows a skill getting better. A *run* is one concrete use of a skill: what it
was asked, what it produced, whether it went clean or failed. An *evaluation*
measures that run against the skill's own declared verification checks and
scores it — appended after every run so the history shows movement.

Running a skill never bypasses the tools: when one of a skill's declared tools
actually fires in a conversation (e.g. the research skill fires research_query),
the runner records that as a run of the skill. The tool did the work; the
runner keeps the receipt and the measurement.
"""

from __future__ import annotations

import logging
from dataclasses import asdict

from sqlalchemy.orm import Session

from app.models import SkillEvaluation as SkillEvaluationRow
from app.models import SkillRun as SkillRunRow
from app.services.skills.evaluator import Evidence, run_checks, score
from app.services.skills.registry import Skill

logger = logging.getLogger("mira.skills.runner")

# What a run may carry before it is written down. Output is a tool's real
# result, so it gets a generous (but bounded) cap like every other channel.
MAX_RUN_TASK = 4_000
MAX_RUN_OUTPUT = 40_000
MAX_RUN_ERROR = 2_000
RUN_STATUSES = {"ran", "failed"}


class SkillRunnerError(Exception):
    """Raised when a skill cannot be run or evaluated as asked."""


class SkillRunner:
    """Record a skill's use and measure it against its own checks."""

    def __init__(self, db: Session, *, user_id: int) -> None:
        self.db = db
        self.user_id = user_id

    def record_run(
        self,
        skill: Skill,
        task: str,
        output: str = "",
        *,
        status: str = "ran",
        error: str | None = None,
    ) -> SkillRunRow:
        """Write one execution of a skill into the ledger."""
        status = status if status in RUN_STATUSES else "ran"
        run = SkillRunRow(
            user_id=self.user_id,
            skill_id=skill.id,
            version=skill.version,
            task=(task or "").strip()[: MAX_RUN_TASK],
            output=(output or "")[: MAX_RUN_OUTPUT] or None,
            status=status,
            error=(error or "")[: MAX_RUN_ERROR] or None if error else None,
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def evaluate(
        self,
        skill: Skill,
        run: SkillRunRow,
        *,
        names: list[str] | None = None,
        evidence: list[Evidence] | None = None,
        notes: list[str] | None = None,
    ) -> SkillEvaluationRow:
        """Run the skill's declared checks against the run's output and score it.

        ``names`` are expected resolved names the skill's "names resolved" check
        verifies; ``evidence`` are claims with citations the founder offered.
        A failed run scores accordingly rather than pretending it succeeded.
        """
        named = [{"name": n} for n in (names or []) if n]
        raw = run_checks(skill, run.output or "", names=named)
        evidence_rows = [asdict(ev) for ev in (evidence or [])]
        rich = {
            **raw,
            "evidence": evidence_rows,
            "errors": [],
            "failed": run.status == "failed",
            "notes": notes or [],
        }
        scored = score(rich)
        scored["checks"] = raw["checks"]  # keep the per-check breakdown with the score
        row = SkillEvaluationRow(
            user_id=self.user_id,
            run_id=run.id,
            skill_id=skill.id,
            version=skill.version,
            task=run.task or "",
            scores=scored,
            evidence=evidence_rows,
            notes=notes or [],
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row
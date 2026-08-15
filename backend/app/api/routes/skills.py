"""The skill registry's API — the shelf she can prove herself on.

A skill is files on her own shelf; this surfaces them, lets the founder look
at one, and runs and evaluates them. Everything is scoped to the requesting
world: a founder sees data/skills, a replica its own copy.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import SkillEvaluation, SkillRun, SkillVersion
from app.services.identity import get_current_user_id
from app.services.skills import SkillError, SkillRegistry
from app.services.skills.runner import SkillRunner
from app.services.skills.versions import SkillVersionError, SkillVersionService

router = APIRouter(prefix="/mira/skills", tags=["mira"])


class SkillRunIn(BaseModel):
    """The record of one execution of a skill: what it was asked and what it
    produced. Recording is not the work — the tool did the work — the receipt
    is what the ledger keeps."""

    task: str = Field(min_length=1, max_length=4000)
    output: str = Field(default="", max_length=40000)
    status: str = Field(default="ran")
    error: str | None = None


class SkillEvalIn(BaseModel):
    """Claims with their citations a founder wants an evaluation to weight."""
    names: list[str] = Field(default_factory=list)
    evidence: list[dict] = Field(default_factory=list)


@router.get("")
def list_skills(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> list[dict]:
    """The full shelf: every skill's metadata, newest first inside its category,
    with how many times it has been run and when it was last edited."""
    registry = SkillRegistry(db, user_id=user_id)
    run_counts = dict(
        db.execute(
            select(SkillRun.skill_id, func.count())
            .where(SkillRun.user_id == user_id)
            .group_by(SkillRun.skill_id)
        ).all()
    )
    last_edited = dict(
        db.execute(
            select(SkillVersion.skill_id, func.max(SkillVersion.created_at))
            .where(SkillVersion.user_id == user_id)
            .group_by(SkillVersion.skill_id)
        ).all()
    )
    out = []
    for skill in registry.list_skills():
        data = skill.as_dict()
        data["run_count"] = run_counts.get(skill.id, 0)
        data["last_edited"] = last_edited.get(skill.id)
        out.append(data)
    return out


@router.post("/{skill_id}/runs", status_code=201)
def create_run(
    skill_id: str,
    body: SkillRunIn,
    category: str | None = None,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """Record a run of a skill and measure it against the skill's own checks."""
    try:
        skill = SkillRegistry(db, user_id=user_id).load_skill(skill_id, category=category)
    except SkillError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    runner = SkillRunner(db, user_id=user_id)
    run = runner.record_run(
        skill, body.task, body.output,
        status=body.status, error=body.error,
    )
    evaluation = runner.evaluate(skill, run) if skill.verification else None
    return {
        "run": {
            "id": run.id,
            "skill_id": skill.id,
            "version": run.version,
            "task": run.task,
            "status": run.status,
            "error": run.error,
            "created_at": run.created_at,
        },
        "evaluation": {
            "id": evaluation.id,
            "run_id": run.id,
            "version": evaluation.version,
            "scores": evaluation.scores,
            "evidence_count": len(evaluation.evidence or []),
            "created_at": evaluation.created_at,
        } if evaluation else None,
    }


@router.post("/{skill_id}/runs/{run_id}/evaluate")
def evaluate_run(
    skill_id: str,
    run_id: int,
    body: SkillEvalIn,
    category: str | None = None,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """Re-measure one run against the skill's checks, attaching any claims the
    founder could see sitting behind it."""
    try:
        skill = SkillRegistry(db, user_id=user_id).load_skill(skill_id, category=category)
    except SkillError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    run = db.get(SkillRun, run_id)
    if run is None or run.user_id != user_id or run.skill_id != skill.id:
        raise HTTPException(status_code=404, detail=f"no such run #{run_id}")

    from app.services.skills import Evidence

    evidence = [Evidence(**ev) for ev in body.evidence]
    runner = SkillRunner(db, user_id=user_id)
    evaluation = runner.evaluate(skill, run, names=body.names, evidence=evidence)
    return {
        "id": evaluation.id,
        "run_id": run.id,
        "version": evaluation.version,
        "scores": evaluation.scores,
        "evidence_count": len(evaluation.evidence or []),
        "created_at": evaluation.created_at,
    }


@router.get("/{skill_id}/versions")
def list_versions(
    skill_id: str,
    category: str | None = None,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> list[dict]:
    """The edit history of a skill, newest first — each entry is one change to
    one of its files, with the reason and when it happened."""
    registry = SkillRegistry(db, user_id=user_id)
    try:
        skill = registry.load_skill(skill_id, category=category)
    except SkillError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    versions = SkillVersionService(db, user_id=user_id).list_for(skill.id, category=skill.category)
    return [SkillVersionService(db, user_id=user_id).as_dict(v) for v in versions]


@router.get("/{skill_id}/versions/{version_id}")
def get_version(
    skill_id: str,
    version_id: int,
    category: str | None = None,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """One edit, fully: the diff, so the change can actually be looked at."""
    service = SkillVersionService(db, user_id=user_id)
    try:
        registry = SkillRegistry(db, user_id=user_id)
        skill = registry.load_skill(skill_id, category=category)
        version = service.get(version_id, skill_id=skill.id)
    except (SkillError, SkillVersionError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return service.as_dict(version, include_diff=True)


@router.post("/{skill_id}/versions/{version_id}/revert")
def revert_version(
    skill_id: str,
    version_id: int,
    category: str | None = None,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """Put the skill's file back to how it was before this edit, and pin the
    revert as a version of its own so the loop stays complete."""
    service = SkillVersionService(db, user_id=user_id)
    try:
        registry = SkillRegistry(db, user_id=user_id)
        skill = registry.load_skill(skill_id, category=category)
        version = service.get(version_id, skill_id=skill.id)
        reverted = service.revert(skill, version, registry=registry)
    except (SkillError, SkillVersionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return service.as_dict(reverted)


@router.get("/{skill_id}")
def get_skill(
    skill_id: str,
    category: str | None = None,
    include_page: bool = False,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """One skill — its metadata, recent runs, and evaluations. ``include_page``
    adds the SKILL.md text she wrote, for reading the book itself."""
    try:
        skill = SkillRegistry(db, user_id=user_id).load_skill(skill_id, category=category)
    except SkillError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    runs = list(
        db.execute(
            select(SkillRun)
            .where(SkillRun.user_id == user_id, SkillRun.skill_id == skill_id)
            .order_by(SkillRun.created_at.desc())
            .limit(10)
        ).scalars()
    )
    evals = list(
        db.execute(
            select(SkillEvaluation)
            .where(SkillEvaluation.user_id == user_id, SkillEvaluation.skill_id == skill_id)
            .order_by(SkillEvaluation.created_at.desc())
            .limit(10)
        ).scalars()
    )
    data = skill.as_dict()
    data["recent_runs"] = [
        {
            "id": r.id,
            "version": r.version,
            "task": r.task,
            "status": r.status,
            "error": r.error,
            "output": r.output,
            "created_at": r.created_at,
        }
        for r in runs
    ]
    data["recent_evaluations"] = [
        {
            "id": e.id,
            "run_id": e.run_id,
            "version": e.version,
            "task": e.task,
            "scores": e.scores,
            "evidence_count": len(e.evidence or []),
            "created_at": e.created_at,
        }
        for e in evals
    ]
    if include_page:
        data["page"] = skill.page
    return data
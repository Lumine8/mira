"""The evaluator — how a skill proves itself.

A skill's ``verification`` list holds objective checks (schema is valid, every
citation resolves, a count matches, a file parses). The evaluator runs those
checks, records claims with their evidence, and produces a score. The point is
provenance: a claim is only as good as the evidence standing behind it, and a
score is only meaningful if it came from checks that can actually fail.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger("mira.skills.eval")

# How a claim may be classified. FACT is backed by checked evidence; INFERENCE
# is a reasonable reading of it; HYPOTHESIS is a proposed explanation; OPINION
# is a taste or judgement; UNKNOWN is an honest gap.
CATEGORIES = {"fact", "inference", "hypothesis", "opinion", "unknown"}

# The dimensions a skill is scored on. Each check may nudge one or more of
# these; the overall score is a blend, not a single "is it good" guess.
SCORE_DIMENSIONS = [
    "correctness",
    "evidence",
    "tools",
    "completeness",
    "robustness",
    "clarity",
    "efficiency",
    "failure_rate",
    "verification",
]

# Citation metadata we can actually check without a network call: a DOI has
# 10. + registrant + suffix; a Europe PMC id is pure digits; an author is not a
# bare single word when a real paper's authorString is expected.
_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
_PMCID_RE = re.compile(r"^PMC\d+$")


@dataclass
class Evidence:
    """One claim, pinned to what stands behind it."""

    claim: str
    category: str = "unknown"
    citation: str = ""
    explanation: str = ""
    confidence: float = 0.0
    counter: str = ""

    def validate(self) -> tuple[bool, str]:
        if self.category not in CATEGORIES:
            return False, f"unknown claim category: {self.category}"
        if self.category == "fact" and self.confidence < 0.5:
            return False, f"a fact claim should be confident, not {self.confidence:.0%}"
        if self.citation and self.citation.lower().startswith("doi:"):
            doi = self.citation.split(":", 1)[1].strip()
            if not _DOI_RE.match(doi):
                return False, f"citersation does not look like a real DOI: {doi}"
        return True, "ok"


def run_checks(skill, output: str, *, names: list[dict] | None = None) -> dict[str, Any]:
    """Run a skill's declared verification checks against its output.

    Returns ``{"checks": {name: passed|failed|skipped}, "missing": []}``. A
    missing check is one declared in meta.yaml but with no matching rule here —
    that lowers the verification score rather than pretending everything passed.
    """
    checks: dict[str, bool | str] = {}
    named_names = {(n.get("name") or "") for n in (names or []) if isinstance(n, dict)}

    for rule in skill.verification:
        key = rule.strip().lower()
        if key in ("output is non-empty", "produces output"):
            checks[rule] = bool(output and output.strip())
        elif key.startswith("contains "):
            needle = key.removeprefix("contains ").strip().strip("'\"")
            checks[rule] = needle in output
        elif key.startswith("no such paper"):
            checks[rule] = "no such paper" not in output.lower()
        elif key.startswith("no invented sources"):
            checks[rule] = not re.search(
                r"\b(fabricated|invented|hallucinated a (source|paper|study))\b",
                output,
                re.IGNORECASE,
            )
        elif "doi" in key and "resolve" in key:
            do = _DOI_RE.search(output)
            checks[rule] = do is not None
        elif key.startswith("names resolved"):
            missing = [n for n in named_names if n and n not in output]
            checks[rule] = not missing
        else:
            # Declared but has no rule: record it as missing so the verification
            # dimension reflects that the check literally could not run.
            checks[rule] = "skipped"

    missing = [rule for rule, passed in checks.items() if passed == "skipped"]
    return {"checks": checks, "missing": missing}


def score(output: dict[str, Any]) -> dict[str, Any]:
    """Blend check results into the nine dimensions and an overall score.

    The overall score is a weighted average of the dimensions that had signal,
    so a skill with no evidence at all scores low instead of "fine by default".
    """
    checks = output.get("checks", {})
    missing = output.get("missing", [])
    ran = [r for r, p in checks.items() if isinstance(p, bool)]
    passed = sum(1 for p in ran if checks[p] is True)

    verification = passed / len(ran) if ran else 0.0
    if missing:
        # A check that could not run is a warning, not a pass.
        verification *= max(0.0, 1.0 - 0.25 * len(missing) / max(1, len(checks)))

    # evidence: how many claims carry a resolvable citation / explanation.
    evidence_items = output.get("evidence", [])
    with_source = sum(
        1 for e in evidence_items if (e.get("citation") or "").strip()
    ) if evidence_items else 0
    evidence = with_source / len(evidence_items) if evidence_items else 0.0

    dimensions = {
        "correctness": float(passed / len(ran) if ran else 0.0),
        "evidence": evidence,
        "tools": float(output.get("tool_hits", 0)),
        "completeness": float(output.get("items_found", 0) > 0),
        "robustness": 1.0 if not output.get("errors") else 0.3,
        "clarity": float(output.get("wordy", False) is False),
        "efficiency": float(output.get("efficient", True)),
        "failure_rate": 1.0 if not output.get("failed") else 0.0,
        "verification": verification,
    }
    for dim in SCORE_DIMENSIONS:
        dimensions[dim] = min(1.0, max(0.0, round(dimensions[dim], 3)))

    total = sum(dimensions.values()) / len(SCORE_DIMENSIONS)
    return {
        "dimensions": dimensions,
        "overall": round(total, 3),
        "checks_passed": passed,
        "checks_total": len(ran),
        "checks_skipped": missing,
        "evidence_count": len(evidence_items),
        "notes": output.get("notes", []),
    }


@dataclass
class SkillEvaluation:
    """The full record of one evaluation pass on one skill run."""

    skill_id: str
    version: str
    task: str
    output: str
    evidence: list[Evidence] = field(default_factory=list)
    failed: bool = False
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def run(self) -> dict[str, Any]:
        validated = []
        errors = list(self.errors)
        for ev in self.evidence:
            ok, why = ev.validate()
            if ok:
                validated.append(asdict(ev))
            else:
                errors.append(why)
        raw = {
            "checks": {},
            "missing": [],
            "evidence": validated,
            "errors": errors,
            "failed": self.failed,
            "notes": self.notes,
        }
        return raw

    def to_json(self) -> str:
        return json.dumps(self.run(), indent=2, default=str)
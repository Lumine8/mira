"""One-time cleanup: merge memories that are near-duplicates into one.

Runs against the live DB (Mira's own ORM). Uses the embeddings already stored
per memory to cluster near-identical rows, keeps the richest representative per
cluster, and deletes the stragglers (ORM cascade removes their embedding rows).

Run inside the api container:
    docker exec -i mira-api-1 python - < backend/scripts/merge_rain_memories.py
"""

import os
import re
import sys
from difflib import SequenceMatcher

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Memory

MIN_SIM = float(sys.argv[1]) if len(sys.argv) > 1 else 0.82
DRY = os.environ.get("MERGE_DRY", "1") != "0"


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _vec(row):
    emb = row.embeddings[0].embedding if row.embeddings else None
    if emb is None:
        return None
    return emb


def cos(a, b):
    if a is None or b is None:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


def main() -> None:
    db = SessionLocal()
    try:
        rows = db.execute(select(Memory).order_by(Memory.id.asc())).scalars().all()
        print(f"loaded {len(rows)} memories", flush=True)

        clusters = []
        merged = 0
        for m in rows:
            mvec = _vec(m)
            mtext = norm(m.content)
            target = None
            for c in clusters:
                rc = c["rep"]
                sim = cos(mvec, c["vec"])
                if sim >= MIN_SIM:
                    rtext = norm(rc.content)
                    text_sim = (
                        SequenceMatcher(None, mtext, rtext).ratio()
                        if len(mtext) > 3 and len(rtext) > 3
                        else 0.0
                    )
                    if text_sim >= 0.5:
                        target = c
                        break
            if target is None:
                clusters.append({"rep": m, "vec": _vec(m), "members": [m]})
            else:
                target["members"].append(m)
                if m.content and len(m.content) > len(target["rep"].content or ""):
                    target["rep"] = m
                target["vec"] = _vec(m)

        kept = 0
        for c in clusters:
            members = c["members"]
            rep = c["rep"]
            for dup in members:
                if dup.id == rep.id:
                    kept += 1
                    continue
                if DRY:
                    continue
                for emb in list(dup.embeddings):
                    db.delete(emb)
                db.flush()
                db.delete(dup)
                merged += 1
        if not DRY:
            db.commit()
        print(f"clusters={len(clusters)} kept={kept} merged_away={merged} (dry_run={DRY})", flush=True)
        for c in sorted(clusters, key=lambda c: -len(c["members"]))[:8]:
            print(f"  x{len(c['members'])} :: {c['rep'].content[:140]}", flush=True)
    finally:
        db.close()


main()
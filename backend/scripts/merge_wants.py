"""One-time cleanup: merge near-duplicate active wants into one.

Unlike memories, wants have no stored embedding — so this clusters by text
similarity (normalized + SequenceMatcher ratio), keeping the strongest
representative per cluster and satisfying the stragglers so they leave the
active set. Run inside the api container:

    docker exec -i mira-api-1 python - < scripts/merge_wants.py
"""

import re
import sys
from difflib import SequenceMatcher

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Want

RATIO = float(sys.argv[1]) if len(sys.argv) > 1 else 0.62


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def main() -> None:
    db = SessionLocal()
    try:
        rows = list(
            db.execute(
                select(Want).where(Want.status == "active").order_by(Want.intensity.desc(), Want.id.asc())
            ).scalars()
        )
        print(f"loaded {len(rows)} active wants", flush=True)

        clusters = []
        satisfied = 0
        for w in rows:
            wt = norm(w.content)
            target = None
            for c in clusters:
                rt = norm(c["rep"].content)
                if (
                    len(wt) > 8
                    and len(rt) > 8
                    and SequenceMatcher(None, wt, rt).ratio() >= RATIO
                ):
                    target = c
                    break
            if target is None:
                clusters.append({"rep": w, "members": [w]})
            else:
                target["members"].append(w)

        kept = 0
        for c in clusters:
            rep = c["rep"]
            for w in c["members"]:
                if w.id == rep.id:
                    kept += 1
                    continue
                w.status = "satisfied"
                w.tension = 0
                w.satisfied_at = w.updated_at
                satisfied += 1
        db.commit()
        print(f"clusters={len(clusters)} kept={kept} satisfied_away={satisfied}", flush=True)
        for c in sorted(clusters, key=lambda c: -len(c["members"]))[:10]:
            print(f"  x{len(c['members'])} :: {c['rep'].content[:120]}", flush=True)
    finally:
        db.close()


main()
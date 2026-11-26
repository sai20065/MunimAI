"""
Fill scheme_clauses.embedding for every current clause that has none.

Safe to re-run: only rows with a NULL embedding are touched, so a freshly loaded scheme
(python -m backend.kb.loader) is picked up by running this once more.

Run:  python -m backend.kb.embed
"""

from __future__ import annotations

import psycopg

from .. import embed_client
from ..config import DBSettings


def _text(scheme_code: str, clause_ref: str, clause_text: str) -> str:
    return f"{scheme_code.replace('_', ' ')} | {clause_ref}\n{clause_text}"


def run(verbose: bool = True) -> dict:
    if not embed_client.available():
        raise SystemExit(f"embedding service not reachable at {embed_client.EMBED_URL}")
    with psycopg.connect(DBSettings.from_env().conninfo) as conn:
        rows = conn.execute(
            "SELECT id, scheme_code, clause_ref, clause_text FROM scheme_clauses "
            "WHERE superseded_at IS NULL AND embedding IS NULL ORDER BY id").fetchall()
        done = 0
        for i in range(0, len(rows), 32):
            chunk = rows[i:i + 32]
            vecs = embed_client.embed([_text(r[1], r[2], r[3]) for r in chunk], timeout=120)
            if vecs is None:
                raise SystemExit("embedding service failed mid-run; re-run to continue")
            for r, v in zip(chunk, vecs):
                conn.execute("UPDATE scheme_clauses SET embedding=%s::vector WHERE id=%s", (embed_client.to_pg(v), r[0]))
            conn.commit()
            done += len(chunk)
            if verbose:
                print(f"embedded {done}/{len(rows)}", flush=True)
        total = conn.execute("SELECT count(*) FILTER (WHERE embedding IS NOT NULL), count(*) "
                             "FROM scheme_clauses WHERE superseded_at IS NULL").fetchone()
    result = {"embedded_now": done, "with_embedding": total[0], "current_clauses": total[1]}
    if verbose:
        print(result)
    return result


if __name__ == "__main__":
    run()

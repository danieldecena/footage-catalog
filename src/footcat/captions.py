"""Visual descriptions for clips with no speech.

Eighteen of thirty clips on the first card contain no dialogue, so text search
cannot reach them — and those are exactly the b-roll you hunt for months later.
A caption makes them findable by what is in frame.
"""
import json
import sqlite3
from datetime import datetime, timezone


def pending(conn: sqlite3.Connection) -> list:
    """Clips with no speech and no caption — the ones search cannot see."""
    return list(conn.execute(
        "select c.id, c.filename from clip c"
        " where c.role='primary' and c.missing=0"
        "   and not exists(select 1 from transcript t where t.clip_id=c.id)"
        "   and not exists(select 1 from caption p where p.clip_id=c.id)"
        " order by c.captured_utc"))


def write(conn: sqlite3.Connection, clip_index: str, text: str,
          keywords: list | None = None, source: str = "claude") -> bool:
    row = conn.execute(
        "select id from clip where role='primary' and filename like ?",
        (f"%_{clip_index}_D.%",)).fetchone()
    if not row:
        return False
    conn.execute(
        "insert or replace into caption(clip_id,text,keywords,source,written_at)"
        " values(?,?,?,?,?)",
        (row["id"], text, json.dumps(keywords or []), source,
         datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
    conn.commit()
    return True


def search(conn: sqlite3.Connection, q: str) -> list:
    return list(conn.execute(
        "select c.filename, p.text from caption p join clip c on c.id=p.clip_id"
        " where p.text like ? or p.keywords like ?"
        " order by c.captured_utc", (f"%{q}%", f"%{q}%")))

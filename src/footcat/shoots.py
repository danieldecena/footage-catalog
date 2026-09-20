"""Shoot derivation: folder name first, time clustering as fallback."""
import re
import sqlite3
from datetime import datetime, timedelta

FOLDER_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_([a-z0-9-]+)_([a-z0-9-]+)$")
GAP_HOURS = 4


def parse_folder(name: str):
    m = FOLDER_RE.match(name)
    return (m.group(1), m.group(2), m.group(3)) if m else None


def _parse(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")


def _upsert_shoot(conn, slug, location, subject, start, end, derived) -> int:
    row = conn.execute("select id from shoot where slug=?", (slug,)).fetchone()
    if row:
        conn.execute("update shoot set started_utc=min(started_utc,?),"
                     " ended_utc=max(ended_utc,?) where id=?", (start, end, row["id"]))
        return row["id"]
    cur = conn.execute(
        "insert into shoot(slug,title,location,subject,started_utc,ended_utc,derived_from)"
        " values(?,?,?,?,?,?,?)", (slug, slug, location, subject, start, end, derived))
    return cur.lastrowid


def _flush(conn, cluster) -> int:
    start, end = cluster[0]["captured_utc"], cluster[-1]["captured_utc"]
    slug = f"{start[:10]}_unsorted_{start[11:16].replace(':', '')}"
    sid = _upsert_shoot(conn, slug, None, None, start, end, "time_cluster")
    for c in cluster:
        conn.execute("update clip set shoot_id=? where id=?", (sid, c["id"]))
    return sid


def assign(conn: sqlite3.Connection) -> int:
    rows = list(conn.execute(
        "select id, rel_path, captured_utc from clip"
        " where role='primary' and shoot_id is null and captured_utc is not null"
        " order by captured_utc"))
    touched, loose = set(), []

    for r in rows:
        folder = r["rel_path"].rsplit("/", 1)[0] if "/" in r["rel_path"] else ""
        leaf = folder.rsplit("/", 1)[-1] if folder else ""
        parsed = parse_folder(leaf) if leaf else None
        if parsed:
            _, loc, subj = parsed
            sid = _upsert_shoot(conn, leaf, loc, subj,
                                r["captured_utc"], r["captured_utc"], "folder")
            conn.execute("update clip set shoot_id=? where id=?", (sid, r["id"]))
            touched.add(sid)
        else:
            loose.append(r)

    cluster = []
    for r in loose:
        if cluster and (_parse(r["captured_utc"]) - _parse(cluster[-1]["captured_utc"])
                        > timedelta(hours=GAP_HOURS)):
            touched.add(_flush(conn, cluster))
            cluster = []
        cluster.append(r)
    if cluster:
        touched.add(_flush(conn, cluster))

    conn.commit()
    return len(touched)

"""Volume identity.

Identified by a marker file at the volume root, never by name or mount path:
names collide ("Untitled", "T7"), mount points shift ("/Volumes/T7 1"), and
diskutil is unavailable in the target shell. The marker also works on exFAT
cards, which have no stable filesystem UUID.
"""
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

MARKER_NAME = ".footage-catalog-id"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_or_create_marker(root: Path) -> str:
    marker = root / MARKER_NAME
    if marker.exists():
        text = marker.read_text().strip()
        if text:
            return text
    marker_id = uuid.uuid4().hex
    marker.write_text(marker_id + "\n")
    return marker_id


def resolve(conn: sqlite3.Connection, root: Path, kind: str = "external") -> int:
    if not root.is_dir():
        raise FileNotFoundError(f"volume root not found: {root}")
    marker_id = _read_or_create_marker(root)
    row = conn.execute("select id from volume where marker_id=?", (marker_id,)).fetchone()
    if row is None:
        cur = conn.execute(
            "insert into volume(marker_id,label,kind,last_seen_at,last_path,created_at)"
            " values(?,?,?,?,?,?)",
            (marker_id, root.name, kind, _now(), str(root), _now()))
        conn.commit()
        return cur.lastrowid
    conn.execute("update volume set last_seen_at=?, last_path=?, label=? where id=?",
                 (_now(), str(root), root.name, row["id"]))
    conn.commit()
    return row["id"]

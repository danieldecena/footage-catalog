"""Transcription into the catalog. Optional dependency, incremental by model.

A clip already transcribed with the same model is skipped. Changing MODEL
re-transcribes everything, which is the point: a better model is a config
change, not a rebuild.
"""
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

MODEL = "small"          # base -> small is the accuracy upgrade; medium is slower again
COMPUTE = "int8"


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pending(conn: sqlite3.Connection, model: str = MODEL) -> list:
    return list(conn.execute(
        "select c.id, c.rel_path, c.filename from clip c"
        " left join transcript_state t on t.clip_id=c.id"
        " where c.role='primary' and c.missing=0"
        "   and (t.clip_id is null or t.model <> ?)"
        " order by c.captured_utc", (model,)))


def transcribe(conn: sqlite3.Connection, root: Path, model: str = MODEL,
               budget_s: float = 0) -> int:
    if not available():
        return 0
    from faster_whisper import WhisperModel
    from . import media
    m = WhisperModel(model, device="cpu", compute_type=COMPUTE)
    start, done = time.time(), 0
    for r in pending(conn, model):
        if budget_s and time.time() - start > budget_s:
            break
        src = media.proxy_for(root, r["rel_path"])
        if not src.exists():
            continue
        segs, _ = m.transcribe(str(src), language="en", vad_filter=True, beam_size=1)
        rows = [(r["id"], i, round(g.start, 1), round(g.end, 1), g.text.strip(), model)
                for i, g in enumerate(segs) if g.text.strip()]
        conn.execute("delete from transcript where clip_id=?", (r["id"],))
        conn.executemany(
            "insert into transcript(clip_id,seg,start_s,end_s,text,model)"
            " values(?,?,?,?,?,?)", rows)
        conn.execute(
            "insert or replace into transcript_state(clip_id,model,segments,transcribed_at)"
            " values(?,?,?,?)", (r["id"], model, len(rows), _now()))
        conn.commit()
        done += 1
    return done


def search(conn: sqlite3.Connection, q: str) -> list:
    return list(conn.execute(
        "select c.filename, t.start_s, t.end_s, t.text from transcript t"
        " join clip c on c.id=t.clip_id where t.text like ?"
        " order by c.captured_utc, t.start_s", (f"%{q}%",)))

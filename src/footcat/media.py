"""Audio analysis and filmstrips, read from proxies, written to the catalog.

Incremental by construction: a clip already at the current ANALYSIS_VERSION
is skipped without opening a file. Re-running costs nothing.
"""
import json
import re
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ANALYSIS_VERSION = 2
SR = 2000
CURVE_POINTS = 160
THRESH_DB = 5.0
MIN_BAND_S = 0.4
FRAME_W = 112


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pending(conn: sqlite3.Connection) -> list:
    """Primary clips with no current-version analysis."""
    return list(conn.execute(
        "select c.id, c.rel_path, c.filename, c.duration_s from clip c"
        " left join analysis a on a.clip_id=c.id"
        " where c.role='primary' and c.missing=0"
        "   and (a.clip_id is null or a.version < ?)"
        " order by c.captured_utc", (ANALYSIS_VERSION,)))


def proxy_for(root: Path, rel_path: str) -> Path:
    """The .LRF beside a clip, or the clip itself when there isn't one."""
    p = root / rel_path
    lrf = p.with_suffix(".LRF")
    return lrf if lrf.exists() else p


def curve(path: Path):
    import numpy as np
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1",
         "-ar", str(SR), "-f", "s16le", "-"], capture_output=True).stdout
    a = np.frombuffer(raw[: len(raw) // 2 * 2], dtype="<i2").astype("float32")
    if a.size < SR // 4:
        return None, 0.0
    win = SR // 4
    n = a.size // win
    if n == 0:
        return None, 0.0
    rms = np.sqrt((a[: n * win].reshape(n, win) ** 2).mean(axis=1))
    db = 20 * np.log10(np.maximum(rms, 1) / 32768)
    dur = n / 4.0
    if n > CURVE_POINTS:
        db = db[np.linspace(0, n - 1, CURVE_POINTS).astype(int)]
    return db, dur


def bands_from(db, dur: float) -> list:
    import numpy as np
    med = float(np.median(db))
    above = db > med + THRESH_DB
    out, s = [], None
    for i, v in enumerate(above):
        if v and s is None:
            s = i
        elif not v and s is not None:
            out.append([round(s / len(db) * dur, 1), round(i / len(db) * dur, 1)])
            s = None
    if s is not None:
        out.append([round(s / len(db) * dur, 1), round(dur, 1)])
    return [b for b in out if b[1] - b[0] >= MIN_BAND_S]


def frame_count(dur: float) -> int:
    return max(16, min(80, round(dur / 2)))


def filmstrip(path: Path, dur: float) -> str | None:
    """Horizontal strip of frames as a data URI, density scaled to duration."""
    import base64
    n = frame_count(dur)
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        for k in range(n):
            t = max(0.0, dur * (k + 0.5) / n)
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(path),
                 "-frames:v", "1", "-vf", f"scale={FRAME_W}:-2", "-q:v", "7",
                 str(td / f"{k:03d}.jpg")], capture_output=True)
        frames = sorted(td.glob("*.jpg"))
        if not frames:
            return None
        out = td / "strip.jpg"
        r = subprocess.run(["montage", *map(str, frames), "-tile", f"{len(frames)}x1",
                            "-geometry", "+0+0", "-background", "black", str(out)],
                           capture_output=True)
        if r.returncode != 0 or not out.exists():
            return None
        return "data:image/jpeg;base64," + base64.b64encode(out.read_bytes()).decode()


def analyse(conn: sqlite3.Connection, root: Path, budget_s: float = 0,
            with_strips: bool = True) -> int:
    """Analyse every clip that needs it. Returns how many were done."""
    import numpy as np
    import time
    start = time.time()
    done = 0
    for r in pending(conn):
        if budget_s and time.time() - start > budget_s:
            break
        src = proxy_for(root, r["rel_path"])
        if not src.exists():
            continue
        db, dur = curve(src)
        if db is None:
            conn.execute(
                "insert or replace into analysis(clip_id,version,analysed_at,bands,curve)"
                " values(?,?,?,?,?)", (r["id"], ANALYSIS_VERSION, _now(), "[]", "[]"))
            conn.commit(); done += 1
            continue
        bands = bands_from(db, dur)
        active = sum(b[1] - b[0] for b in bands)
        strip = filmstrip(src, dur) if with_strips else None
        conn.execute(
            "insert or replace into analysis"
            "(clip_id,version,median_db,dynamics,active_pct,bands,curve,strip,analysed_at)"
            " values(?,?,?,?,?,?,?,?,?)",
            (r["id"], ANALYSIS_VERSION, round(float(np.median(db)), 1),
             round(float(db.std()), 1), round(active / dur * 100) if dur else 0,
             json.dumps(bands), json.dumps([round(float(x), 1) for x in db]),
             strip, _now()))
        conn.commit()
        done += 1
    return done

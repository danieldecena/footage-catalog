"""Reader for the DJI camera's own SQLite index (MISC/AC006.db).

This holds star/highlight flags and authoritative epoch timestamps. It is
destroyed when the card is formatted, so it must be read and preserved at
ingest. Never raises on a malformed database: a card with a corrupt index
should still scan, just without flags.
"""
import sqlite3
from dataclasses import dataclass
from pathlib import Path

# Columns we use if the firmware's database has them. DJI's schema varies by
# model and firmware, so every optional column is discovered, never assumed —
# one missing column must not cost us the whole read.
VIDEO_COLS = ("duration", "rotation", "resolution_width", "resolution_height",
              "frame_num", "frame_den", "gps_status", "steady_mode", "fov_type",
              "bit_depth", "model_name", "app_audio_status")
GIS_COLS = ("file_name", "dcf_index", "star", "highlight", "video_index")


def _columns(conn, table: str) -> set:
    try:
        return {r[1] for r in conn.execute(f"pragma table_info({table})")}
    except sqlite3.Error:
        return set()


@dataclass
class CameraRecord:
    basename: str
    dcf_index: int | None = None
    epoch: int | None = None
    duration_ms: int | None = None
    rotation: int | None = None
    width: int | None = None
    height: int | None = None
    fps_num: int | None = None
    fps_den: int | None = None
    gps_status: int | None = None
    star: int = 0
    highlight: int = 0
    steady_mode: int | None = None
    fov_type: int | None = None
    bit_depth: int | None = None
    model_name: str | None = None
    video_index: int | None = None
    app_audio: int | None = None


def find_camera_db(volume_root: Path) -> Path | None:
    misc = volume_root / "MISC"
    if not misc.is_dir():
        return None
    return next(iter(sorted(misc.glob("*.db"))), None)


def read(db_path: Path) -> dict[str, CameraRecord]:
    """Read what this database happens to have. Never raises."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        g = _columns(conn, "gis_info_table")
        v = _columns(conn, "video_info_table")
        m = _columns(conn, "mtime_table")
        if "file_name" not in g:
            conn.close(); return {}
        gsel = [f"g.{c}" for c in GIS_COLS if c in g]
        vsel = [f"v.{c}" for c in VIDEO_COLS if c in v]
        joins = ""
        if "video_index" in g and "ID" in v:
            joins += " left join video_info_table v on v.ID = g.video_index"
        else:
            vsel = []
        if "dcf_index" in g and {"dcf_index", "mtime"} <= m:
            joins += " left join mtime_table mm on mm.dcf_index = g.dcf_index"
            msel = ["mm.mtime"]
        else:
            msel = []
        sql = "select " + ", ".join(gsel + vsel + msel) + " from gis_info_table g" + joins
        rows = list(conn.execute(sql))
        conn.close()
    except sqlite3.Error:
        return {}

    def val(r, k):
        try:
            return r[k]
        except (IndexError, KeyError):
            return None

    out: dict[str, CameraRecord] = {}
    for r in rows:
        name = (val(r, "file_name") or "").rsplit("/", 1)[-1]
        if not name:
            continue
        out[name] = CameraRecord(
            basename=name, dcf_index=val(r, "dcf_index"), epoch=val(r, "mtime"),
            duration_ms=val(r, "duration"), rotation=val(r, "rotation"),
            width=val(r, "resolution_width"), height=val(r, "resolution_height"),
            fps_num=val(r, "frame_num"), fps_den=val(r, "frame_den"),
            gps_status=val(r, "gps_status"), star=val(r, "star") or 0,
            highlight=val(r, "highlight") or 0, steady_mode=val(r, "steady_mode"),
            fov_type=val(r, "fov_type"), bit_depth=val(r, "bit_depth"),
            model_name=val(r, "model_name"), video_index=val(r, "video_index"),
            app_audio=val(r, "app_audio_status"))
    return out

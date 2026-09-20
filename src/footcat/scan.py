"""Scan orchestration.

Three tiers keep rescans nearly free:
  * (size, mtime_ns) unchanged  -> skip, zero reads
  * same inode + size, new path -> a MOVE, update in place
  * otherwise                   -> probe and hash

Rows are never deleted on a rescan; a file that disappears gets missing=1,
so the catalog still answers "which drive was that clip on" when the drive
is in a drawer.
"""
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import cameradb, hashing, probe, shoots, timeres, volumes

VIDEO_EXTS = frozenset({"MP4", "MOV", "M4V"})
PROXY_EXTS = frozenset({"LRF"})
PHOTO_EXTS = frozenset({"JPG", "JPEG", "DNG", "HEIC"})
ALL_EXTS = VIDEO_EXTS | PROXY_EXTS | PHOTO_EXTS
CAMERADB_DIR = "_cameradb"


@dataclass
class ScanStats:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    moved: int = 0
    missing: int = 0
    probed: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.inserted or self.updated or self.moved or self.missing)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _role(ext: str) -> str:
    if ext in PROXY_EXTS:
        return "proxy"
    if ext in PHOTO_EXTS:
        return "photo"
    return "primary"


def scan_volume(conn: sqlite3.Connection, root: Path, kind: str = "external") -> ScanStats:
    vid = volumes.resolve(conn, root, kind=kind)
    stats = ScanStats()

    cam_path = cameradb.find_camera_db(root)
    cam = cameradb.read(cam_path) if cam_path else {}

    existing = {r["rel_path"]: dict(r) for r in conn.execute(
        "select id, rel_path, size_bytes, mtime_ns, inode from clip where volume_id=?",
        (vid,))}
    by_inode = {(r["inode"], r["size_bytes"]): r
                for r in existing.values() if r["inode"]}
    seen: set[str] = set()

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        ext = path.suffix.lstrip(".").upper()
        if ext not in ALL_EXTS:
            continue
        rel = str(path.relative_to(root))
        st = path.stat()
        seen.add(rel)

        prior = existing.get(rel)
        if (prior and prior["size_bytes"] == st.st_size
                and prior["mtime_ns"] == st.st_mtime_ns):
            stats.skipped += 1
            continue

        if not prior:
            cand = by_inode.get((st.st_ino, st.st_size))
            if cand and cand["rel_path"] not in seen:
                conn.execute(
                    "update clip set rel_path=?, filename=?, missing=0 where id=?",
                    (rel, path.name, cand["id"]))
                cand["rel_path"] = rel
                stats.moved += 1
                continue

        _upsert(conn, vid, path, rel, st, ext, cam)
        stats.probed += 1
        if prior:
            stats.updated += 1
        else:
            stats.inserted += 1

    conn.execute("create temp table if not exists _seen(rel_path text primary key)")
    conn.execute("delete from _seen")
    conn.executemany("insert or ignore into _seen values(?)", [(r,) for r in seen])
    cur = conn.execute(
        "update clip set missing=1 where volume_id=? and missing=0"
        " and rel_path not in (select rel_path from _seen)", (vid,))
    stats.missing = max(cur.rowcount, 0)

    _link_proxies(conn, vid)
    conn.commit()
    shoots.assign(conn)
    return stats


def _upsert(conn, vid, path: Path, rel: str, st, ext: str, cam: dict) -> None:
    rec = cam.get(path.name)
    pr = probe.probe(path) if ext in (VIDEO_EXTS | PROXY_EXTS) else probe.ProbeResult()

    width = pr.width or (rec.width if rec else None)
    height = pr.height or (rec.height if rec else None)
    rotation = pr.rotation or ((rec.rotation or 0) if rec else 0)
    dw, dh = probe.display_dims(width, height, rotation)

    duration_ms = None
    if rec and rec.duration_ms:
        duration_ms = rec.duration_ms
    elif pr.duration_s:
        duration_ms = int(pr.duration_s * 1000)

    tr = timeres.resolve(path.name, rec.epoch if rec else None, duration_ms,
                         pr.container_creation, st.st_mtime_ns)

    values = dict(
        volume_id=vid, rel_path=rel, filename=path.name, ext=ext, role=_role(ext),
        size_bytes=st.st_size, mtime_ns=st.st_mtime_ns, inode=st.st_ino,
        quick_hash=hashing.quick_hash(path),
        duration_s=(duration_ms / 1000 if duration_ms else None),
        vcodec=pr.vcodec, acodec=pr.acodec, width=width, height=height,
        coded_width=pr.coded_width, coded_height=pr.coded_height, rotation=rotation,
        aspect=probe.aspect_label(dw, dh) if dw and dh else None,
        fps_num=pr.fps_num or (rec.fps_num if rec else None),
        fps_den=pr.fps_den or (rec.fps_den if rec else None),
        bit_rate=pr.bit_rate, bit_depth=rec.bit_depth if rec else None,
        captured_utc=tr.captured_utc, captured_local=tr.captured_local,
        filename_stamp=tr.filename_stamp, clock_offset_min=tr.clock_offset_min,
        clock_suspect=tr.clock_suspect, time_source=tr.time_source,
        camera_model=(rec.model_name if rec else None) or pr.camera_model,
        star=rec.star if rec else 0, highlight=rec.highlight if rec else 0,
        gps_status=rec.gps_status if rec else None,
        steady_mode=rec.steady_mode if rec else None,
        fov_type=rec.fov_type if rec else None,
        app_audio=rec.app_audio if rec else None,
        probe_version=probe.PROBE_VERSION, indexed_at=_now(), missing=0)

    cols = ",".join(values)
    marks = ",".join("?" * len(values))
    updates = ",".join(f"{k}=excluded.{k}" for k in values
                       if k not in ("volume_id", "rel_path"))
    conn.execute(f"insert into clip({cols}) values({marks})"
                 f" on conflict(volume_id, rel_path) do update set {updates}",
                 tuple(values.values()))


def _link_proxies(conn, vid) -> None:
    rows = list(conn.execute(
        "select id, filename, ext, role from clip where volume_id=?", (vid,)))
    primaries = {r["filename"][: -(len(r["ext"]) + 1)]: r["id"]
                 for r in rows if r["role"] == "primary"}
    for r in rows:
        if r["role"] != "proxy":
            continue
        stem = r["filename"][: -(len(r["ext"]) + 1)]
        pid = primaries.get(stem)
        if pid:
            conn.execute("update clip set primary_clip_id=? where id=?", (pid, r["id"]))


def ingest_card(conn: sqlite3.Connection, card_root: Path,
                archive_root: Path) -> ScanStats:
    """Scan a camera card, preserving its database before anything else.

    The camera database holds star/highlight flags and the authoritative epoch
    timestamps, and is destroyed when the card is formatted. Copy first.
    """
    vid = volumes.resolve(conn, card_root, kind="card")
    marker = (card_root / volumes.MARKER_NAME).read_text().strip()

    cam_path = cameradb.find_camera_db(card_root)
    if cam_path is not None:
        dest = archive_root / CAMERADB_DIR
        dest.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        shutil.copy2(cam_path, dest / f"{marker[:8]}_{stamp}_{cam_path.name}")

    conn.execute("update volume set kind='card' where id=?", (vid,))
    conn.commit()
    return scan_volume(conn, card_root, kind="card")

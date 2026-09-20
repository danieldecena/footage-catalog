"""One command: copy, verify, index, analyse, transcribe — then a verdict.

Every stage is resumable and skips what is already done, so running it twice
costs almost nothing. The output that matters is the last line: whether the
card is safe to format.
"""
import shutil
import sqlite3
import time
from pathlib import Path

from . import archive, cameradb, db, media, scan, speech, verify

CATALOG = "catalog.db"


def copy_tree(src: Path, dst: Path, budget_s: float = 0) -> tuple[int, int]:
    """Copy new/changed files only. Writes to .part first so a half-copied
    file can never be mistaken for a finished one. Returns (copied, skipped)."""
    start, copied, skipped = time.time(), 0, 0
    for f in sorted(src.rglob("*")):
        if not f.is_file() or f.name.startswith("."):
            continue
        rel = f.relative_to(src)
        out = dst / rel
        if out.exists() and out.stat().st_size == f.stat().st_size:
            skipped += 1
            continue
        if budget_s and time.time() - start > budget_s:
            break
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(out.suffix + ".part")
        shutil.copy2(f, tmp)
        tmp.replace(out)
        copied += 1
    return copied, skipped


def run(card: Path, archive_root: Path, budget_s: float = 0,
        do_speech: bool = True, log=print) -> dict:
    archive_root.mkdir(parents=True, exist_ok=True)
    conn = db.connect(archive_root / CATALOG)
    out = {}

    # 1. the camera database, before anything else
    cam = cameradb.find_camera_db(card) if card else None
    if cam:
        d = archive_root / scan.CAMERADB_DIR
        d.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        shutil.copy2(cam, d / f"{stamp}_{cam.name}")
        log(f"camera database preserved ({cam.name})")

    # 2. copy
    if card and card.is_dir():
        copied, skipped = copy_tree(card, archive_root, budget_s=budget_s)
        out["copied"], out["skipped"] = copied, skipped
        log(f"copied {copied} new file(s), {skipped} already present")

    # 3. index
    stats = scan.scan_volume(conn, archive_root, kind="archive")
    out["indexed"] = stats.inserted
    log(f"indexed +{stats.inserted} new, {stats.skipped} unchanged, "
        f"{stats.moved} moved, {stats.missing} missing")

    # 4. verify — the gate
    #
    # Every index the archive holds, not just this card's. MISC/AC006.db is
    # overwritten by each import, so on its own it describes only the newest
    # card and every earlier clip would have nothing to check against. The
    # per-run copies in _cameradb/ are what make the gate usable rather than
    # merely honest.
    #
    # Dotfiles are skipped: an AppleDouble ._AC006.db is not a database, and
    # reading one returns an empty map indistinguishable from a card with no
    # readings. The archive already contains one.
    expected = {}
    indexes = []
    kept = archive_root / scan.CAMERADB_DIR
    if kept.is_dir():
        indexes += [p for p in sorted(kept.glob("*.db")) if not p.name.startswith(".")]
    live = cameradb.find_camera_db(archive_root)
    if live:
        indexes.append(live)
    if cam:
        indexes.append(cam)
    for idx in indexes:
        for name, rec in cameradb.read(idx).items():
            if rec.duration_ms:
                expected[name] = rec.duration_ms / 1000
    log(f"camera records available for {len(expected)} clip(s)")
    res = verify.verify(conn, archive_root, expected=expected)
    out["verified"], out["bad"] = len(res.ok), len(res.bad)
    out["safe"] = res.safe

    # 5. analyse (incremental)
    n = media.analyse(conn, archive_root, budget_s=budget_s)
    out["analysed"] = n
    log(f"analysed {n} clip(s); {len(media.pending(conn))} still pending")

    # 6. transcribe (incremental, optional)
    if do_speech and speech.available():
        t = speech.transcribe(conn, archive_root, budget_s=budget_s)
        out["transcribed"] = t
        log(f"transcribed {t} clip(s); {len(speech.pending(conn))} still pending")
    else:
        out["transcribed"] = 0
        if do_speech:
            log("transcription skipped (faster-whisper not installed)")

    out["archive"] = archive.summary(conn)
    log("")
    log(verify.verdict(res))
    conn.close()
    return out

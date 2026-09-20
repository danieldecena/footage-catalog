import os
import shutil
import sqlite3
import pytest
from footcat import db, scan
from conftest import requires_ffmpeg


def _vol(tmp_path, name="vol"):
    root = tmp_path / name
    root.mkdir()
    return root


@requires_ffmpeg
def test_inserts_clips(tmp_path, make_video):
    conn = db.connect(tmp_path / "c.db")
    root = _vol(tmp_path)
    shutil.copy(make_video(name="a.mp4"), root / "DJI_20260916043331_0005_D.MP4")
    stats = scan.scan_volume(conn, root)
    assert stats.inserted == 1 and stats.probed == 1
    row = conn.execute("select role, width, height, quick_hash, duration_s"
                       " from clip").fetchone()
    assert row["role"] == "primary" and row["quick_hash"]
    assert row["width"] == 320 and row["height"] == 240


@requires_ffmpeg
def test_rescan_skips_unchanged_without_probing(tmp_path, make_video):
    conn = db.connect(tmp_path / "c.db")
    root = _vol(tmp_path)
    shutil.copy(make_video(name="a.mp4"), root / "DJI_20260916043331_0005_D.MP4")
    scan.scan_volume(conn, root)
    stats = scan.scan_volume(conn, root)
    assert stats.skipped == 1
    assert stats.inserted == 0 and stats.probed == 0
    assert stats.changed is False


@requires_ffmpeg
def test_move_is_detected_not_reinserted(tmp_path, make_video):
    conn = db.connect(tmp_path / "c.db")
    root = _vol(tmp_path)
    src = root / "DJI_20260916043331_0005_D.MP4"
    shutil.copy(make_video(name="a.mp4"), src)
    scan.scan_volume(conn, root)
    sub = root / "2026-09-16_skykomish_coho"
    sub.mkdir()
    os.rename(src, sub / src.name)
    stats = scan.scan_volume(conn, root)
    assert stats.moved == 1 and stats.inserted == 0
    assert conn.execute("select count(*) from clip").fetchone()[0] == 1
    assert conn.execute("select rel_path from clip").fetchone()[0].startswith("2026-09-16")


@requires_ffmpeg
def test_deleted_file_is_marked_missing_not_removed(tmp_path, make_video):
    conn = db.connect(tmp_path / "c.db")
    root = _vol(tmp_path)
    f = root / "DJI_20260916043331_0005_D.MP4"
    shutil.copy(make_video(name="a.mp4"), f)
    scan.scan_volume(conn, root)
    f.unlink()
    stats = scan.scan_volume(conn, root)
    assert stats.missing == 1
    assert conn.execute("select missing from clip").fetchone()[0] == 1
    assert conn.execute("select count(*) from clip").fetchone()[0] == 1


@requires_ffmpeg
def test_roles_and_proxy_linking(tmp_path, make_video):
    conn = db.connect(tmp_path / "c.db")
    root = _vol(tmp_path)
    v = make_video(name="a.mp4")
    shutil.copy(v, root / "DJI_20260916043331_0005_D.MP4")
    shutil.copy(v, root / "DJI_20260916043331_0005_D.LRF")
    (root / "DJI_20260916045140_0007_D.JPG").write_bytes(b"\xff\xd8\xff\xd9")
    scan.scan_volume(conn, root)
    roles = dict(conn.execute("select ext, role from clip"))
    assert roles["MP4"] == "primary" and roles["LRF"] == "proxy" and roles["JPG"] == "photo"
    proxy = conn.execute("select primary_clip_id from clip where ext='LRF'").fetchone()
    primary = conn.execute("select id from clip where ext='MP4'").fetchone()[0]
    assert proxy["primary_clip_id"] == primary


@requires_ffmpeg
def test_non_media_files_are_ignored(tmp_path, make_video):
    conn = db.connect(tmp_path / "c.db")
    root = _vol(tmp_path)
    shutil.copy(make_video(name="a.mp4"), root / "DJI_20260916043331_0005_D.MP4")
    (root / "notes.txt").write_text("hello")
    (root / "readme.md").write_text("hi")
    scan.scan_volume(conn, root)
    assert conn.execute("select count(*) from clip").fetchone()[0] == 1


@requires_ffmpeg
def test_changed_file_is_reprobed_as_update(tmp_path, make_video):
    conn = db.connect(tmp_path / "c.db")
    root = _vol(tmp_path)
    dest = root / "DJI_20260916043331_0005_D.MP4"
    shutil.copy(make_video(name="a.mp4", seconds=1), dest)
    scan.scan_volume(conn, root)
    shutil.copy(make_video(name="b.mp4", seconds=2), dest)
    stats = scan.scan_volume(conn, root)
    assert stats.updated == 1 and stats.inserted == 0
    assert conn.execute("select count(*) from clip").fetchone()[0] == 1


@requires_ffmpeg
def test_camera_db_supplies_flags_and_time(tmp_path, make_video):
    conn = db.connect(tmp_path / "c.db")
    root = _vol(tmp_path)
    name = "DJI_20260915000324_0001_D.MP4"
    shutil.copy(make_video(name="a.mp4"), root / name)
    misc = root / "MISC"; misc.mkdir()
    c = sqlite3.connect(misc / "AC006.db")
    c.executescript("""
      create table gis_info_table(ID integer, dcf_index integer, file_name text,
        star integer, highlight integer, video_index integer);
      create table video_info_table(ID integer, duration integer, frame_num integer,
        frame_den integer, rotation integer, resolution_width integer,
        resolution_height integer, gps_status integer, steady_mode integer,
        fov_type integer, bit_depth integer, model_name text);
      create table mtime_table(dcf_index integer, mtime integer);
    """)
    c.execute("insert into gis_info_table values(1,1048640,?,0,1,79)",
              ("/mnt/DCIM/DJI_001/" + name,))
    c.execute("insert into video_info_table values"
              "(79,71171,30000,1001,90,1920,1080,0,2,1,10,'DJI AC006')")
    c.execute("insert into mtime_table values(1048640,1789430678)")
    c.commit(); c.close()

    scan.scan_volume(conn, root, kind="card")
    row = conn.execute("select highlight, time_source, clock_suspect, camera_model,"
                       " captured_local from clip where ext='MP4'").fetchone()
    assert row["highlight"] == 1
    assert row["time_source"] == "camera_db"
    assert row["clock_suspect"] == 1            # UTC-era clip
    assert row["camera_model"] == "DJI AC006"
    assert row["captured_local"].startswith("2026-09-14T17:")


def test_ingest_card_preserves_camera_db(tmp_path):
    conn = db.connect(tmp_path / "c.db")
    card = tmp_path / "OsmoAction"
    (card / "MISC").mkdir(parents=True)
    sqlite3.connect(card / "MISC" / "AC006.db").close()
    archive = tmp_path / "archive"; archive.mkdir()
    scan.ingest_card(conn, card, archive)
    copies = list((archive / scan.CAMERADB_DIR).glob("*.db"))
    assert len(copies) == 1
    assert conn.execute("select kind from volume").fetchone()[0] == "card"


def test_reingest_keeps_both_camera_db_snapshots(tmp_path):
    conn = db.connect(tmp_path / "c.db")
    card = tmp_path / "OsmoAction"
    (card / "MISC").mkdir(parents=True)
    sqlite3.connect(card / "MISC" / "AC006.db").close()
    archive = tmp_path / "archive"; archive.mkdir()
    import time
    scan.ingest_card(conn, card, archive)
    time.sleep(1.1)
    scan.ingest_card(conn, card, archive)
    assert len(list((archive / scan.CAMERADB_DIR).glob("*.db"))) == 2


def test_missing_camera_db_is_not_an_error(tmp_path):
    conn = db.connect(tmp_path / "c.db")
    plain = tmp_path / "plain"; plain.mkdir()
    archive = tmp_path / "archive"; archive.mkdir()
    scan.ingest_card(conn, plain, archive)


def test_derived_output_is_not_indexed(tmp_path, make_video):
    """The archive holds this pipeline's own JPEGs, which are not footage.

    Filmstrips, caption frames and contact sheets have no EXIF, no camera
    record and no duration. Indexing them as role='photo' made 106 of the
    catalog's 142 photos this tool's own output.
    """
    conn = db.connect(tmp_path / "c.db")
    root = tmp_path / "vol"; root.mkdir()
    shutil.copy(make_video(name="real.mp4", seconds=1),
                root / "DCIM" / "DJI_20260917040000_0000_D.MP4"
                if (root / "DCIM").is_dir() else _dcim(root))
    for d in ("_strips", "_strips2", "_caption", "LOST_CLIPS"):
        (root / d).mkdir(parents=True, exist_ok=True)
        (root / d / "0001.jpg").write_bytes(b"\xff\xd8\xff derived, not footage")

    scan.scan_volume(conn, root)
    rows = conn.execute("select rel_path, role from clip").fetchall()
    paths = [r["rel_path"] for r in rows]
    assert any(p.startswith("DCIM/") for p in paths), "the real clip must still index"
    for d in ("_strips", "_strips2", "_caption", "LOST_CLIPS"):
        assert not any(p.startswith(f"{d}/") for p in paths), f"{d} was indexed"


def _dcim(root):
    (root / "DCIM").mkdir(parents=True, exist_ok=True)
    return root / "DCIM" / "DJI_20260917040000_0000_D.MP4"

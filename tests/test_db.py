from footcat import db


def test_connect_creates_schema(tmp_path):
    conn = db.connect(tmp_path / "catalog.db")
    tables = {r[0] for r in conn.execute(
        "select name from sqlite_master where type='table'")}
    assert {"volume", "clip", "shoot", "episode", "episode_shoot"} <= tables


def test_foreign_keys_and_wal_enabled(tmp_path):
    conn = db.connect(tmp_path / "catalog.db")
    assert conn.execute("pragma foreign_keys").fetchone()[0] == 1
    assert conn.execute("pragma journal_mode").fetchone()[0].lower() == "wal"


def test_generated_columns_flip_on_rotation(tmp_path):
    conn = db.connect(tmp_path / "catalog.db")
    conn.execute("insert into volume(marker_id,label,kind,created_at)"
                 " values('m1','Card','card','2026-09-17T00:00:00Z')")
    conn.execute("""insert into clip(volume_id,rel_path,filename,ext,size_bytes,
        mtime_ns,quick_hash,width,height,rotation,indexed_at)
        values(1,'a.MP4','a.MP4','MP4',1,1,'h',3840,2160,-90,'2026-09-17T00:00:00Z')""")
    row = conn.execute("select display_width,display_height,is_vertical from clip").fetchone()
    assert tuple(row) == (2160, 3840, 1)


def test_unrotated_clip_is_not_vertical(tmp_path):
    conn = db.connect(tmp_path / "catalog.db")
    conn.execute("insert into volume(marker_id,label,kind,created_at)"
                 " values('m1','Card','card','2026-09-17T00:00:00Z')")
    conn.execute("""insert into clip(volume_id,rel_path,filename,ext,size_bytes,
        mtime_ns,quick_hash,width,height,rotation,indexed_at)
        values(1,'b.MP4','b.MP4','MP4',1,1,'h',7680,4320,0,'2026-09-17T00:00:00Z')""")
    row = conn.execute("select display_width,display_height,is_vertical from clip").fetchone()
    assert tuple(row) == (7680, 4320, 0)


def test_reopening_is_idempotent(tmp_path):
    p = tmp_path / "catalog.db"
    db.connect(p).close()
    conn = db.connect(p)
    assert conn.execute("select count(*) from clip").fetchone()[0] == 0

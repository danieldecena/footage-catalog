from footcat import db, shoots


def test_parse_folder_valid():
    assert shoots.parse_folder("2026-09-16_skykomish_coho") == \
        ("2026-09-16", "skykomish", "coho")


def test_parse_folder_rejects_bad_shapes():
    assert shoots.parse_folder("DJI_001") is None
    assert shoots.parse_folder("2026-09-16") is None
    assert shoots.parse_folder("2026-09-16_Skykomish_coho") is None
    assert shoots.parse_folder("2026-09-16_sky komish_coho") is None


def test_parse_folder_allows_hyphens_within_tokens():
    assert shoots.parse_folder("2026-09-16_lake-sammamish_smallmouth-bass") == \
        ("2026-09-16", "lake-sammamish", "smallmouth-bass")


def _setup(tmp_path):
    conn = db.connect(tmp_path / "c.db")
    conn.execute("insert into volume(marker_id,label,kind,created_at)"
                 " values('m','V','card','2026-09-17T00:00:00Z')")
    return conn


def _clip(conn, path, when):
    conn.execute("""insert into clip(volume_id,rel_path,filename,ext,size_bytes,
        mtime_ns,quick_hash,captured_utc,indexed_at,role)
        values(1,?,?,'MP4',1,1,?,?, '2026-09-17T00:00:00Z','primary')""",
        (path, path.rsplit("/", 1)[-1], path, when))


def test_folder_named_clips_share_a_shoot(tmp_path):
    conn = _setup(tmp_path)
    _clip(conn, "2026-09-16_skykomish_coho/a.MP4", "2026-09-16T12:00:00Z")
    _clip(conn, "2026-09-16_skykomish_coho/b.MP4", "2026-09-16T23:00:00Z")
    shoots.assign(conn)
    ids = [r[0] for r in conn.execute("select distinct shoot_id from clip")]
    assert len(ids) == 1
    row = conn.execute("select slug,location,subject,derived_from from shoot").fetchone()
    assert row["slug"] == "2026-09-16_skykomish_coho"
    assert row["location"] == "skykomish" and row["subject"] == "coho"
    assert row["derived_from"] == "folder"


def test_unnamed_folders_cluster_on_four_hour_gap(tmp_path):
    conn = _setup(tmp_path)
    _clip(conn, "DCIM/a.MP4", "2026-09-16T12:00:00Z")
    _clip(conn, "DCIM/b.MP4", "2026-09-16T13:00:00Z")
    _clip(conn, "DCIM/c.MP4", "2026-09-16T20:00:00Z")
    shoots.assign(conn)
    ids = {r[0] for r in conn.execute("select shoot_id from clip")}
    assert len(ids) == 2
    assert conn.execute(
        "select count(*) from shoot where derived_from='time_cluster'").fetchone()[0] == 2


def test_assign_is_idempotent(tmp_path):
    conn = _setup(tmp_path)
    _clip(conn, "DCIM/a.MP4", "2026-09-16T12:00:00Z")
    shoots.assign(conn)
    before = conn.execute("select count(*) from shoot").fetchone()[0]
    shoots.assign(conn)
    assert conn.execute("select count(*) from shoot").fetchone()[0] == before


def test_clips_without_capture_time_are_left_alone(tmp_path):
    conn = _setup(tmp_path)
    conn.execute("""insert into clip(volume_id,rel_path,filename,ext,size_bytes,
        mtime_ns,quick_hash,indexed_at,role)
        values(1,'x.MP4','x.MP4','MP4',1,1,'h','2026-09-17T00:00:00Z','primary')""")
    shoots.assign(conn)
    assert conn.execute("select shoot_id from clip").fetchone()[0] is None

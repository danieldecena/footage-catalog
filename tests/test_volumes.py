import pytest
from footcat import db, volumes


def test_creates_marker_and_row(tmp_path):
    conn = db.connect(tmp_path / "c.db")
    root = tmp_path / "vol"; root.mkdir()
    vid = volumes.resolve(conn, root, kind="card")
    assert (root / volumes.MARKER_NAME).exists()
    row = conn.execute("select label, kind from volume where id=?", (vid,)).fetchone()
    assert row["label"] == "vol" and row["kind"] == "card"


def test_same_volume_resolves_to_same_id(tmp_path):
    conn = db.connect(tmp_path / "c.db")
    root = tmp_path / "vol"; root.mkdir()
    assert volumes.resolve(conn, root) == volumes.resolve(conn, root)


def test_identity_survives_rename(tmp_path):
    conn = db.connect(tmp_path / "c.db")
    root = tmp_path / "old"; root.mkdir()
    vid = volumes.resolve(conn, root)
    new = tmp_path / "new"; root.rename(new)
    assert volumes.resolve(conn, new) == vid


def test_distinct_volumes_get_distinct_ids(tmp_path):
    conn = db.connect(tmp_path / "c.db")
    a = tmp_path / "a"; a.mkdir()
    b = tmp_path / "b"; b.mkdir()
    assert volumes.resolve(conn, a) != volumes.resolve(conn, b)


def test_updates_last_seen_and_path(tmp_path):
    conn = db.connect(tmp_path / "c.db")
    root = tmp_path / "vol"; root.mkdir()
    vid = volumes.resolve(conn, root)
    row = conn.execute("select last_seen_at,last_path from volume where id=?",
                       (vid,)).fetchone()
    assert row["last_seen_at"] and row["last_path"] == str(root)


def test_missing_root_raises(tmp_path):
    conn = db.connect(tmp_path / "c.db")
    with pytest.raises(FileNotFoundError):
        volumes.resolve(conn, tmp_path / "nope")

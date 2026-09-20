import shutil
from footcat import db, scan, media, board
from conftest import requires_ffmpeg


@requires_ffmpeg
def test_board_shape(tmp_path, make_video):
    conn = db.connect(tmp_path / "c.db")
    root = tmp_path / "vol"; root.mkdir()
    shutil.copy(make_video(name="v.mp4", seconds=2),
                root / "DJI_20260917120001_0001_D.MP4")
    scan.scan_volume(conn, root)
    media.analyse(conn, root, with_strips=False)
    d = board.build(conn)
    assert set(d) == {"clips", "archive", "candidates", "at_risk"}
    c = d["clips"][0]
    for k in ("clip","dur","res","curve","bands","segs","words","shoot","gb"):
        assert k in c
    assert c["clip"] == "0001"
    assert isinstance(c["curve"], list) and c["curve"]


@requires_ffmpeg
def test_single_copy_clip_shows_as_at_risk(tmp_path, make_video):
    conn = db.connect(tmp_path / "c.db")
    root = tmp_path / "vol"; root.mkdir()
    shutil.copy(make_video(name="v.mp4", seconds=2),
                root / "DJI_20260917120001_0001_D.MP4")
    scan.scan_volume(conn, root)
    d = board.build(conn)
    assert d["archive"]["single_copy"] == 1
    assert d["at_risk"][0]["filename"].endswith(".MP4")

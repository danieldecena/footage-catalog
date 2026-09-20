import shutil
from footcat import db, scan, captions
from conftest import requires_ffmpeg


def _setup(tmp_path, make_video):
    conn = db.connect(tmp_path / "c.db")
    root = tmp_path / "vol"; root.mkdir()
    shutil.copy(make_video(name="v.mp4", seconds=1),
                root / "DJI_20260917120001_0001_D.MP4")
    scan.scan_volume(conn, root)
    return conn


@requires_ffmpeg
def test_silent_clip_is_pending(tmp_path, make_video):
    conn = _setup(tmp_path, make_video)
    assert len(captions.pending(conn)) == 1


@requires_ffmpeg
def test_a_clip_with_speech_needs_no_caption(tmp_path, make_video):
    conn = _setup(tmp_path, make_video)
    cid = conn.execute("select id from clip").fetchone()[0]
    conn.execute("insert into transcript values(?,?,?,?,?,?)",
                 (cid, 0, 0.0, 1.0, "hello", "small"))
    conn.commit()
    assert captions.pending(conn) == []


@requires_ffmpeg
def test_writing_a_caption_clears_it_from_pending(tmp_path, make_video):
    conn = _setup(tmp_path, make_video)
    assert captions.write(conn, "0001", "a bedroom", ["bedroom", "bed"])
    assert captions.pending(conn) == []


@requires_ffmpeg
def test_caption_is_searchable_by_text_and_keyword(tmp_path, make_video):
    conn = _setup(tmp_path, make_video)
    captions.write(conn, "0001", "bookshelves in a public library", ["library", "books"])
    assert len(captions.search(conn, "library")) == 1
    assert len(captions.search(conn, "books")) == 1
    assert captions.search(conn, "fishing") == []


@requires_ffmpeg
def test_unknown_clip_is_refused(tmp_path, make_video):
    conn = _setup(tmp_path, make_video)
    assert captions.write(conn, "9999", "nothing") is False

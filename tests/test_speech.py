import shutil
from footcat import db, scan, speech
from conftest import requires_ffmpeg


def _setup(tmp_path, make_video):
    conn = db.connect(tmp_path / "c.db")
    root = tmp_path / "vol"; root.mkdir()
    shutil.copy(make_video(name="v.mp4", seconds=1),
                root / "DJI_20260917120001_0001_D.MP4")
    scan.scan_volume(conn, root)
    return conn, root


@requires_ffmpeg
def test_everything_is_pending_before_a_run(tmp_path, make_video):
    conn, _ = _setup(tmp_path, make_video)
    assert len(speech.pending(conn)) == 1


@requires_ffmpeg
def test_a_transcribed_clip_is_not_pending(tmp_path, make_video):
    conn, _ = _setup(tmp_path, make_video)
    cid = conn.execute("select id from clip").fetchone()[0]
    conn.execute("insert into transcript_state values(?,?,?,?)",
                 (cid, speech.MODEL, 3, "2026-09-17T00:00:00Z"))
    conn.commit()
    assert len(speech.pending(conn)) == 0


@requires_ffmpeg
def test_changing_model_makes_it_pending_again(tmp_path, make_video):
    conn, _ = _setup(tmp_path, make_video)
    cid = conn.execute("select id from clip").fetchone()[0]
    conn.execute("insert into transcript_state values(?,?,?,?)",
                 (cid, "base", 3, "2026-09-17T00:00:00Z"))
    conn.commit()
    assert len(speech.pending(conn, "small")) == 1


@requires_ffmpeg
def test_search_finds_text(tmp_path, make_video):
    conn, _ = _setup(tmp_path, make_video)
    cid = conn.execute("select id from clip").fetchone()[0]
    conn.execute("insert into transcript values(?,?,?,?,?,?)",
                 (cid, 0, 1.0, 3.0, "the tide is going out", "small"))
    conn.commit()
    hits = speech.search(conn, "tide")
    assert len(hits) == 1 and hits[0]["start_s"] == 1.0
    assert speech.search(conn, "salmon") == []


def test_missing_dependency_is_not_an_error(tmp_path, monkeypatch):
    from pathlib import Path
    conn = db.connect(tmp_path / "c.db")
    monkeypatch.setattr(speech, "available", lambda: False)
    assert speech.transcribe(conn, Path(tmp_path)) == 0

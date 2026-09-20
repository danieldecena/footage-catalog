import shutil
from footcat import db, scan, verify
from conftest import requires_ffmpeg


def _setup(tmp_path, make_video, n=2, seconds=1):
    conn = db.connect(tmp_path / "c.db")
    root = tmp_path / "vol"; root.mkdir()
    for i in range(n):
        shutil.copy(make_video(name=f"v{i}.mp4", seconds=seconds),
                    root / f"DJI_2026091704000{i}_000{i}_D.MP4")
    scan.scan_volume(conn, root)
    return conn, root


def _expected(conn):
    """What the camera's own index would say, for clips that are intact."""
    return {r["filename"]: r["duration_s"]
            for r in conn.execute("select filename, duration_s from clip")}


@requires_ffmpeg
def test_all_good_is_safe(tmp_path, make_video):
    conn, root = _setup(tmp_path, make_video)
    res = verify.verify(conn, root, expected=_expected(conn))
    assert res.safe and len(res.ok) == 2
    assert "SAFE TO FORMAT" in verify.verdict(res)


@requires_ffmpeg
def test_no_camera_record_is_not_safe(tmp_path, make_video):
    """The case this gate used to pass by accident.

    Without the camera's record there is nothing independent to compare a
    duration against -- the fallback compared ffprobe's answer to the
    duration the scan wrote by probing the same file, so a truncated copy
    agreed with itself and was cleared for deletion. Intact files are still
    intact here; the point is that the gate cannot say so.
    """
    conn, root = _setup(tmp_path, make_video)
    res = verify.verify(conn, root, expected={})
    assert not res.safe
    assert len(res.unchecked) == 2 and not res.bad
    assert "DO NOT FORMAT" in verify.verdict(res)
    assert "could not be checked" in verify.verdict(res)


@requires_ffmpeg
def test_zero_byte_file_is_caught(tmp_path, make_video):
    conn, root = _setup(tmp_path, make_video)
    f = next(root.glob("*.MP4")); f.write_bytes(b"")
    res = verify.verify(conn, root)
    assert not res.safe
    assert any("zero bytes" in why for _, why in res.bad)
    assert "DO NOT FORMAT" in verify.verdict(res)


@requires_ffmpeg
def test_truncated_file_is_caught(tmp_path, make_video):
    conn, root = _setup(tmp_path, make_video)
    f = next(root.glob("*.MP4"))
    data = f.read_bytes(); f.write_bytes(data[: len(data)//3])
    res = verify.verify(conn, root)
    assert not res.safe
    assert any("decode" in why or "duration" in why for _, why in res.bad)


@requires_ffmpeg
def test_duration_mismatch_is_caught(tmp_path, make_video):
    conn, root = _setup(tmp_path, make_video, seconds=1)
    name = next(root.glob("*.MP4")).name
    res = verify.verify(conn, root, expected={name: 99.0})
    assert not res.safe
    assert any("expected 99" in why for _, why in res.bad)


@requires_ffmpeg
def test_missing_file_is_caught(tmp_path, make_video):
    conn, root = _setup(tmp_path, make_video)
    next(root.glob("*.MP4")).unlink()
    res = verify.verify(conn, root)
    assert any("missing" in why for _, why in res.bad)

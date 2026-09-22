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


@requires_ffmpeg
def test_archive_clip_off_the_card_does_not_block(tmp_path, make_video):
    """The 2026-09-20 failure: an archived clip with no camera record,
    not on the card being imported, blocked that card's format verdict."""
    conn, root = _setup(tmp_path, make_video)
    names = sorted(r["filename"] for r in conn.execute("select filename from clip"))
    on_card, off_card = names[0], names[1]
    exp = {k: v for k, v in _expected(conn).items() if k == on_card}
    res = verify.verify(conn, root, expected=exp, only={on_card})
    assert res.safe and res.ok == [on_card] and res.off_card == 1
    assert "SAFE TO FORMAT" in verify.verdict(res)
    assert "not on this card" in verify.verdict(res)


@requires_ffmpeg
def test_card_clip_without_record_still_blocks(tmp_path, make_video):
    conn, root = _setup(tmp_path, make_video)
    name = sorted(r["filename"] for r in conn.execute("select filename from clip"))[0]
    res = verify.verify(conn, root, expected={}, only={name})
    assert not res.safe and len(res.unchecked) == 1
    assert "DO NOT FORMAT" in verify.verdict(res)


@requires_ffmpeg
def test_card_clip_missing_from_archive_blocks(tmp_path, make_video):
    """Scoping must not let an uncopied clip pass by absence."""
    conn, root = _setup(tmp_path, make_video)
    names = {r["filename"] for r in conn.execute("select filename from clip")}
    lost = "DJI_20260920113141_0055_D.MP4"
    res = verify.verify(conn, root, expected=_expected(conn), only=names | {lost})
    assert not res.safe
    assert (lost, "on the card but not in the archive") in res.bad


@requires_ffmpeg
def test_card_clips_reads_only_videos(tmp_path, make_video):
    card = tmp_path / "card" / "DCIM" / "DJI_001"; card.mkdir(parents=True)
    shutil.copy(make_video(name="a.mp4"), card / "DJI_20260920113141_0055_D.MP4")
    (card / "DJI_20260920113141_0055_D.LRF").write_bytes(b"x")
    (card / "._DJI_20260920113141_0055_D.MP4").write_bytes(b"x")
    assert verify.card_clips(tmp_path / "card") == {"DJI_20260920113141_0055_D.MP4"}

import shutil
import json
from footcat import db, scan, media
from conftest import requires_ffmpeg


def _setup(tmp_path, make_video, n=2, seconds=2):
    conn = db.connect(tmp_path / "c.db")
    root = tmp_path / "vol"; root.mkdir()
    for i in range(n):
        shutil.copy(make_video(name=f"v{i}.mp4", seconds=seconds),
                    root / f"DJI_2026091712000{i}_000{i}_D.MP4")
    scan.scan_volume(conn, root)
    return conn, root


def test_frame_count_scales_with_duration():
    assert media.frame_count(5) == 16          # floor
    assert media.frame_count(60) == 30
    assert media.frame_count(700) == 80        # ceiling


@requires_ffmpeg
def test_analyse_writes_rows(tmp_path, make_video):
    conn, root = _setup(tmp_path, make_video)
    n = media.analyse(conn, root, with_strips=False)
    assert n == 2
    assert conn.execute("select count(*) from analysis").fetchone()[0] == 2
    row = conn.execute("select curve, bands, version from analysis").fetchone()
    assert json.loads(row["curve"]) and row["version"] == media.ANALYSIS_VERSION


@requires_ffmpeg
def test_second_run_does_nothing(tmp_path, make_video):
    conn, root = _setup(tmp_path, make_video)
    media.analyse(conn, root, with_strips=False)
    assert media.analyse(conn, root, with_strips=False) == 0
    assert len(media.pending(conn)) == 0


@requires_ffmpeg
def test_new_clip_is_the_only_one_reanalysed(tmp_path, make_video):
    conn, root = _setup(tmp_path, make_video)
    media.analyse(conn, root, with_strips=False)
    shutil.copy(make_video(name="v9.mp4", seconds=2),
                root / "DJI_20260917120009_0009_D.MP4")
    scan.scan_volume(conn, root)
    assert len(media.pending(conn)) == 1
    assert media.analyse(conn, root, with_strips=False) == 1


@requires_ffmpeg
def test_version_bump_reanalyses_everything(tmp_path, make_video, monkeypatch):
    conn, root = _setup(tmp_path, make_video)
    media.analyse(conn, root, with_strips=False)
    monkeypatch.setattr(media, "ANALYSIS_VERSION", media.ANALYSIS_VERSION + 1)
    assert len(media.pending(conn)) == 2


@requires_ffmpeg
def test_proxy_is_preferred_over_the_original(tmp_path, make_video):
    conn, root = _setup(tmp_path, make_video, n=1)
    mp4 = next(root.glob("*.MP4"))
    lrf = mp4.with_suffix(".LRF")
    shutil.copy(mp4, lrf)
    assert media.proxy_for(root, mp4.name) == lrf


@requires_ffmpeg
def test_filmstrip_is_a_data_uri(tmp_path, make_video):
    conn, root = _setup(tmp_path, make_video, n=1, seconds=2)
    s = media.filmstrip(next(root.glob("*.MP4")), 2.0)
    assert s is None or s.startswith("data:image/jpeg;base64,")

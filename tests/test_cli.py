import shutil
from footcat import cli
from conftest import requires_ffmpeg


def test_nothing_mounted_is_silent_success(tmp_path, capsys):
    archive = tmp_path / "archive"; archive.mkdir()
    code = cli.main(["--archive", str(archive), "--scan", str(tmp_path / "absent")])
    assert code == 0
    assert capsys.readouterr().out == ""


def test_missing_archive_is_an_error(tmp_path, capsys):
    code = cli.main(["--archive", str(tmp_path / "nope"), "--scan", str(tmp_path)])
    assert code == 2
    assert "archive" in capsys.readouterr().err.lower()


def test_nothing_mounted_creates_nothing(tmp_path):
    """A scheduled run with no volume present touches nothing at all."""
    archive = tmp_path / "archive"; archive.mkdir()
    assert cli.main(["--archive", str(archive), "--scan", str(tmp_path / "absent")]) == 0
    assert not (archive / "catalog.db").exists()
    assert list(archive.iterdir()) == []


def test_catalog_lands_at_archive_root(tmp_path):
    archive = tmp_path / "archive"; archive.mkdir()
    vol = tmp_path / "vol"; vol.mkdir()
    cli.main(["--archive", str(archive), "--scan", str(vol)])
    assert (archive / "catalog.db").exists()


@requires_ffmpeg
def test_reports_only_when_work_was_done(tmp_path, make_video, capsys):
    archive = tmp_path / "archive"; archive.mkdir()
    vol = tmp_path / "vol"; vol.mkdir()
    shutil.copy(make_video(name="a.mp4"), vol / "DJI_20260916043331_0005_D.MP4")
    assert cli.main(["--archive", str(archive), "--scan", str(vol)]) == 0
    assert "1 new" in capsys.readouterr().out
    assert cli.main(["--archive", str(archive), "--scan", str(vol)]) == 0
    assert capsys.readouterr().out == ""

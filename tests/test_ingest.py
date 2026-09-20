import shutil
import sqlite3
from footcat import db, ingest, media
from conftest import requires_ffmpeg


def _card(tmp_path, make_video, n=2):
    card = tmp_path / "OsmoAction"
    (card / "DCIM" / "DJI_001").mkdir(parents=True)
    (card / "MISC").mkdir()
    sqlite3.connect(card / "MISC" / "AC006.db").close()
    for i in range(n):
        shutil.copy(make_video(name=f"v{i}.mp4", seconds=1),
                    card / "DCIM" / "DJI_001" / f"DJI_2026091712000{i}_000{i}_D.MP4")
    return card


@requires_ffmpeg
def test_full_run_copies_indexes_verifies(tmp_path, make_video):
    card = _card(tmp_path, make_video)
    arch = tmp_path / "archive"
    r = ingest.run(card, arch, do_speech=False, log=lambda *_: None)
    assert r["copied"] >= 2
    assert r["indexed"] == 2
    assert r["safe"] is True and r["bad"] == 0
    assert r["analysed"] == 2
    assert (arch / "catalog.db").exists()
    assert list((arch / "_cameradb").glob("*.db"))


@requires_ffmpeg
def test_second_run_is_nearly_free(tmp_path, make_video):
    card = _card(tmp_path, make_video)
    arch = tmp_path / "archive"
    ingest.run(card, arch, do_speech=False, log=lambda *_: None)
    r = ingest.run(card, arch, do_speech=False, log=lambda *_: None)
    assert r["copied"] == 0
    assert r["indexed"] == 0
    assert r["analysed"] == 0


@requires_ffmpeg
def test_new_clip_only_costs_that_clip(tmp_path, make_video):
    card = _card(tmp_path, make_video)
    arch = tmp_path / "archive"
    ingest.run(card, arch, do_speech=False, log=lambda *_: None)
    shutil.copy(make_video(name="v9.mp4", seconds=1),
                card / "DCIM" / "DJI_001" / "DJI_20260917120009_0009_D.MP4")
    r = ingest.run(card, arch, do_speech=False, log=lambda *_: None)
    assert r["copied"] == 1 and r["indexed"] == 1 and r["analysed"] == 1


@requires_ffmpeg
def test_a_damaged_archive_file_is_recopied_from_the_card(tmp_path, make_video):
    """Self-healing: a truncated archive copy differs in size from the card,
    so the next run replaces it rather than certifying it."""
    card = _card(tmp_path, make_video)
    arch = tmp_path / "archive"
    ingest.run(card, arch, do_speech=False, log=lambda *_: None)
    f = next((arch / "DCIM" / "DJI_001").glob("*.MP4"))
    good = f.stat().st_size
    f.write_bytes(f.read_bytes()[:900])
    r = ingest.run(card, arch, do_speech=False, log=lambda *_: None)
    assert r["copied"] == 1                      # healed
    assert f.stat().st_size == good
    assert r["safe"] is True


@requires_ffmpeg
def test_damage_with_the_card_gone_fails_the_gate(tmp_path, make_video):
    """Nothing to heal from: the gate must refuse."""
    import shutil as _s
    card = _card(tmp_path, make_video)
    arch = tmp_path / "archive"
    ingest.run(card, arch, do_speech=False, log=lambda *_: None)
    _s.rmtree(card)
    f = next((arch / "DCIM" / "DJI_001").glob("*.MP4"))
    f.write_bytes(f.read_bytes()[:900])
    r = ingest.run(None, arch, do_speech=False, log=lambda *_: None)
    assert r["safe"] is False and r["bad"] >= 1


@requires_ffmpeg
def test_part_files_are_never_left_behind(tmp_path, make_video):
    card = _card(tmp_path, make_video)
    arch = tmp_path / "archive"
    ingest.run(card, arch, do_speech=False, log=lambda *_: None)
    assert not list(arch.rglob("*.part"))

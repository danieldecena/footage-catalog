"""Fixtures here are real values measured from Daniel's card on 2026-09-17."""
from datetime import datetime, timezone
from footcat import timeres


def epoch_of(y, mo, d, h, mi, s):
    return int(datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc).timestamp())


def test_parse_filename_stamp():
    assert timeres.parse_filename_stamp("DJI_20260916043331_0005_D.MP4") == \
        datetime(2026, 9, 16, 4, 33, 31)


def test_parse_filename_stamp_rejects_non_dji():
    assert timeres.parse_filename_stamp("IMG_1234.MOV") is None
    assert timeres.parse_filename_stamp("DJI_notadate_0001_D.MP4") is None
    assert timeres.parse_filename_stamp("DJI_20261399999999_0001_D.MP4") is None


def test_epoch_minus_duration_is_capture_start():
    # clip 0005: epoch ends 04:38:54Z, runs 319.53s -> starts 04:33:34Z
    r = timeres.resolve("DJI_20260916043331_0005_D.MP4",
                        epoch=epoch_of(2026, 9, 16, 4, 38, 54), duration_ms=319530,
                        container_creation=None, mtime_ns=0)
    assert r.captured_utc == "2026-09-16T04:33:34Z"
    assert r.time_source == "camera_db"


def test_ignoring_duration_would_misfile_by_the_clip_length():
    # guard against regressing to epoch-as-start
    r = timeres.resolve("DJI_20260917160717_0042_D.MP4",
                        epoch=epoch_of(2026, 9, 17, 23, 20, 31), duration_ms=794500,
                        container_creation=None, mtime_ns=0)
    assert r.captured_utc == "2026-09-17T23:07:16Z"   # 13m14s earlier


def test_utc_era_clip_has_zero_offset_and_is_flagged():
    # clip 0001: camera clock still on UTC
    r = timeres.resolve("DJI_20260915000324_0001_D.MP4",
                        epoch=epoch_of(2026, 9, 15, 0, 4, 38), duration_ms=71171,
                        container_creation=None, mtime_ns=0)
    assert r.clock_offset_min == 0
    assert r.clock_suspect == 1


def test_pacific_era_clip_is_clean():
    # clip 0018: filename 17:46:26 local, epoch ends 00:47:13Z, 44.144s
    r = timeres.resolve("DJI_20260916174626_0018_D.MP4",
                        epoch=epoch_of(2026, 9, 17, 0, 47, 13), duration_ms=44144,
                        container_creation=None, mtime_ns=0)
    assert r.clock_offset_min == -420
    assert r.clock_suspect == 0


def test_clip_0003_lands_on_september_15_pacific():
    # the headline bug: filename says 16 Sep 04:23, truth is 15 Sep 21:23
    r = timeres.resolve("DJI_20260916042301_0003_D.MP4",
                        epoch=epoch_of(2026, 9, 16, 4, 24, 22), duration_ms=77333,
                        container_creation=None, mtime_ns=0)
    assert r.captured_local.startswith("2026-09-15T21:2")


def test_unexpected_offset_is_suspect_and_not_snapped():
    r = timeres.resolve("DJI_20260916174626_0018_D.MP4",
                        epoch=epoch_of(2026, 9, 17, 3, 47, 13), duration_ms=44144,
                        container_creation=None, mtime_ns=0)
    assert r.clock_suspect == 1
    assert r.clock_offset_min not in (0, -420)


def test_no_filename_stamp_leaves_offset_unset():
    r = timeres.resolve("clip.mov", epoch=epoch_of(2026, 9, 17, 0, 0, 0),
                        duration_ms=1000, container_creation=None, mtime_ns=0)
    assert r.clock_offset_min is None and r.clock_suspect == 0
    assert r.captured_utc is not None


def test_falls_back_to_container_creation_with_offset():
    r = timeres.resolve("clip.mov", epoch=None, duration_ms=None,
                        container_creation="2026-07-28T12:10:13-0700", mtime_ns=0)
    assert r.time_source == "quicktime_creationdate"
    assert r.captured_utc == "2026-07-28T19:10:13Z"


def test_falls_back_to_mtime_as_last_resort():
    r = timeres.resolve("clip.mov", epoch=None, duration_ms=None,
                        container_creation=None,
                        mtime_ns=epoch_of(2026, 9, 15, 0, 4, 38) * 10**9)
    assert r.time_source == "mtime"
    assert r.captured_utc == "2026-09-15T00:04:38Z"

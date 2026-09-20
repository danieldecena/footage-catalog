import shutil
import xml.etree.ElementTree as ET
from fractions import Fraction
import pytest
from footcat import db, scan, fcpxml
from conftest import requires_ffmpeg


def test_rate_for_ntsc():
    assert fcpxml.rate(30000, 1001) == (1001, 30000)
    assert fcpxml.rate(60000, 1001) == (1001, 60000)
    assert fcpxml.rate(30, 1) == (1, 30)


def test_times_snap_to_the_frame_grid():
    fd = (1001, 30000)
    assert fcpxml.tval(0, fd) == "0s"
    v = fcpxml.tval(1.0, fd)
    num, den = v[:-1].split("/")
    assert int(num) % 1001 == 0                  # whole frames only
    assert int(den) == 30000
    assert abs(Fraction(int(num), int(den)) - 1) < Fraction(1, 30)


def test_off_grid_value_is_rounded_not_truncated():
    fd = (1001, 30000)
    a = fcpxml.frames(4.52, fd)
    assert a == round(4.52 * 30000 / 1001)


def _built(tmp_path, make_video, marks, **kw):
    conn = db.connect(tmp_path / "c.db")
    root = tmp_path / "vol"; root.mkdir()
    for i in (1, 2):
        shutil.copy(make_video(name=f"v{i}.mp4", seconds=2),
                    root / f"DJI_2026091712000{i}_000{i}_D.MP4")
    scan.scan_volume(conn, root)
    return fcpxml.build(conn, root, marks, **kw)


@requires_ffmpeg
def test_builds_valid_xml(tmp_path, make_video):
    xml = _built(tmp_path, make_video, {"0001": [{"s": 0.2, "e": 1.2}]})
    root = ET.fromstring(xml)
    assert root.tag == "fcpxml"
    assert root.get("version") == fcpxml.FCPXML_VERSION
    assert root.find("resources") is not None
    assert root.find("library/event/project/sequence/spine") is not None


@requires_ffmpeg
def test_marks_become_keyword_ranges_and_markers(tmp_path, make_video):
    xml = _built(tmp_path, make_video, {"0001": [{"s": 0.2, "e": 1.2}]})
    root = ET.fromstring(xml)
    kws = root.findall(".//event/asset-clip/keyword")
    assert len(kws) == 1 and kws[0].get("value") == "select"
    assert len(root.findall(".//event/asset-clip/marker")) == 1


@requires_ffmpeg
def test_stringout_lays_selects_end_to_end(tmp_path, make_video):
    xml = _built(tmp_path, make_video,
                 {"0001": [{"s": 0.0, "e": 1.0}], "0002": [{"s": 0.5, "e": 1.0}]})
    spine = ET.fromstring(xml).find("library/event/project/sequence/spine")
    clips = spine.findall("asset-clip")
    assert len(clips) == 2
    assert clips[0].get("offset") == "0s"
    assert clips[1].get("offset") != "0s"        # second one starts after the first


@requires_ffmpeg
def test_every_time_attribute_is_a_rational(tmp_path, make_video):
    xml = _built(tmp_path, make_video, {"0001": [{"s": 0.37, "e": 1.83}]})
    for el in ET.fromstring(xml).iter():
        for attr in ("offset", "start", "duration", "tcStart", "frameDuration"):
            v = el.get(attr)
            if v is None: continue
            assert v == "0s" or (v.endswith("s") and "/" in v), f"{attr}={v}"


@requires_ffmpeg
def test_asset_src_is_a_file_url(tmp_path, make_video):
    xml = _built(tmp_path, make_video, {"0001": [{"s": 0.2, "e": 1.0}]})
    rep = ET.fromstring(xml).find(".//media-rep")
    assert rep.get("src").startswith("file:///")
    assert rep.get("kind") == "original-media"


@requires_ffmpeg
def test_clip_name_is_used_when_given(tmp_path, make_video):
    xml = _built(tmp_path, make_video, {"0001": [{"s": 0.2, "e": 1.0}]},
                 names={"0001": "First"})
    assert 'name="First"' in xml


@requires_ffmpeg
def test_no_marks_raises(tmp_path, make_video):
    with pytest.raises(ValueError):
        _built(tmp_path, make_video, {"0001": []})


@requires_ffmpeg
def test_media_root_overrides_the_scan_path(tmp_path, make_video):
    import shutil as _s
    from pathlib import Path as _P
    conn = db.connect(tmp_path / "c.db")
    root = tmp_path / "vol"; root.mkdir()
    _s.copy(make_video(name="v.mp4", seconds=2), root / "DJI_20260917120001_0001_D.MP4")
    scan.scan_volume(conn, root)
    xml = fcpxml.build(conn, root, {"0001": [{"s": 0.2, "e": 1.0}]},
                       media_root=_P("/Users/home/Movies/Footage/import"))
    src = ET.fromstring(xml).find(".//media-rep").get("src")
    assert src.startswith("file:///Users/home/Movies/Footage/import/")
    assert "/tmp" not in src and str(tmp_path) not in src

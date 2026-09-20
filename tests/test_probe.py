from footcat import probe
from conftest import requires_ffmpeg


def test_side_data_wins_over_legacy_tag():
    stream = {"side_data_list": [{"rotation": -90}], "tags": {"rotate": "90"}}
    assert probe.parse_rotation(stream) == -90


def test_legacy_tag_is_negated_when_no_side_data():
    assert probe.parse_rotation({"tags": {"rotate": "90"}}) == -90
    assert probe.parse_rotation({"tags": {"rotate": "270"}}) == -270


def test_no_rotation_info_is_zero():
    assert probe.parse_rotation({}) == 0
    assert probe.parse_rotation({"side_data_list": [{"displaymatrix": "..."}]}) == 0


def test_float_rotation_is_rounded():
    assert probe.parse_rotation({"side_data_list": [{"rotation": -90.0}]}) == -90


def test_display_dims_flip_on_quarter_turns():
    assert probe.display_dims(3840, 2160, -90) == (2160, 3840)
    assert probe.display_dims(3840, 2160, 90) == (2160, 3840)
    assert probe.display_dims(3840, 2160, 270) == (2160, 3840)
    assert probe.display_dims(3840, 2160, 180) == (3840, 2160)
    assert probe.display_dims(3840, 2160, 0) == (3840, 2160)


def test_aspect_labels():
    assert probe.aspect_label(7680, 4320) == "16:9"
    assert probe.aspect_label(3840, 2880) == "4:3"
    assert probe.aspect_label(2160, 3840) == "9:16"
    assert probe.aspect_label(1000, 999) == "other"


@requires_ffmpeg
def test_probe_reads_real_file(make_video):
    r = probe.probe(make_video(w=320, h=240, seconds=1))
    assert r.width == 320 and r.height == 240
    assert r.vcodec == "h264" and r.acodec == "aac"
    assert 0.9 < r.duration_s < 1.3
    assert r.rotation == 0
    assert r.fps_num == 30 and r.fps_den == 1


# NOTE: newer ffmpeg ignores `-metadata:s:v:0 rotate=`, so a synthetic rotated
# file can't be produced reliably across versions. The rotation LOGIC is fully
# covered by the parse_rotation/display_dims unit tests above; the end-to-end
# case is verified against a real rotated clip in test_real_card.py (clip 0001).


@requires_ffmpeg
def test_probe_reports_zero_rotation_for_unrotated_file(make_video):
    r = probe.probe(make_video(name="flat.mp4", w=320, h=240))
    assert r.rotation == 0
    assert probe.display_dims(r.width, r.height, r.rotation) == (320, 240)


@requires_ffmpeg
def test_probe_of_nonvideo_returns_empty(tmp_path):
    p = tmp_path / "x.MP4"; p.write_bytes(b"not a video")
    assert probe.probe(p).vcodec is None

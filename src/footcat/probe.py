"""ffprobe wrapper.

Two traps this module exists to handle:
  * ffprobe 4.4 emits BOTH side_data rotation and the legacy `rotate` tag,
    with opposite signs. Side data wins; the legacy tag is negated.
  * Osmo clips report coded_height 1088 against a real height of 1080, so
    orientation must be derived from display dimensions, never coded_*.
"""
import json
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

PROBE_VERSION = 1
_ASPECTS = {Fraction(16, 9): "16:9", Fraction(4, 3): "4:3", Fraction(9, 16): "9:16",
            Fraction(3, 4): "3:4"}


@dataclass
class ProbeResult:
    duration_s: float | None = None
    vcodec: str | None = None
    acodec: str | None = None
    width: int | None = None
    height: int | None = None
    coded_width: int | None = None
    coded_height: int | None = None
    rotation: int = 0
    fps_num: int | None = None
    fps_den: int | None = None
    bit_rate: int | None = None
    camera_model: str | None = None
    container_creation: str | None = None


def parse_rotation(stream: dict) -> int:
    for sd in stream.get("side_data_list") or []:
        if "rotation" in sd:
            try:
                return int(round(float(sd["rotation"])))
            except (TypeError, ValueError):
                return 0
    tags = stream.get("tags") or {}
    if "rotate" in tags:
        try:
            return -int(round(float(tags["rotate"])))
        except (TypeError, ValueError):
            return 0
    return 0


def display_dims(width, height, rotation: int):
    if width is None or height is None:
        return (width, height)
    return (height, width) if abs(rotation) % 180 == 90 else (width, height)


def aspect_label(w, h) -> str:
    if not w or not h:
        return "other"
    return _ASPECTS.get(Fraction(int(w), int(h)), "other")


def probe(path: Path) -> ProbeResult:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True)
    if proc.returncode != 0 or not proc.stdout.strip():
        return ProbeResult()
    data = json.loads(proc.stdout)
    fmt = data.get("format", {}) or {}
    ftags = fmt.get("tags", {}) or {}
    r = ProbeResult(
        camera_model=ftags.get("encoder") or ftags.get("com.apple.quicktime.model"),
        container_creation=ftags.get("com.apple.quicktime.creationdate")
                           or ftags.get("creation_time"))
    if fmt.get("duration"):
        r.duration_s = float(fmt["duration"])
    if fmt.get("bit_rate"):
        r.bit_rate = int(fmt["bit_rate"])

    for s in data.get("streams", []):
        kind = s.get("codec_type")
        if kind == "video" and r.vcodec is None:
            if (s.get("disposition") or {}).get("attached_pic"):
                continue                      # embedded thumbnail, not the track
            r.vcodec = s.get("codec_name")
            r.width, r.height = s.get("width"), s.get("height")
            r.coded_width, r.coded_height = s.get("coded_width"), s.get("coded_height")
            r.rotation = parse_rotation(s)
            rate = s.get("r_frame_rate") or ""
            if "/" in rate:
                num, den = rate.split("/", 1)
                if int(den):
                    r.fps_num, r.fps_den = int(num), int(den)
        elif kind == "audio" and r.acodec is None:
            r.acodec = s.get("codec_name")
    return r

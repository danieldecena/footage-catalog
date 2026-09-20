"""Turn marked ranges into an FCPXML that Final Cut can open.

Two outputs from the same marks:
  * a STRINGOUT — a sequence of just the marked ranges, laid end to end
  * KEYWORD RANGES — the marks applied to the clips in the event browser

Times must be frame-aligned rationals ("1001/30000s"); Final Cut rejects
floats and off-grid values, so every boundary is snapped to a frame here.
"""
import sqlite3
from fractions import Fraction
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape, quoteattr

FCPXML_VERSION = "1.13"


def rate(fps_num: int, fps_den: int) -> tuple[int, int]:
    """Frame duration as (numerator, denominator) — 29.97 -> (1001, 30000)."""
    f = Fraction(fps_den or 1, fps_num or 30)
    return f.numerator, f.denominator


def tval(seconds: float, fd: tuple[int, int]) -> str:
    """Snap seconds to the frame grid and render as an FCPXML rational."""
    num, den = fd
    frames = round(seconds * den / num)
    n = frames * num
    return "0s" if n == 0 else f"{n}/{den}s"


def frames(seconds: float, fd: tuple[int, int]) -> int:
    num, den = fd
    return round(seconds * den / num)


def _fileurl(p: Path) -> str:
    """Absolute file URL. The path is used verbatim — the caller is
    responsible for passing the path as the MACHINE RUNNING FINAL CUT sees
    it, which is not necessarily where this process has the files mounted."""
    return "file://" + quote(str(p))


def build(conn: sqlite3.Connection, root: Path, marks: dict,
          names: dict | None = None, event: str = "Selects",
          project: str = "Stringout", media_root: Path | None = None) -> str:
    """marks: {clip_index: [{'s':float,'e':float}, ...]}

    `root` is where this process reads the catalog; `media_root` is where
    Final Cut will find the footage. They differ whenever the scanner runs
    somewhere the files are mounted under another path — get this wrong and
    every clip opens offline.
    """
    media_root = Path(media_root) if media_root else Path(root)
    names = names or {}
    rows = {}
    for r in conn.execute(
            "select filename, rel_path, duration_s, display_width w, display_height h,"
            " fps_num, fps_den from clip where role='primary'"):
        rows[r["filename"].split("_")[2]] = dict(r)

    used = [(k, v) for k, v in sorted(marks.items()) if v and k in rows]
    if not used:
        raise ValueError("no marks to export")

    # one <format> per distinct geometry+rate
    formats, fmt_id = {}, {}
    for k, _ in used:
        r = rows[k]
        fd = rate(r["fps_num"] or 30000, r["fps_den"] or 1001)
        key = (r["w"], r["h"], fd)
        if key not in formats:
            formats[key] = f"r{len(formats)+1}"
        fmt_id[k] = formats[key]

    seq_key = max(((k, sum(x["e"] - x["s"] for x in v)) for k, v in used),
                  key=lambda t: t[1])[0]
    seq_fmt_key = (rows[seq_key]["w"], rows[seq_key]["h"],
                   rate(rows[seq_key]["fps_num"], rows[seq_key]["fps_den"]))
    seq_fd = seq_fmt_key[2]

    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<!DOCTYPE fcpxml>', f'<fcpxml version="{FCPXML_VERSION}">', '  <resources>']

    for (w, h, fd), fid in formats.items():
        out.append(f'    <format id="{fid}" name="FFVideoFormat{h}p" '
                   f'frameDuration="{fd[0]}/{fd[1]}s" width="{w}" height="{h}"/>')

    asset_id = {}
    n = len(formats)
    for k, _ in used:
        r = rows[k]
        n += 1
        aid = f"r{n}"
        asset_id[k] = aid
        fd = rate(r["fps_num"], r["fps_den"])
        src = _fileurl(media_root / r["rel_path"])
        out.append(
            f'    <asset id="{aid}" name={quoteattr(r["filename"])} uid={quoteattr("FC"+k)} '
            f'start="0s" duration="{tval(r["duration_s"] or 0, fd)}" '
            f'hasVideo="1" hasAudio="1" audioSources="1" audioChannels="2" '
            f'format="{fmt_id[k]}">')
        out.append(f'      <media-rep kind="original-media" src="{src}"/>')
        out.append('    </asset>')
    out.append('  </resources>')

    out.append(f'  <library>')
    out.append(f'    <event name={quoteattr(event)}>')

    # 1. the clips in the browser, carrying keyword ranges for each mark
    for k, ranges in used:
        r = rows[k]
        fd = rate(r["fps_num"], r["fps_den"])
        out.append(f'      <asset-clip ref="{asset_id[k]}" name={quoteattr(names.get(k) or r["filename"])} '
                   f'offset="0s" start="0s" duration="{tval(r["duration_s"] or 0, fd)}" '
                   f'format="{fmt_id[k]}">')
        for i, rg in enumerate(ranges, 1):
            out.append(f'        <keyword start="{tval(rg["s"], fd)}" '
                       f'duration="{tval(rg["e"]-rg["s"], fd)}" value="select"/>')
            out.append(f'        <marker start="{tval(rg["s"], fd)}" duration="{tval(1/30, fd)}" '
                       f'value={quoteattr((names.get(k) or "select")+f" {i}")}/>')
        out.append('      </asset-clip>')

    # 2. the stringout: every marked range, end to end
    total = sum(rg["e"] - rg["s"] for _, rs in used for rg in rs)
    out.append(f'      <project name={quoteattr(project)}>')
    out.append(f'        <sequence format="{formats[seq_fmt_key]}" '
               f'duration="{tval(total, seq_fd)}" tcStart="0s" tcFormat="NDF" '
               f'audioLayout="stereo" audioRate="48k">')
    out.append('          <spine>')
    off = 0.0
    for k, ranges in used:
        r = rows[k]
        fd = rate(r["fps_num"], r["fps_den"])
        for rg in ranges:
            dur = rg["e"] - rg["s"]
            out.append(
                f'            <asset-clip ref="{asset_id[k]}" '
                f'name={quoteattr(names.get(k) or r["filename"])} '
                f'offset="{tval(off, seq_fd)}" start="{tval(rg["s"], fd)}" '
                f'duration="{tval(dur, fd)}" format="{fmt_id[k]}" tcFormat="NDF"/>')
            off += dur
    out.append('          </spine>')
    out.append('        </sequence>')
    out.append('      </project>')
    out.append('    </event>')
    out.append('  </library>')
    out.append('</fcpxml>')
    return "\n".join(out) + "\n"

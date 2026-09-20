"""Emit everything the review board renders, as one JSON document."""
import json
import sqlite3
from pathlib import Path

from . import archive


def build(conn: sqlite3.Connection) -> dict:
    clips = []
    for r in conn.execute("""
        select c.id, c.filename, c.duration_s, c.captured_local, c.display_width w,
               c.display_height h, c.is_vertical, c.highlight, c.star, c.clock_suspect,
               c.fps_num, c.fps_den, c.size_bytes, c.aspect, c.gps_status,
               c.steady_mode, c.fov_type, c.bit_depth, c.app_audio,
               a.median_db, a.dynamics, a.active_pct, a.bands, a.curve, a.strip,
               s.slug shoot
        from clip c
        left join analysis a on a.clip_id = c.id
        left join shoot s on s.id = c.shoot_id
        where c.role='primary' and c.missing=0
          and c.id = (select min(c2.id) from clip c2
                      where c2.quick_hash = c.quick_hash and c2.role='primary'
                        and c2.missing=0)
        order by c.captured_utc"""):
        cid = r["id"]
        segs = [dict(s=t["start_s"], e=t["end_s"], t=t["text"]) for t in conn.execute(
            "select start_s,end_s,text from transcript where clip_id=? order by seg", (cid,))]
        cap = conn.execute("select text, keywords from caption where clip_id=?",
                           (cid,)).fetchone()
        clips.append(dict(
            clip=r["filename"].split("_")[2], file=r["filename"],
            dur=round(r["duration_s"] or 0, 2), local=r["captured_local"] or "",
            day=(r["captured_local"] or "")[:10],
            hour=int((r["captured_local"] or "1970-01-01T00")[11:13] or 0),
            res=f'{r["w"]}x{r["h"]}', vertical=r["is_vertical"],
            highlight=r["highlight"], star=r["star"], suspect=r["clock_suspect"],
            gb=round((r["size_bytes"] or 0) / 1073741824, 2),
            fps=round((r["fps_num"] or 0) / (r["fps_den"] or 1), 2),
            fov=r["fov_type"], depth=r["bit_depth"],
            audio=("external" if r["app_audio"] else "internal mic"), shoot=r["shoot"] or "unsorted",
            median_db=r["median_db"], dynamics=r["dynamics"],
            active_pct=r["active_pct"] or 0,
            bands=json.loads(r["bands"] or "[]"), curve=json.loads(r["curve"] or "[]"),
            strip=r["strip"] or "", segs=segs,
            caption=(cap["text"] if cap else ""),
            keywords=(json.loads(cap["keywords"]) if cap and cap["keywords"] else []),
            words=sum(len(s["t"].split()) for s in segs)))
    return dict(clips=clips,
                archive=archive.summary(conn),
                candidates=archive.candidates(conn)[:60],
                at_risk=archive.at_risk(conn)[:60])


def main(argv=None) -> int:
    import argparse
    from . import db as _db
    ap = argparse.ArgumentParser(prog="footcat-board")
    ap.add_argument("--archive", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    conn = _db.connect(Path(a.archive) / "catalog.db")
    data = build(conn)
    Path(a.out).write_text(json.dumps(data, separators=(",", ":")))
    print(f"{len(data['clips'])} clips -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

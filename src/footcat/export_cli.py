"""footcat.export_cli — marks JSON + catalog -> FCPXML."""
import argparse, json, sys
from pathlib import Path
from . import db, fcpxml


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="footcat-export")
    ap.add_argument("--archive", required=True)
    ap.add_argument("--marks", required=True, help="JSON from the review board")
    ap.add_argument("--out", required=True)
    ap.add_argument("--event", default="Selects")
    ap.add_argument("--project", default="Stringout")
    ap.add_argument("--media-root", help="path to the archive AS FINAL CUT SEES IT "
                    "(defaults to --archive; set it when the scanner runs elsewhere)")
    a = ap.parse_args(argv)

    archive = Path(a.archive)
    raw = json.load(open(a.marks))
    docs = raw["documents"] if isinstance(raw, dict) and "documents" in raw else raw
    marks, names = {}, {}
    for d in docs:
        body = d.get("data", d)
        clip = body.get("clip") or d.get("id")
        if not clip: continue
        if body.get("ranges"): marks[clip] = body["ranges"]
        if body.get("name"):   names[clip] = body["name"]

    conn = db.connect(archive / "catalog.db")
    try:
        xml = fcpxml.build(conn, archive, marks, names=names,
                           event=a.event, project=a.project,
                           media_root=Path(a.media_root) if a.media_root else archive)
    except ValueError as e:
        print(f"nothing to export: {e}", file=sys.stderr); return 1
    Path(a.out).write_text(xml)
    n = sum(len(v) for v in marks.values())
    print(f"{n} selects from {len(marks)} clips -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

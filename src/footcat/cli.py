"""footcat — scan, ingest, export."""
import argparse
import sys
from pathlib import Path

from . import db, ingest, scan


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="footcat")
    ap.add_argument("--archive", required=True, help="archive root; the catalog lives here")
    ap.add_argument("--card", action="append", default=[],
                    help="camera/card root to ingest (repeatable)")
    ap.add_argument("--scan", action="append", default=[],
                    help="volume to index without copying (repeatable)")
    ap.add_argument("--no-speech", action="store_true")
    ap.add_argument("--budget", type=float, default=0,
                    help="seconds per stage before stopping; resume by re-running")
    a = ap.parse_args(argv)

    archive = Path(a.archive)
    if not archive.is_dir():
        print(f"archive root not found: {archive}", file=sys.stderr)
        return 2

    quiet = True
    for raw in a.card:
        root = Path(raw)
        if not root.is_dir():
            continue                      # not plugged in: silent, not an error
        quiet = False
        r = ingest.run(root, archive, budget_s=a.budget, do_speech=not a.no_speech)
        if not r.get("safe"):
            return 1

    for raw in a.scan:
        root = Path(raw)
        if not root.is_dir():
            continue
        quiet = False
        conn = db.connect(archive / ingest.CATALOG)
        s = scan.scan_volume(conn, root)
        if s.changed:
            print(f"{root.name}: +{s.inserted} new, {s.updated} updated, "
                  f"{s.moved} moved, {s.missing} missing")
        conn.close()

    if quiet and not a.card and not a.scan:
        ingest.run(None, archive, budget_s=a.budget, do_speech=not a.no_speech)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

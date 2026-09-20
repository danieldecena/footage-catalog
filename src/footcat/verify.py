"""The decode gate.

A file count is not proof. Today's lesson: a 0-byte stub and a truncated 3 GB
copy both look like files in Finder, and neither plays. Nothing is declared
safe until every clip has been opened, decoded, and its duration checked
against the camera's own record.
"""
import json
import subprocess
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

TOLERANCE_S = 1.0


@dataclass
class VerifyResult:
    ok: list = field(default_factory=list)
    bad: list = field(default_factory=list)        # (name, reason)
    # Decoded cleanly, but with nothing independent to check the duration
    # against. NOT the same as verified -- see verify() below.
    unchecked: list = field(default_factory=list)

    @property
    def safe(self) -> bool:
        return bool(self.ok) and not self.bad and not self.unchecked


def decodes(path: Path) -> float | None:
    """Return duration in seconds, or None if the file will not decode."""
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True)
    if p.returncode != 0:
        return None
    try:
        return float(p.stdout.strip())
    except ValueError:
        return None


def verify(conn: sqlite3.Connection, root: Path,
           expected: dict[str, float] | None = None) -> VerifyResult:
    """Decode every primary clip under root; compare to expected durations.

    `expected` maps filename -> duration in seconds (from the camera index).
    """
    res = VerifyResult()
    rows = conn.execute(
        "select rel_path, filename, duration_s from clip"
        " where role='primary' and missing=0").fetchall()
    for r in rows:
        p = root / r["rel_path"]
        if not p.exists():
            res.bad.append((r["filename"], "file missing")); continue
        if p.stat().st_size == 0:
            res.bad.append((r["filename"], "zero bytes")); continue
        got = decodes(p)
        if got is None:
            res.bad.append((r["filename"], "will not decode — truncated?")); continue
        # Only the camera's record is an independent expectation. Falling
        # back to r["duration_s"] compared ffprobe's answer to ffprobe's own
        # answer -- the scan wrote that column by probing this same file --
        # so a truncated copy probed short twice, agreed with itself, and
        # was declared safe. A check that cannot fail is not a check, and
        # this one gates deleting the original.
        want = (expected or {}).get(r["filename"])
        if want is None:
            res.unchecked.append((r["filename"], "no camera record to check against"))
            continue
        if abs(got - want) > TOLERANCE_S:
            res.bad.append((r["filename"],
                            f"duration {got:.1f}s vs expected {want:.1f}s")); continue
        res.ok.append(r["filename"])
    return res


def verdict(res: VerifyResult) -> str:
    if res.safe:
        return f"SAFE TO FORMAT — {len(res.ok)}/{len(res.ok)} clips verified"
    n = len(res.bad) + len(res.unchecked)
    lines = [f"DO NOT FORMAT — {n} problem(s), {len(res.ok)} verified"]
    lines += [f"  {name}: {why}" for name, why in res.bad]
    if res.unchecked:
        # Named, not silently folded into the pass. The usual cause is the
        # camera index missing from MISC/, which is recoverable.
        lines.append(f"  {len(res.unchecked)} clip(s) decoded but could not be "
                     f"checked against the camera's record")
        lines += [f"    {name}" for name, _ in res.unchecked[:5]]
        if len(res.unchecked) > 5:
            lines.append(f"    ... and {len(res.unchecked) - 5} more")
    return "\n".join(lines)

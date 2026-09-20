"""Which footage is dead weight, and what is safe to remove.

The hard rule, learned expensively: nothing is ever an archive candidate
unless a second copy exists. A tool that says "safe to delete" has to be
right, or it is worse than having no tool.
"""
import json
import sqlite3

MICRO_S = 1.0          # under this, archive unwatched
SHORT_S = 3.0


def copies(conn: sqlite3.Connection) -> dict:
    """quick_hash -> number of distinct volumes holding it."""
    out = {}
    for r in conn.execute(
            "select quick_hash, count(distinct volume_id) n from clip"
            " where role='primary' group by quick_hash"):
        out[r["quick_hash"]] = r["n"]
    return out


def flagged_hashes(conn: sqlite3.Connection) -> set:
    """Content you flagged, by hash — a flag on any copy protects them all."""
    return {r[0] for r in conn.execute(
        "select quick_hash from clip where role='primary'"
        " and (highlight=1 or star=1)")}


def candidates(conn: sqlite3.Connection) -> list:
    """Removal candidates, worst first. Only ever clips with 2+ copies.

    One row per distinct clip, never one per copy: with the footage on two
    drives every clip is two rows, and counting both would claim twice the
    reclaimable space. Removing a candidate means dropping ONE of its copies.
    """
    cp = copies(conn)
    flagged = flagged_hashes(conn)
    rows = []
    seen = set()
    for r in conn.execute(
            "select c.id, c.filename, c.duration_s, c.size_bytes, c.quick_hash,"
            " c.highlight, c.star, a.active_pct, a.bands,"
            " (select count(*) from transcript t where t.clip_id=c.id) segs"
            " from clip c left join analysis a on a.clip_id=c.id"
            " where c.role='primary' and c.missing=0"):
        n = cp.get(r["quick_hash"], 1)
        dur = r["duration_s"] or 0
        active = r["active_pct"] or 0
        reasons = []
        if dur < MICRO_S:
            reasons.append("under a second")
        elif dur < SHORT_S:
            reasons.append("very short")
        if active == 0 and dur >= MICRO_S:
            reasons.append("no audio activity")
        if r["segs"] == 0 and dur >= SHORT_S:
            reasons.append("no speech")
        if not reasons:
            continue
        if r["quick_hash"] in flagged:
            continue                    # flagged on any copy protects every copy
        if r["quick_hash"] in seen:
            continue                    # already counted this clip via another copy
        seen.add(r["quick_hash"])
        gb = (r["size_bytes"] or 0) / 1073741824
        score = gb * (1 if dur < MICRO_S else 0.6 if active == 0 else 0.3)
        rows.append(dict(filename=r["filename"], duration_s=round(dur, 1),
                         gb=round(gb, 2), copies=n, reasons=reasons,
                         safe=n > 1, score=round(score, 3)))
    rows.sort(key=lambda x: (-x["safe"], -x["score"]))
    return rows


def at_risk(conn: sqlite3.Connection) -> list:
    """Clips that exist on exactly one volume — the real danger list."""
    cp = copies(conn)
    out = []
    for r in conn.execute(
            "select filename, quick_hash, size_bytes, duration_s from clip"
            " where role='primary' and missing=0"):
        if cp.get(r["quick_hash"], 1) <= 1:
            out.append(dict(filename=r["filename"],
                            gb=round((r["size_bytes"] or 0) / 1073741824, 2),
                            duration_s=round(r["duration_s"] or 0, 1)))
    out.sort(key=lambda x: -x["gb"])
    return out


def summary(conn: sqlite3.Connection) -> dict:
    c = candidates(conn)
    risk = at_risk(conn)
    return dict(
        candidates=len(c),
        reclaimable_gb=round(sum(x["gb"] for x in c if x["safe"]), 2),
        blocked_gb=round(sum(x["gb"] for x in c if not x["safe"]), 2),
        single_copy=len(risk),
        single_copy_gb=round(sum(x["gb"] for x in risk), 2))

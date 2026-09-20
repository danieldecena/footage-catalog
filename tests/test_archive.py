from footcat import db, archive


def _clip(conn, vol, name, dur, gb, h=0, hl=0, active=None, segs=0):
    cur = conn.execute("""insert into clip(volume_id,rel_path,filename,ext,size_bytes,
        mtime_ns,quick_hash,duration_s,highlight,indexed_at,role)
        values(?,?,?,'MP4',?,1,?,?,?,'2026-09-17T00:00:00Z','primary')""",
        (vol, name, name, int(gb*1073741824), h or name, dur, hl))
    cid = cur.lastrowid
    if active is not None:
        conn.execute("insert into analysis(clip_id,version,active_pct,analysed_at)"
                     " values(?,1,?,'x')", (cid, active))
    for i in range(segs):
        conn.execute("insert into transcript values(?,?,?,?,?,?)",
                     (cid, i, 0.0, 1.0, "hi", "small"))
    conn.commit(); return cid


def _db(tmp_path, vols=2):
    conn = db.connect(tmp_path/"c.db")
    for i in range(vols):
        conn.execute("insert into volume(marker_id,label,kind,created_at)"
                     " values(?,?,?,?)", (f"m{i}", f"V{i}", "external", "x"))
    conn.commit(); return conn


def test_micro_clip_with_two_copies_is_safe(tmp_path):
    conn=_db(tmp_path)
    _clip(conn,1,"a.MP4",0.5,0.01,h="hh"); _clip(conn,2,"a.MP4",0.5,0.01,h="hh")
    c=archive.candidates(conn)
    assert c and c[0]["safe"] is True and "under a second" in c[0]["reasons"]


def test_single_copy_is_never_safe_to_remove(tmp_path):
    conn=_db(tmp_path)
    _clip(conn,1,"a.MP4",0.5,0.01,h="only")
    c=archive.candidates(conn)
    assert c[0]["safe"] is False and c[0]["copies"] == 1


def test_flagged_clip_is_never_a_candidate(tmp_path):
    conn=_db(tmp_path)
    _clip(conn,1,"a.MP4",0.5,0.01,h="hh",hl=1); _clip(conn,2,"a.MP4",0.5,0.01,h="hh")
    assert all(x["filename"]!="a.MP4" or x["safe"] for x in archive.candidates(conn))
    names=[x["filename"] for x in archive.candidates(conn)]
    assert names == []                       # highlight excludes it entirely


def test_silent_long_clip_is_flagged_but_not_micro(tmp_path):
    conn=_db(tmp_path)
    _clip(conn,1,"b.MP4",30,1.0,h="bb",active=0); _clip(conn,2,"b.MP4",30,1.0,h="bb")
    r=[x for x in archive.candidates(conn) if x["filename"]=="b.MP4"][0]
    assert "no audio activity" in r["reasons"] and "under a second" not in r["reasons"]


def test_clip_with_speech_and_activity_is_not_a_candidate(tmp_path):
    conn=_db(tmp_path)
    _clip(conn,1,"c.MP4",30,1.0,h="cc",active=40,segs=3)
    assert [x for x in archive.candidates(conn) if x["filename"]=="c.MP4"] == []


def test_at_risk_lists_single_copy_clips_biggest_first(tmp_path):
    conn=_db(tmp_path)
    _clip(conn,1,"big.MP4",60,8.0,h="b1")
    _clip(conn,1,"small.MP4",60,1.0,h="s1")
    _clip(conn,1,"dup.MP4",60,2.0,h="dd"); _clip(conn,2,"dup.MP4",60,2.0,h="dd")
    r=archive.at_risk(conn)
    assert [x["filename"] for x in r] == ["big.MP4","small.MP4"]


def test_summary_separates_reclaimable_from_blocked(tmp_path):
    conn=_db(tmp_path)
    _clip(conn,1,"a.MP4",0.5,2.0,h="hh"); _clip(conn,2,"a.MP4",0.5,2.0,h="hh")
    _clip(conn,1,"b.MP4",0.5,3.0,h="only")
    s=archive.summary(conn)
    assert s["reclaimable_gb"] > 0 and s["blocked_gb"] > 0
    assert s["single_copy"] >= 1


def test_a_clip_on_two_drives_is_one_candidate_not_two(tmp_path):
    """Two copies of the same clip must not double the reclaimable figure."""
    conn = _db(tmp_path, vols=2)
    _clip(conn, 1, "mac/a.MP4", dur=0.4, gb=2, h="samehash")
    _clip(conn, 2, "ssd/a.MP4", dur=0.4, gb=2, h="samehash")
    c = archive.candidates(conn)
    assert len(c) == 1, f"expected one candidate, got {len(c)}"
    assert c[0]["copies"] == 2 and c[0]["safe"] is True
    s = archive.summary(conn)
    assert s["reclaimable_gb"] == 2.0, s        # one copy, not both
    assert s["single_copy"] == 0

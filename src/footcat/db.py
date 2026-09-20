"""Catalog schema and connection.

Machine-owned tables (volume, clip, shoot) can be deleted and rebuilt from
disk at any time. Human-owned tables (episode, episode_shoot) cannot.
"""
from pathlib import Path
import sqlite3

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS volume (
  id INTEGER PRIMARY KEY,
  marker_id TEXT NOT NULL UNIQUE,
  label TEXT,
  kind TEXT CHECK(kind IN ('card','internal','external','archive')),
  last_seen_at TEXT,
  last_path TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS shoot (
  id INTEGER PRIMARY KEY,
  slug TEXT UNIQUE,
  title TEXT,
  location TEXT,
  subject TEXT,
  started_utc TEXT,
  ended_utc TEXT,
  derived_from TEXT CHECK(derived_from IN ('folder','time_cluster','manual')),
  notes TEXT
);

CREATE TABLE IF NOT EXISTS clip (
  id INTEGER PRIMARY KEY,
  volume_id INTEGER NOT NULL REFERENCES volume(id) ON DELETE CASCADE,
  rel_path TEXT NOT NULL,
  filename TEXT NOT NULL,
  ext TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'primary'
       CHECK(role IN ('primary','proxy','photo')),
  primary_clip_id INTEGER REFERENCES clip(id),
  size_bytes INTEGER NOT NULL,
  mtime_ns INTEGER NOT NULL,
  inode INTEGER,
  quick_hash TEXT NOT NULL,
  content_hash TEXT,
  duration_s REAL,
  vcodec TEXT,
  acodec TEXT,
  width INTEGER,
  height INTEGER,
  coded_width INTEGER,
  coded_height INTEGER,
  rotation INTEGER NOT NULL DEFAULT 0,
  display_width INTEGER GENERATED ALWAYS AS
    (CASE WHEN abs(rotation)%180=90 THEN height ELSE width END) STORED,
  display_height INTEGER GENERATED ALWAYS AS
    (CASE WHEN abs(rotation)%180=90 THEN width ELSE height END) STORED,
  is_vertical INTEGER GENERATED ALWAYS AS (display_height > display_width) STORED,
  aspect TEXT,
  fps_num INTEGER,
  fps_den INTEGER,
  bit_rate INTEGER,
  bit_depth INTEGER,
  captured_utc TEXT,
  captured_local TEXT,
  filename_stamp TEXT,
  clock_offset_min INTEGER,
  clock_suspect INTEGER NOT NULL DEFAULT 0,
  time_source TEXT CHECK(time_source IN
    ('camera_db','quicktime_creationdate','container','filename','mtime')),
  camera_model TEXT,
  star INTEGER NOT NULL DEFAULT 0,
  highlight INTEGER NOT NULL DEFAULT 0,
  gps_status INTEGER,
  lat REAL,
  lon REAL,
  steady_mode INTEGER,
  fov_type INTEGER,
  app_audio INTEGER,
  shoot_id INTEGER REFERENCES shoot(id) ON DELETE SET NULL,
  thumb_path TEXT,
  probe_version INTEGER NOT NULL DEFAULT 1,
  indexed_at TEXT NOT NULL,
  missing INTEGER NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_clip_loc ON clip(volume_id, rel_path);
CREATE INDEX IF NOT EXISTS ix_clip_quick ON clip(quick_hash);
CREATE INDEX IF NOT EXISTS ix_clip_when ON clip(captured_utc);
CREATE INDEX IF NOT EXISTS ix_clip_shoot ON clip(shoot_id);
CREATE INDEX IF NOT EXISTS ix_clip_inode ON clip(volume_id, inode);
CREATE INDEX IF NOT EXISTS ix_clip_flagged
  ON clip(highlight, star) WHERE role='primary';

CREATE TABLE IF NOT EXISTS episode (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  stage TEXT NOT NULL DEFAULT 'idea'
    CHECK(stage IN ('idea','filming','editing','ready','published')),
  hook TEXT,
  notes TEXT,
  published_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS episode_shoot (
  episode_id INTEGER NOT NULL REFERENCES episode(id) ON DELETE CASCADE,
  shoot_id INTEGER NOT NULL REFERENCES shoot(id) ON DELETE CASCADE,
  PRIMARY KEY (episode_id, shoot_id)
);
"""


ANALYSIS_SCHEMA = """
CREATE TABLE IF NOT EXISTS analysis (
  clip_id       INTEGER PRIMARY KEY REFERENCES clip(id) ON DELETE CASCADE,
  version       INTEGER NOT NULL,
  median_db     REAL,
  dynamics      REAL,
  active_pct    INTEGER,
  bands         TEXT,          -- json [[start,end],...]
  curve         TEXT,          -- json [db,...]
  strip         TEXT,          -- data: URI filmstrip
  analysed_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transcript (
  clip_id    INTEGER NOT NULL REFERENCES clip(id) ON DELETE CASCADE,
  seg        INTEGER NOT NULL,
  start_s    REAL NOT NULL,
  end_s      REAL NOT NULL,
  text       TEXT NOT NULL,
  model      TEXT,
  PRIMARY KEY (clip_id, seg)
);

CREATE TABLE IF NOT EXISTS transcript_state (
  clip_id       INTEGER PRIMARY KEY REFERENCES clip(id) ON DELETE CASCADE,
  model         TEXT NOT NULL,
  segments      INTEGER NOT NULL,
  transcribed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_transcript_clip ON transcript(clip_id);

CREATE TABLE IF NOT EXISTS caption (
  clip_id     INTEGER PRIMARY KEY REFERENCES clip(id) ON DELETE CASCADE,
  text        TEXT NOT NULL,
  keywords    TEXT,            -- json [str]
  source      TEXT NOT NULL,   -- who described it
  written_at  TEXT NOT NULL
);
"""


def _migrate(conn) -> None:
    cols = {r[1] for r in conn.execute("pragma table_info(clip)")}
    if "app_audio" not in cols:
        conn.execute("alter table clip add column app_audio INTEGER")


def connect(path: Path) -> sqlite3.Connection:
    """Open the catalog, applying the schema if absent.

    foreign_keys is per-connection, not persistent, so it is set every time.
    """
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    conn.executescript(ANALYSIS_SCHEMA)
    _migrate(conn)
    conn.commit()
    return conn

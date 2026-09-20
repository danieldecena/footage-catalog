# footcat — footage catalog

Indexes DJI Osmo Action footage from SD cards and external drives into a SQLite
catalog that stays accurate when drives are unplugged.

## Why it exists

Raw footage is unsearchable. This makes it queryable without typing anything in:
every field is derived from the files themselves and from the camera's own index.

## Install

Python 3.10+ and `ffprobe`. No third-party runtime dependencies.

    brew install ffmpeg
    python3 -m pip install --user pytest     # tests only

## Use

Ingest a card (do this BEFORE formatting it):

    python3 -m footcat.cli --archive /Volumes/SSD/Footage --card /Volumes/OsmoAction

Rescan an archive drive:

    python3 -m footcat.cli --archive /Volumes/SSD/Footage --scan /Volumes/SSD/Footage

A run that finds nothing mounted prints nothing and exits 0, so it is safe on a
schedule. It only speaks when something changed.

## ⚠️ Formatting a card destroys its flags

`MISC/AC006.db` on the card holds your in-camera **star** and **highlight** flags
and the only trustworthy capture timestamps. Formatting the card deletes it, and
nothing can reconstruct it. `--card` copies it into `<archive>/_cameradb/` before
scanning anything. **Always ingest before you format.**

## Folder naming

Name a shoot folder `YYYY-MM-DD_location_subject`:

    2026-09-16_skykomish_coho/

Lowercase; hyphens within a token, underscores between tokens. Matching folders
become shoots automatically. Folders that don't match still work — clips are
grouped by time instead, splitting on gaps over 4 hours.

## What it handles that naive tooling gets wrong

**Rotation.** A vertical clip reports its *coded* size, so 1080p vertical looks
like `1920x1080`. Rotation lives in a display matrix, and ffprobe 4.4 emits both
that and a legacy tag with opposite signs. Read wrong, every vertical clip is
misfiled.

**Capture time.** The camera's epoch is when recording *ended*. Capture time is
`epoch - duration`; ignore that and a 13-minute clip is filed 13 minutes late.

**Clock drift.** A camera's clock can change mid-card. Clips recorded on UTC get
`clock_suspect=1` rather than a silently wrong date.

**Proxies.** Each clip has an `.LRF` sibling. Counted once, linked to its primary.

**Offline drives.** Rows are never deleted — a vanished file gets `missing=1`, and
`volume.label` says which drive to go find.

**Big files.** Dedupe uses a bounded hash (head 4 MiB + tail 4 MiB + size), so an
8K rush costs ~8 MiB of reads, not gigabytes.

## Tests

    python3 -m pytest

`tests/test_real_card.py` is skipped unless you point it at a mounted card:

    FOOTCAT_TEST_CARD=/Volumes/OsmoAction python3 -m pytest tests/test_real_card.py

Those assertions encode facts measured from a real card and are the acceptance gate.

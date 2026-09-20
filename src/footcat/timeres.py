"""Timestamp reconciliation — the highest-risk module in the scanner.

Two independent traps, both measured on Daniel's real card:

1. The camera's epoch is when recording ENDED, not started. Clip 0005's epoch
   sits 5m23s after its filename stamp, almost exactly its 5m19s duration.
   So captured_utc = epoch - duration. Skip this and every clip is filed late
   by its own length, up to 13 minutes.

2. The camera clock changed partway through a single card. Clips 0001-0006 ran
   on UTC (offset 0); clips 0018+ on Pacific (offset -420). Clip 0003 reads
   04:23 but was shot at 21:23 the previous day.

The epoch is ground truth. The filename stamp is a hint used only to detect
which clock era a clip came from.
"""
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/Los_Angeles")
EXPECTED_OFFSETS_MIN = (0, -420)
CLEAN_OFFSET_MIN = -420          # camera clock correctly on local time
TOLERANCE_MIN = 2
_STAMP_RE = re.compile(r"_(\d{14})_")


@dataclass
class TimeResolution:
    captured_utc: str | None = None
    captured_local: str | None = None
    filename_stamp: str | None = None
    clock_offset_min: int | None = None
    clock_suspect: int = 0
    time_source: str = "mtime"


def parse_filename_stamp(filename: str) -> datetime | None:
    m = _STAMP_RE.search(filename)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def _render(start_utc: datetime, stamp: datetime | None) -> TimeResolution:
    local = start_utc.astimezone(LOCAL_TZ)
    r = TimeResolution(
        captured_utc=start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        captured_local=local.strftime("%Y-%m-%dT%H:%M:%S"))
    if stamp is not None:
        r.filename_stamp = stamp.strftime("%Y-%m-%dT%H:%M:%S")
        delta = (stamp - start_utc.replace(tzinfo=None)).total_seconds() / 60
        snapped = min(EXPECTED_OFFSETS_MIN, key=lambda e: abs(delta - e))
        r.clock_offset_min = (snapped if abs(delta - snapped) <= TOLERANCE_MIN
                              else int(round(delta)))
        r.clock_suspect = 0 if r.clock_offset_min == CLEAN_OFFSET_MIN else 1
    return r


def resolve(filename: str, epoch: int | None, duration_ms: int | None,
            container_creation: str | None, mtime_ns: int) -> TimeResolution:
    stamp = parse_filename_stamp(filename)

    if epoch is not None:
        end = datetime.fromtimestamp(epoch, tz=timezone.utc)
        start = end - timedelta(milliseconds=duration_ms or 0)
        r = _render(start, stamp)
        r.time_source = "camera_db"
        return r

    if container_creation:
        for fmt, src in (("%Y-%m-%dT%H:%M:%S%z", "quicktime_creationdate"),
                         ("%Y-%m-%dT%H:%M:%S.%f%z", "quicktime_creationdate"),
                         ("%Y-%m-%dT%H:%M:%SZ", "container"),
                         ("%Y-%m-%dT%H:%M:%S.%fZ", "container")):
            try:
                dt = datetime.strptime(container_creation, fmt)
            except ValueError:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            r = _render(dt.astimezone(timezone.utc), stamp)
            r.time_source = src
            return r

    r = _render(datetime.fromtimestamp(mtime_ns / 1e9, tz=timezone.utc), stamp)
    r.time_source = "mtime"
    return r

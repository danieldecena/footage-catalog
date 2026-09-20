"""Bounded content hash for large media files.

Full-hashing multi-GB 8K rushes on every rescan is ruinous, so the dedupe key
reads a fixed ~8 MiB: the head, the tail, and the size.
"""
import hashlib
from pathlib import Path

CHUNK = 4 * 1024 * 1024
DIGEST_BYTES = 16


def quick_hash(path: Path) -> str:
    size = path.stat().st_size
    h = hashlib.blake2b(digest_size=DIGEST_BYTES)
    h.update(str(size).encode())
    with open(path, "rb") as f:
        h.update(f.read(CHUNK))
        if size > CHUNK:
            # max() keeps head and tail from overlapping between 1x and 2x CHUNK
            f.seek(max(CHUNK, size - CHUNK))
            h.update(f.read(CHUNK))
    return h.hexdigest()

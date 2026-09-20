import os
from footcat.hashing import quick_hash, CHUNK


def _write(p, size, fill=b"\x00"):
    with open(p, "wb") as f:
        f.write(fill * (size // len(fill)))
    return p


def test_identical_files_hash_equal(tmp_path):
    a = _write(tmp_path / "a.bin", 1024)
    b = _write(tmp_path / "b.bin", 1024)
    assert quick_hash(a) == quick_hash(b)


def test_size_difference_changes_hash(tmp_path):
    a = _write(tmp_path / "a.bin", 1024)
    b = _write(tmp_path / "b.bin", 2048)
    assert quick_hash(a) != quick_hash(b)


def test_tail_difference_detected_on_large_file(tmp_path):
    size = CHUNK * 3
    a, b = tmp_path / "a.bin", tmp_path / "b.bin"
    for p, last in ((a, b"\x01"), (b, b"\x02")):
        with open(p, "wb") as f:
            f.write(b"\x00" * (size - 1))
            f.write(last)
    assert quick_hash(a) != quick_hash(b)


def test_head_difference_detected_on_large_file(tmp_path):
    size = CHUNK * 3
    a, b = tmp_path / "a.bin", tmp_path / "b.bin"
    for p, first in ((a, b"\x01"), (b, b"\x02")):
        with open(p, "wb") as f:
            f.write(first)
            f.write(b"\x00" * (size - 1))
    assert quick_hash(a) != quick_hash(b)


def test_reads_only_bounded_bytes(tmp_path, monkeypatch):
    p = tmp_path / "big.bin"
    with open(p, "wb") as f:
        f.truncate(CHUNK * 50)
    total = 0
    real_read = os.read

    def counting_read(fd, n):
        nonlocal total
        data = real_read(fd, n)
        total += len(data)
        return data

    monkeypatch.setattr(os, "read", counting_read)
    quick_hash(p)
    assert total <= CHUNK * 2 + 4096


def test_hash_is_32_hex_chars(tmp_path):
    h = quick_hash(_write(tmp_path / "a.bin", 10))
    assert len(h) == 32 and all(c in "0123456789abcdef" for c in h)

"""ZIP-parity test: run Web-LaTeX's safe_zip.unpack() against the shared hostile archives.

This script is run INSIDE the container (via docker exec -i) by the CI smoke test, using the
same archive set that the AppStore backend and Online-IDE also run (.github#13, item 3.3).

Usage (from smoke-test.sh):

    docker exec -i wl python3 - < .github/test-zip-parity.py

The script is intentionally standalone (no package install required): it embeds the same
hostile-archive generator that appstore_upload_utils.hostile_archives exports.
"""

from __future__ import annotations

import io
import os
import shutil
import stat
import struct
import sys
import zipfile
import zlib

# safe_zip is part of the image
sys.path.insert(0, "/opt/weblatex")
from app.safe_zip import Rejected, unpack  # noqa: E402

WORK = "/tmp/zip-parity-test"
failures = []
counter = [0]


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)
        print("FAIL:", message)


# ---------------------------------------------------------------------------
# Hostile archive generator (kept in sync with appstore_upload_utils.hostile_archives)
# ---------------------------------------------------------------------------

def _make_zip(entries: dict, compress: int = zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, value in entries.items():
            content, mode = value if isinstance(value, tuple) else (value, 0o100644)
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = mode << 16
            info.compress_type = compress
            z.writestr(info, content)
    return buf.getvalue()


def _hostile_archives() -> list[tuple[str, bytes]]:
    cases: list[tuple[str, bytes]] = []

    def add(label: str, data: bytes) -> None:
        cases.append((label, data))

    good = _make_zip({"ok.txt": b"hello"})

    for name, label in [
        ("../../escape.txt", "zip-slip"),
        ("a/../../escape.txt", "zip-slip nested"),
        ("/tmp/absolute.txt", "absolute path"),
        ("C:/drive.txt", "drive letter"),
        ("back\\slash.txt", "backslash"),
        ("ctrl\x07char.txt", "control character"),
        ("./dot.txt", "dot component"),
        ("a//b.txt", "empty path component"),
        ("d/" * 40 + "deep.txt", "path too deeply nested"),
        ("x" * 300, "entry name too long"),
    ]:
        add(label, _make_zip({"ok.txt": b"fine", name: b"x"}))

    for mode, label in [
        (stat.S_IFLNK | 0o777, "symlink"),
        (stat.S_IFCHR | 0o666, "character device"),
        (stat.S_IFBLK | 0o660, "block device"),
        (stat.S_IFIFO | 0o644, "fifo"),
    ]:
        add(label, _make_zip({"ok.txt": b"fine", "bad": (b"/etc/passwd", mode)}))

    add("symlink then file through it",
        _make_zip({"lnk": (b"/tmp", stat.S_IFLNK | 0o777), "lnk/through.txt": b"x"}))

    encrypted = bytearray(_make_zip({"secret.txt": b"x" * 20}))
    struct.pack_into("<H", encrypted, encrypted.rindex(b"PK\x01\x02") + 8, 0x1)
    add("encrypted entry", bytes(encrypted))

    add("bzip2 compression", _make_zip({"a.txt": b"x" * 200}, compress=zipfile.ZIP_BZIP2))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.txt", b"1")
        z.writestr("A.TXT", b"2")
    add("duplicate names (case)", buf.getvalue())

    add("empty archive", _make_zip({}))
    add("not a zip", b"MZ this is not a zip file at all" * 5)
    add("truncated zip", good[: len(good) // 2])
    add("too many entries", _make_zip({f"f{i}.txt": b"" for i in range(2001)}))

    bomb = _make_zip({"big.bin": b"\x00" * (100 * 1024 * 1024)})
    add("decompression bomb (single entry)", bomb)
    many = _make_zip({f"p{i}.bin": b"\x00" * (8 * 1024 * 1024) for i in range(10)})
    add("decompression bomb (many medium entries)", many)

    lying = bytearray(_make_zip({"a.txt": b"hello world" * 100}, compress=zipfile.ZIP_STORED))
    struct.pack_into("<I", lying, lying.rindex(b"PK\x01\x02") + 24, 5)
    add("header lies about uncompressed size", bytes(lying))

    corrupt = bytearray(_make_zip({"a.txt": b"hello world" * 100}, compress=zipfile.ZIP_STORED))
    corrupt[40] ^= 0xFF
    add("corrupt content (CRC mismatch)", bytes(corrupt))

    payload = b"A" * 100_000
    local = (
        struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0, 0, 0, 0x21,
                    zlib.crc32(payload), len(payload), len(payload), 1, 0)
        + b"a" + payload
    )
    central = b"".join(
        struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, 0, 0, 0, 0x21,
                    zlib.crc32(payload), len(payload), len(payload), 1, 0, 0, 0, 0, 0, 0)
        + bytes([ord("a") + i])
        for i in range(5)
    )
    end = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, 5, 5, len(central), len(local), 0)
    add("overlapping entries", local + central + end)

    add("single file too large",
        _make_zip({"big.bin": os.urandom(2 * 1024 * 1024 + 1)}, compress=zipfile.ZIP_STORED))

    return cases


# ---------------------------------------------------------------------------
# Run each hostile archive through safe_zip.unpack()
# ---------------------------------------------------------------------------

os.makedirs(WORK, exist_ok=True)

for label, archive_bytes in _hostile_archives():
    counter[0] += 1
    base = f"{WORK}/case{counter[0]}"
    os.makedirs(base)
    zip_path = f"{base}/a.zip"
    with open(zip_path, "wb") as fh:
        fh.write(archive_bytes)
    dest = f"{base}/out"

    rejected = False
    try:
        unpack(zip_path, dest)
    except (Rejected, Exception):
        rejected = True

    written: list[str] = []
    if os.path.exists(dest):
        for root, dirs, files in os.walk(dest):
            written += [os.path.relpath(os.path.join(root, f), dest) for f in files + dirs]

    check(rejected, f"{label}: safe_zip accepted the archive (expected Rejected)")
    check(written == [], f"{label}: files were written despite rejection: {written}")
    if rejected and not written:
        print(f"OK: {label}")

shutil.rmtree(WORK, ignore_errors=True)

if failures:
    print(f"\n{len(failures)} parity test(s) FAILED")
    sys.exit(1)
print("\nzip parity tests: all passed")

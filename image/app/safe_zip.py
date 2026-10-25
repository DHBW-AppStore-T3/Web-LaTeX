"""Unpack a ZIP (the team's starter project) completely or not at all.

The rules are the backend's (``app/services/upload_validation.py`` in the backend repository) and the
Online-IDE's (``image/unpack-assignments.py``), kept in step by hand; the platform checks the upload
too, and this module does not rely on that.

* the whole archive is inspected before anything is written: at most MAX_ENTRIES entries,
  MAX_ENTRY_BYTES per entry and MAX_TOTAL_BYTES in total, counted on the bytes that really come out of
  the decompressor (header sizes are not believed); every CRC is verified
* one bad entry rejects the archive: absolute paths, "..", "." or empty components, backslashes, control
  characters, over-long or too deeply nested paths, duplicate names (also by case), symbolic links and
  device files, encrypted entries, compression other than stored/deflate, overlapping entries
* only regular files (0644) and directories are written, into a staging directory next to the
  destination; a complete result is moved into place and existing files are never overwritten
* macOS metadata (__MACOSX/, .DS_Store, ._*) is left out
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import zipfile

MAX_ZIP_BYTES = 2 * 1024 * 1024
MAX_ENTRIES = 2000
MAX_ENTRY_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_PATH_LENGTH = 1024
MAX_COMPONENT_LENGTH = 255
MAX_DEPTH = 32
CHUNK = 64 * 1024


class Rejected(Exception):
    """The archive is not acceptable; the message says why."""


def _check_name(name: str) -> None:
    if not name or len(name) > MAX_PATH_LENGTH:
        raise Rejected("an entry has an empty or too long path")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in name):
        raise Rejected("an entry path contains control characters")
    if "\\" in name:
        raise Rejected("an entry path contains a backslash")
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise Rejected("an entry has an absolute path")
    parts = name.rstrip("/").split("/")
    if len(parts) > MAX_DEPTH:
        raise Rejected("an entry path is nested too deeply")
    for part in parts:
        if part in ("", ".", ".."):
            raise Rejected("an entry path contains '.', '..' or an empty component")
        if len(part) > MAX_COMPONENT_LENGTH:
            raise Rejected("an entry path component is too long")


def _is_mac_metadata(name: str) -> bool:
    parts = name.rstrip("/").split("/")
    return parts[0] == "__MACOSX" or parts[-1] == ".DS_Store" or parts[-1].startswith("._")


def _inspect(archive: zipfile.ZipFile, length: int) -> list[zipfile.ZipInfo]:
    infos = archive.infolist()
    if not infos:
        raise Rejected("the archive is empty")
    if len(infos) > MAX_ENTRIES:
        raise Rejected(f"more than {MAX_ENTRIES} entries")
    seen: set[str] = set()
    compressed = 0
    for info in infos:
        _check_name(info.filename)
        folded = info.filename.rstrip("/").casefold()
        if folded in seen:
            raise Rejected("two entries have the same path")
        seen.add(folded)
        if info.flag_bits & 0x1:
            raise Rejected("the archive has encrypted entries")
        if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise Rejected("the archive uses an unsupported compression method")
        mode = info.external_attr >> 16 if info.create_system == 3 else 0
        if mode and (stat.S_ISLNK(mode) or stat.S_ISCHR(mode) or stat.S_ISBLK(mode) or stat.S_ISFIFO(mode) or stat.S_ISSOCK(mode)):
            raise Rejected("the archive contains a symbolic link or a device file")
        if info.is_dir() and info.file_size:
            raise Rejected("a directory entry has content")
        if info.file_size > MAX_ENTRY_BYTES:
            raise Rejected("an entry is larger than the limit")
        compressed += info.compress_size
    if compressed > length:
        raise Rejected("the archive's entries overlap")
    return [i for i in infos if not _is_mac_metadata(i.filename)]


def _write(archive: zipfile.ZipFile, entries: list[zipfile.ZipInfo], staging: str) -> None:
    total = 0
    for info in entries:
        target = os.path.join(staging, *info.filename.rstrip("/").split("/"))
        if info.is_dir():
            os.makedirs(target, mode=0o755, exist_ok=True)
            continue
        os.makedirs(os.path.dirname(target), mode=0o755, exist_ok=True)
        written = 0
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
        with os.fdopen(fd, "wb") as out, archive.open(info) as source:
            while True:
                chunk = source.read(CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                total += len(chunk)
                if written > MAX_ENTRY_BYTES or total > MAX_TOTAL_BYTES:
                    raise Rejected("the archive unpacks to more than the limit")
                out.write(chunk)
        if written != info.file_size:
            raise Rejected("an entry's real size differs from its header")


def _verify_inside(staging: str) -> None:
    root = os.path.realpath(staging)
    for current, dirs, files in os.walk(staging):
        for name in dirs + files:
            path = os.path.join(current, name)
            if os.path.islink(path) or os.path.commonpath([root, os.path.realpath(path)]) != root:
                raise Rejected("an unpacked entry is a link or leaves the target directory")


def _move_into_place(staging: str, destination: str) -> None:
    for current, _dirs, files in os.walk(staging):
        relative = os.path.relpath(current, staging)
        target_dir = destination if relative == "." else os.path.join(destination, relative)
        os.makedirs(target_dir, mode=0o755, exist_ok=True)
        for name in files:
            target = os.path.join(target_dir, name)
            if not os.path.lexists(target):
                os.replace(os.path.join(current, name), target)


def unpack(zip_path: str, destination: str) -> None:
    """Unpack ``zip_path`` into ``destination`` (which may exist). Raises :class:`Rejected` or ``OSError``."""
    destination = destination.rstrip("/")
    staging = destination + ".unpacking"
    shutil.rmtree(staging, ignore_errors=True)
    try:
        if os.path.getsize(zip_path) > MAX_ZIP_BYTES:
            raise Rejected("the archive file is larger than the limit")
        try:
            archive = zipfile.ZipFile(zip_path)
        except (zipfile.BadZipFile, OSError, ValueError):
            raise Rejected("not a readable ZIP archive") from None
        with archive:
            entries = _inspect(archive, os.path.getsize(zip_path))
            os.makedirs(staging, mode=0o700)
            try:
                _write(archive, entries, staging)
            except (zipfile.BadZipFile, NotImplementedError, RuntimeError, EOFError, ValueError) as exc:
                raise Rejected(f"an entry cannot be read ({exc.__class__.__name__})") from None
        _verify_inside(staging)
        os.makedirs(destination, mode=0o755, exist_ok=True)
        _move_into_place(staging, destination)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

"""Structure checks for uploaded images (PNG, JPEG, GIF), the same rules as the backend's
``app/services/upload_formats.py``: the container is walked (PNG: every chunk and its CRC), the pixel
count is limited (LaTeX would try to hold a 40000 x 40000 image announced by a tiny file), and data
appended after the end of a PNG or GIF (a polyglot with an archive) is refused.
"""

from __future__ import annotations

import struct
import zlib

MAX_PIXELS = 100_000_000


class Rejected(ValueError):
    pass


def _pixels(width: int, height: int) -> None:
    if width < 1 or height < 1:
        raise Rejected("the image has no size")
    if width * height > MAX_PIXELS:
        raise Rejected("the image has more than 100 million pixels")


def _png(data: bytes) -> None:
    position = 8
    first = True
    while True:
        if position + 12 > len(data):
            raise Rejected("the PNG is truncated")
        length, kind = struct.unpack(">I4s", data[position : position + 8])
        end = position + 8 + length + 4
        if end > len(data):
            raise Rejected("the PNG is truncated")
        body = data[position + 8 : position + 8 + length]
        if zlib.crc32(kind + body) != struct.unpack(">I", data[end - 4 : end])[0]:
            raise Rejected("a PNG chunk is damaged")
        if first:
            if kind != b"IHDR" or length != 13:
                raise Rejected("the PNG has no header chunk")
            _pixels(*struct.unpack(">II", body[:8]))
            first = False
        if kind == b"IEND":
            if end != len(data):
                raise Rejected("there is data after the end of the PNG")
            return
        position = end


def _jpeg(data: bytes) -> None:
    position = 2
    size = None
    while position + 4 <= len(data):
        if data[position] != 0xFF:
            raise Rejected("the JPEG has a broken segment")
        marker = data[position + 1]
        if marker == 0xFF:
            position += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            position += 2
            continue
        if marker == 0xD9:
            break
        (length,) = struct.unpack(">H", data[position + 2 : position + 4])
        if length < 2 or position + 2 + length > len(data):
            raise Rejected("the JPEG is truncated")
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if length < 8:
                raise Rejected("the JPEG frame header is too short")
            height, width = struct.unpack(">HH", data[position + 5 : position + 9])
            size = (width, height)
        if marker == 0xDA:
            break
        position += 2 + length
    if size is None:
        raise Rejected("the JPEG has no frame header")
    _pixels(*size)
    if b"\xff\xd9" not in data[-4096:]:
        raise Rejected("the JPEG has no end marker")


def _gif(data: bytes) -> None:
    if len(data) < 14:
        raise Rejected("the GIF is truncated")
    _pixels(*struct.unpack("<HH", data[6:10]))
    if data[-1:] != b"\x3b":
        raise Rejected("the GIF does not end with its trailer")


def inspect(data: bytes, extension: str) -> None:
    """Raise :class:`Rejected` unless ``data`` is a sound image of the type the extension says."""
    kinds = {
        ".png": (b"\x89PNG\r\n\x1a\n", _png),
        ".jpg": (b"\xff\xd8\xff", _jpeg),
        ".jpeg": (b"\xff\xd8\xff", _jpeg),
        ".gif": (b"GIF8", _gif),
    }
    if extension not in kinds:
        raise Rejected("this image type is not allowed")
    magic, check = kinds[extension]
    if not data.startswith(magic):
        raise Rejected("the content does not match the file extension")
    check(data)

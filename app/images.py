"""Image files Tagwerk keeps in /config/images: uploaded covers and the covers saved for undo.

Images are stored under the SHA-256 of their content, so a cover shared by a whole album is
stored once. Only JPEG and PNG are accepted: every player and DJ program can show them.
"""

import hashlib
import re
import struct
from pathlib import Path

MAX_SIZE = 10 * 1024 * 1024  # bytes per uploaded image
_ID = re.compile(r"[0-9a-f]{64}")


class ImageError(ValueError):
    """Not an image Tagwerk can embed."""


def image_info(data: bytes) -> tuple[str, int, int]:
    """(MIME type, width, height) of a JPEG or PNG. Width/height are 0 if not found."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        width, height = struct.unpack(">II", data[16:24]) if len(data) >= 24 else (0, 0)
        return "image/png", width, height
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg", *_jpeg_size(data)
    raise ImageError("Only JPEG and PNG images can be used as cover art")


def _jpeg_size(data: bytes) -> tuple[int, int]:
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            return 0, 0
        marker = data[i + 1]
        length = struct.unpack(">H", data[i + 2 : i + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):  # start of frame
            height, width = struct.unpack(">HH", data[i + 5 : i + 9])
            return width, height
        i += 2 + length
    return 0, 0


class ImageStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def put(self, data: bytes) -> str:
        """Store image bytes; returns their id (SHA-256 hex)."""
        image_id = hashlib.sha256(data).hexdigest()
        path = self.directory / image_id
        if not path.exists():
            self.directory.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        return image_id

    def get(self, image_id: str) -> bytes:
        return self.path(image_id).read_bytes()

    def path(self, image_id: str) -> Path:
        if not _ID.fullmatch(image_id):
            raise KeyError(image_id)
        return self.directory / image_id

    def exists(self, image_id: str) -> bool:
        try:
            return self.path(image_id).is_file()
        except KeyError:
            return False

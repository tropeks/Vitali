"""Tiny shared helper: sha256 of a file's bytes, streamed (no full read into memory).

Used by ``apps.core.cold_storage`` to checksum the plaintext export before
encryption and to verify the decrypted round trip and the stored artifact —
see that module for why each of those checks exists.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

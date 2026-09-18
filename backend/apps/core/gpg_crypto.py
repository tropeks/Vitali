"""Symmetric GPG encrypt/decrypt, matching scripts/backup.sh's invocation.

Order 020 (Capitão's amendment) requires the audit-log cold export to reuse
the SAME encryption mechanism and key as the project's existing backup path
(``scripts/backup.sh`` / ``scripts/restore_test.sh``) rather than invent a new
scheme or new key management. This module is deliberately a thin wrapper
around the ``gpg`` CLI with the exact same flags backup.sh uses, so an
artifact produced here is decryptable by the exact same command an operator
would already run by hand.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


class GpgError(Exception):
    """Raised when the ``gpg`` subprocess exits non-zero."""


def encrypt_file(
    plaintext_path: Path, out_path: Path, *, passphrase: str, gnupg_home: Path
) -> None:
    _run(
        [
            "gpg",
            "--batch",
            "--yes",
            "--quiet",
            "--passphrase",
            passphrase,
            "--cipher-algo",
            "AES256",
            "--symmetric",
            "--output",
            str(out_path),
            str(plaintext_path),
        ],
        step="encryption",
        gnupg_home=gnupg_home,
    )


def decrypt_file(
    ciphertext_path: Path, out_path: Path, *, passphrase: str, gnupg_home: Path
) -> None:
    _run(
        [
            "gpg",
            "--batch",
            "--yes",
            "--quiet",
            "--passphrase",
            passphrase,
            "--output",
            str(out_path),
            "--decrypt",
            str(ciphertext_path),
        ],
        step="decryption",
        gnupg_home=gnupg_home,
    )


def _run(args: list[str], *, step: str, gnupg_home: Path) -> None:
    # --homedir: an ephemeral, per-export keyring directory. Purely symmetric
    # (passphrase-based) encryption needs no persistent keyring, and the
    # runtime user (appuser, no HOME — see backend/Dockerfile) has nowhere
    # gpg could otherwise default to writing one.
    gnupg_home.mkdir(parents=True, exist_ok=True, mode=0o700)
    args = [args[0], "--homedir", str(gnupg_home), *args[1:]]
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise GpgError(f"gpg {step} failed (exit {result.returncode}): {result.stderr.strip()}")

"""
ICP-Brasil digital signature primitive.

Implements the cryptographic core required by MP 2.200-2/2001 (Medida
Provisória que institui a ICP-Brasil) and CFM Res. 2.299/2021 (paperless
clinical records):

- Load an ICP-Brasil A1 certificate from a PKCS#12 (.pfx/.p12) bundle.
- Compute a SHA-256 hash of the document content.
- Sign the content with RSA-PKCS#1 v1.5 + SHA-256 — the algorithm pair the
  ICP-Brasil DOC-ICP-15.03 profile mandates for "AD-RB" (Assinatura Digital
  com Referência Básica).
- Verify a previously produced signature against a certificate.

The service intentionally stays at the cryptographic primitive layer. It does
NOT validate the full ICP-Brasil chain of trust (AC Raiz Brasileira →
intermediate AC → end-entity cert) — that requires shipping the ICP-Brasil
trust store, which is out of scope for the primitive. Callers that need full
chain validation should layer it on top.

A3 hardware tokens (PKCS#11) are out of scope here; the primitive expects an
A1 PKCS#12 bundle which is what software signing flows use today.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509 import Certificate


class ICPBrasilSignerError(Exception):
    """Raised when the signing primitive cannot complete (bad cert, no key, etc.)."""


@dataclass(frozen=True)
class SignatureResult:
    """Result of `ICPBrasilSigner.sign` — every field is needed downstream by the storage layer."""

    signature: bytes
    document_hash_hex: str
    cert_subject: str
    cert_issuer: str
    cert_serial_hex: str
    cert_not_valid_before: datetime
    cert_not_valid_after: datetime
    is_icp_brasil: bool
    algorithm: str = "SHA256withRSA"


class ICPBrasilSigner:
    """Stateless ICP-Brasil signing primitive. All entry points are classmethods."""

    @staticmethod
    def load_pkcs12(pfx_bytes: bytes, password: str | None) -> tuple[Any, Certificate]:
        """
        Parse a PKCS#12 bundle. Returns (private_key, certificate).

        Raises ICPBrasilSignerError if the bundle is malformed, password is
        wrong, or the bundle does not contain both a key and a cert.
        """
        password_bytes = password.encode("utf-8") if password else None
        try:
            private_key, cert, _additional = pkcs12.load_key_and_certificates(
                pfx_bytes, password_bytes
            )
        except ValueError as exc:
            raise ICPBrasilSignerError(f"Could not parse PKCS#12 bundle: {exc}") from exc
        if private_key is None:
            raise ICPBrasilSignerError("PKCS#12 bundle contains no private key.")
        if cert is None:
            raise ICPBrasilSignerError("PKCS#12 bundle contains no certificate.")
        return private_key, cert

    @staticmethod
    def compute_hash(document: bytes) -> bytes:
        digest = hashes.Hash(hashes.SHA256())
        digest.update(document)
        return digest.finalize()

    @classmethod
    def sign(cls, document: bytes, pfx_bytes: bytes, password: str | None) -> SignatureResult:
        """
        Sign `document` with the key bundled in `pfx_bytes`. Returns the raw
        signature + every field the storage layer needs to materialise a
        `DigitalSignature` row.
        """
        private_key, cert = cls.load_pkcs12(pfx_bytes, password)
        if not isinstance(private_key, rsa.RSAPrivateKey):
            raise ICPBrasilSignerError(
                "ICP-Brasil AD-RB signing requires an RSA key; the bundled key "
                f"is {type(private_key).__name__}."
            )

        doc_hash = cls.compute_hash(document)
        signature = private_key.sign(document, padding.PKCS1v15(), hashes.SHA256())

        return SignatureResult(
            signature=signature,
            document_hash_hex=doc_hash.hex(),
            cert_subject=cert.subject.rfc4514_string(),
            cert_issuer=cert.issuer.rfc4514_string(),
            cert_serial_hex=format(cert.serial_number, "X"),
            cert_not_valid_before=_cert_valid_from(cert),
            cert_not_valid_after=_cert_valid_until(cert),
            is_icp_brasil=cls.is_icp_brasil(cert),
        )

    @staticmethod
    def verify(document: bytes, signature: bytes, cert: Certificate) -> bool:
        """
        Verify that `signature` is a valid RSA-PKCS#1 v1.5 + SHA-256 signature
        over `document` produced by the private key matching `cert.public_key()`.
        Returns True / False; does not raise on a non-match.
        """
        public_key = cert.public_key()
        if not isinstance(public_key, rsa.RSAPublicKey):
            return False
        try:
            public_key.verify(signature, document, padding.PKCS1v15(), hashes.SHA256())
        except InvalidSignature:
            return False
        return True

    @staticmethod
    def is_icp_brasil(cert: Certificate) -> bool:
        """
        Heuristic — the cert's issuer chain mentions an ICP-Brasil AC. A real
        chain-of-trust check requires the ICP-Brasil trust store (DOC-ICP-04)
        and is layered on top of this primitive.
        """
        issuer = cert.issuer.rfc4514_string()
        markers = ("ICP-Brasil", "AC Raiz Brasileira", "ICPBrasil")
        return any(marker in issuer for marker in markers)


def _cert_valid_from(cert: Certificate) -> datetime:
    # `cryptography` ≥ 42 deprecated the naive attributes in favour of UTC.
    return cast(datetime, getattr(cert, "not_valid_before_utc", cert.not_valid_before))


def _cert_valid_until(cert: Certificate) -> datetime:
    return cast(datetime, getattr(cert, "not_valid_after_utc", cert.not_valid_after))

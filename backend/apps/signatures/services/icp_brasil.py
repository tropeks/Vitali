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

In addition to the cryptographic primitive, the sign flow now performs real
ICP-Brasil chain-of-trust validation via `ICPBrasilChainValidator`
(`services/chain.py`): it builds a path from the end-entity certificate up to a
configured ICP-Brasil anchor (AC Raiz Brasileira → intermediate AC →
end-entity), checks the leaf validity window, enforces CA / KeyUsage
constraints, and extracts the ICP-Brasil policy OIDs (arc 2.16.76.1). The result
of THAT validation — not the old issuer-DN string heuristic — is what sets
`SignatureResult.is_icp_brasil`.

Revocation (CRL / OCSP) is the explicit PR2 follow-up and is NOT checked here.
The trust store is shipped/refreshed out-of-band (`refresh_icp_truststore`);
when it is empty, validation degrades gracefully (see `views.py` and
`docs/ICP_BRASIL.md`).

A3 hardware tokens (PKCS#11) are out of scope here; the primitive expects an
A1 PKCS#12 bundle which is what software signing flows use today.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509 import Certificate
from django.conf import settings

from .chain import ICPBrasilChainValidator

logger = logging.getLogger(__name__)


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
    # ICP-Brasil certificate policy OIDs (arc 2.16.76.1) found on the leaf.
    policy_oids: list[str] = field(default_factory=list)
    # Human-readable outcome of chain validation (for logging / 400 detail).
    chain_reason: str = ""
    # True when the trust store has no anchors → chain validation was skipped.
    chain_truststore_empty: bool = False


class ICPBrasilSigner:
    """Stateless ICP-Brasil signing primitive. All entry points are classmethods."""

    @staticmethod
    def load_pkcs12(
        pfx_bytes: bytes, password: str | None
    ) -> tuple[Any, Certificate, list[Certificate]]:
        """
        Parse a PKCS#12 bundle. Returns (private_key, certificate, additional_certs).

        `additional_certs` are any intermediate CA certificates bundled alongside
        the end-entity cert — used as path-building hints for chain validation.

        Raises ICPBrasilSignerError if the bundle is malformed, password is
        wrong, or the bundle does not contain both a key and a cert.
        """
        password_bytes = password.encode("utf-8") if password else None
        try:
            private_key, cert, additional = pkcs12.load_key_and_certificates(
                pfx_bytes, password_bytes
            )
        except ValueError as exc:
            raise ICPBrasilSignerError(f"Could not parse PKCS#12 bundle: {exc}") from exc
        if private_key is None:
            raise ICPBrasilSignerError("PKCS#12 bundle contains no private key.")
        if cert is None:
            raise ICPBrasilSignerError("PKCS#12 bundle contains no certificate.")
        return private_key, cert, list(additional or [])

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
        private_key, cert, additional = cls.load_pkcs12(pfx_bytes, password)
        if not isinstance(private_key, rsa.RSAPrivateKey):
            raise ICPBrasilSignerError(
                "ICP-Brasil AD-RB signing requires an RSA key; the bundled key "
                f"is {type(private_key).__name__}."
            )

        # Real chain-of-trust validation — replaces the old issuer-DN heuristic
        # as the source of truth for `is_icp_brasil`.
        chain = ICPBrasilChainValidator().validate(cert, extra_intermediates=additional)

        if chain.is_truststore_empty:
            # Cannot validate without anchors — degrade gracefully (do NOT block),
            # but make the operational gap loud so the store gets populated.
            logger.warning(
                "ICP-Brasil chain validation DISABLED: %s. Signature recorded as "
                "non-ICP-Brasil. Populate the store with `manage.py refresh_icp_truststore`.",
                chain.reason,
            )
        elif getattr(settings, "ICP_BRASIL_ENFORCE_CHAIN", True) and not chain.trusted:
            # Populated store + enforcement on + untrusted cert → reject.
            logger.warning("ICP-Brasil chain validation FAILED: %s", chain.reason)
            raise ICPBrasilSignerError(chain.reason)

        if chain.policy_oids:
            logger.info("ICP-Brasil policy OIDs on signing cert: %s", ", ".join(chain.policy_oids))

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
            is_icp_brasil=chain.trusted,
            policy_oids=list(chain.policy_oids),
            chain_reason=chain.reason,
            chain_truststore_empty=chain.is_truststore_empty,
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
    def _issuer_mentions_icp_brasil(cert: Certificate) -> bool:
        """
        DEPRECATED heuristic — the cert's issuer DN merely *mentions* an
        ICP-Brasil AC. This is spoofable and is NO LONGER the source of truth
        for `is_icp_brasil` (that now comes from `ICPBrasilChainValidator`).
        Retained only for diagnostics / logging.
        """
        issuer = cert.issuer.rfc4514_string()
        markers = ("ICP-Brasil", "AC Raiz Brasileira", "ICPBrasil")
        return any(marker in issuer for marker in markers)


def _cert_valid_from(cert: Certificate) -> datetime:
    # `cryptography` ≥ 42 deprecated the naive attributes in favour of UTC.
    return cast(datetime, getattr(cert, "not_valid_before_utc", cert.not_valid_before))


def _cert_valid_until(cert: Certificate) -> datetime:
    return cast(datetime, getattr(cert, "not_valid_after_utc", cert.not_valid_after))

"""
ICP-Brasil certificate chain-of-trust validation.

This delegates path validation to **`pyhanko-certvalidator`**, a vetted
RFC 5280 path-validation implementation, instead of the hand-rolled path
builder that previously lived here. A cross-model adversarial review (Gemini)
found that the hand-rolled validator skipped several RFC 5280 obligations that a
real validator enforces; using `pyhanko-certvalidator` closes that gap.

What is validated here (PR1) — all performed offline (`allow_fetching=False`):

- **Full path validation (RFC 5280)** — from the leaf up to a configured
  ICP-Brasil trust anchor. This enforces, for *every* certificate in the path:
  the validity window (leaf AND intermediates AND anchor), BasicConstraints
  (CA=True on CAs, `pathLenConstraint`), `keyCertSign` KeyUsage on CA certs,
  NameConstraints, and rejection of weak signature algorithms.
- **Leaf key usage** — the leaf must assert `digital_signature` or
  `non_repudiation` (content_commitment), the usages an ICP-Brasil signing
  certificate requires. Enforced via `validate_usage`.
- **Policy OIDs** — OIDs under the ICP-Brasil `2.16.76.1` arc are extracted from
  the leaf's CertificatePolicies extension for audit/logging. This is
  independent of the library's path check.

What is NOT validated here (explicit follow-up, PR2): revocation status via
CRL / OCSP. In PR1 the `ValidationContext` is built with
`allow_fetching=False` and `revocation_mode='soft-fail'` so no network calls are
made. PR2 enables revocation by flipping `allow_fetching=True` and
`revocation_mode='require'`.

The trust store is shipped/refreshed out-of-band (see the
`refresh_icp_truststore` management command); when it is empty the validator
reports `is_truststore_empty=True` and `trusted=False` WITHOUT raising, so the
signing flow can degrade gracefully instead of breaking.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import cast

from asn1crypto import x509 as asn1_x509
from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509 import Certificate, ExtensionNotFound
from cryptography.x509.oid import ExtensionOID
from django.conf import settings
from pyhanko_certvalidator import CertificateValidator, ValidationContext
from pyhanko_certvalidator.errors import (
    InvalidCertificateError,
    PathBuildingError,
    PathValidationError,
    RevokedError,
)

logger = logging.getLogger(__name__)

# Root OID arc allocated to ICP-Brasil certificate policies (ITI DOC-ICP-04).
ICP_BRASIL_POLICY_ARC = "2.16.76.1"

# Leaf key usages an ICP-Brasil signing certificate must assert. pyhanko names
# the non-repudiation bit `non_repudiation` (a.k.a. content_commitment).
REQUIRED_LEAF_KEY_USAGE = frozenset({"digital_signature", "non_repudiation"})


@dataclass(frozen=True)
class ChainValidationResult:
    """Outcome of `ICPBrasilChainValidator.validate`."""

    trusted: bool
    reason: str
    chain_subjects: list[str] = field(default_factory=list)
    policy_oids: list[str] = field(default_factory=list)
    is_truststore_empty: bool = False


def _load_anchors(truststore_dir: str) -> tuple[Certificate, ...]:
    """
    Parse every ``*.pem`` / ``*.crt`` file under ``truststore_dir`` into trusted
    CA certificates. Each file may be PEM or DER, and a PEM file may bundle
    multiple certificates. Unreadable / unparseable files are logged and skipped
    so one bad file does not disable the whole trust store.
    """
    anchors: list[Certificate] = []
    base = Path(truststore_dir)
    if not base.is_dir():
        return ()

    for path in sorted(base.iterdir()):
        if path.suffix.lower() not in (".pem", ".crt"):
            continue
        try:
            raw = path.read_bytes()
        except OSError as exc:
            logger.warning("Could not read trust anchor %s: %s", path, exc)
            continue
        anchors.extend(_parse_certs(raw, path))

    return tuple(anchors)


def _parse_certs(raw: bytes, path: Path) -> list[Certificate]:
    """Parse a blob as a PEM bundle first, then fall back to single DER."""
    certs: list[Certificate] = []
    try:
        certs = x509.load_pem_x509_certificates(raw)
    except ValueError:
        certs = []
    if certs:
        return certs
    try:
        return [x509.load_der_x509_certificate(raw)]
    except ValueError as exc:
        logger.warning("Trust anchor %s is neither valid PEM nor DER: %s", path, exc)
        return []


@lru_cache(maxsize=8)
def _cached_anchors(truststore_dir: str) -> tuple[Certificate, ...]:
    return _load_anchors(truststore_dir)


def _to_asn1(cert: Certificate) -> asn1_x509.Certificate:
    """Convert a `cryptography` certificate to an `asn1crypto` one via DER."""
    return asn1_x509.Certificate.load(cert.public_bytes(Encoding.DER))


class ICPBrasilChainValidator:
    """
    Validates a trust path from an end-entity certificate up to a configured
    ICP-Brasil anchor using `pyhanko-certvalidator` (RFC 5280). Stateless apart
    from the cached anchor set.
    """

    def __init__(self, truststore_dir: str | None = None) -> None:
        self._truststore_dir = str(
            truststore_dir if truststore_dir is not None else settings.ICP_BRASIL_TRUSTSTORE_DIR
        )

    @property
    def anchors(self) -> tuple[Certificate, ...]:
        return _cached_anchors(self._truststore_dir)

    @staticmethod
    def clear_cache() -> None:
        """Drop the parsed-anchor cache (after refreshing the trust store)."""
        _cached_anchors.cache_clear()

    def validate(
        self,
        leaf_cert: Certificate,
        extra_intermediates: list[Certificate] | None = None,
        at_time: datetime | None = None,
    ) -> ChainValidationResult:
        anchors = self.anchors
        if not anchors:
            return ChainValidationResult(
                trusted=False,
                reason="trust store not populated",
                is_truststore_empty=True,
            )

        when = at_time or datetime.now(UTC)
        # Policy OIDs are extracted independently of the path check (they're for
        # audit/logging) so they're available even on a validation failure.
        policy_oids = self._extract_policy_oids(leaf_cert)

        try:
            trust_roots = [_to_asn1(a) for a in anchors]
            intermediates = [_to_asn1(c) for c in (extra_intermediates or [])]
            end_entity = _to_asn1(leaf_cert)
        except ValueError as exc:
            return ChainValidationResult(
                trusted=False,
                reason=f"could not parse certificate: {exc}",
                policy_oids=policy_oids,
            )

        # PR1: no network, no revocation. PR2 flips these to
        # allow_fetching=True + revocation_mode='require'.
        ctx = ValidationContext(
            trust_roots=trust_roots,
            moment=when,
            allow_fetching=False,
            revocation_mode="soft-fail",
        )
        validator = CertificateValidator(
            end_entity_cert=end_entity,
            intermediate_certs=intermediates,
            validation_context=ctx,
        )

        try:
            # Full RFC 5280 path validation (validity of EVERY cert, pathlen,
            # basic constraints, CA keyCertSign, name constraints, algorithm
            # policy) AND the leaf key-usage check.
            path = asyncio.run(validator.async_validate_usage(set(REQUIRED_LEAF_KEY_USAGE)))
        except (
            PathValidationError,
            PathBuildingError,
            InvalidCertificateError,
            RevokedError,
            ValueError,
        ) as exc:
            return ChainValidationResult(
                trusted=False,
                reason=str(exc).strip(),
                policy_oids=policy_oids,
            )

        chain_subjects = [c.subject.human_friendly for c in path]
        return ChainValidationResult(
            trusted=True,
            reason="chain validates to a trusted ICP-Brasil anchor (RFC 5280, pyhanko-certvalidator)",
            chain_subjects=chain_subjects,
            policy_oids=policy_oids,
        )

    # ─── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_policy_oids(cert: Certificate) -> list[str]:
        try:
            ext = cert.extensions.get_extension_for_oid(ExtensionOID.CERTIFICATE_POLICIES)
        except ExtensionNotFound:
            return []
        oids: list[str] = []
        for policy in cast(x509.CertificatePolicies, ext.value):
            dotted = policy.policy_identifier.dotted_string
            if dotted == ICP_BRASIL_POLICY_ARC or dotted.startswith(ICP_BRASIL_POLICY_ARC + "."):
                oids.append(dotted)
        return oids

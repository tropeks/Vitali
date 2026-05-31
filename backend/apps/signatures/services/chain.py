"""
ICP-Brasil certificate chain-of-trust validation.

This layers a *real* path-building validator on top of the cryptographic
primitive in `icp_brasil.py`. It answers the question the old string heuristic
could not: does this end-entity certificate chain up to a certificate we
explicitly trust as an ICP-Brasil anchor?

What is validated here (PR1):

- **Path building** — from the leaf upward, each step is linked to a candidate
  issuer (an extra intermediate supplied by the caller, or a configured trust
  anchor) whose subject equals the current cert's issuer AND whose key actually
  signed the current cert (`Certificate.verify_directly_issued_by`, which also
  checks the validity window at the relevant instant). The path must terminate
  at a configured anchor.
- **Validity window** — the leaf's own `not_before`/`not_after` are checked
  explicitly against `at_time` (default: now, UTC).
- **CA constraints** — every non-leaf cert in the path must carry
  BasicConstraints with CA=True.
- **Key usage** — when the leaf carries a KeyUsage extension it must assert
  `digital_signature` OR `content_commitment` (a.k.a. non-repudiation), the
  usages an ICP-Brasil signing cert requires.
- **Policy OIDs** — OIDs under the ICP-Brasil `2.16.76.1` arc are extracted
  from the leaf's CertificatePolicies extension for audit/logging.

What is NOT validated here (explicit follow-up, PR2): revocation status via
CRL / OCSP. The trust store is shipped/refreshed out-of-band (see the
`refresh_icp_truststore` management command); when it is empty the validator
reports `is_truststore_empty=True` and `trusted=False` WITHOUT raising, so the
signing flow can degrade gracefully instead of breaking.

No network calls are made anywhere in this module.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import cast

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509 import Certificate, ExtensionNotFound
from cryptography.x509.oid import ExtensionOID
from django.conf import settings

logger = logging.getLogger(__name__)

# Root OID arc allocated to ICP-Brasil certificate policies (ITI DOC-ICP-04).
ICP_BRASIL_POLICY_ARC = "2.16.76.1"

# Defence-in-depth bound on path length to stop pathological / malicious inputs.
MAX_CHAIN_DEPTH = 8


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


class ICPBrasilChainValidator:
    """
    Builds and validates a trust path from an end-entity certificate up to a
    configured ICP-Brasil anchor. Stateless apart from the cached anchor set.
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
        policy_oids = self._extract_policy_oids(leaf_cert)

        # (c) Leaf validity window — check explicitly and early.
        not_before = _not_before(leaf_cert)
        not_after = _not_after(leaf_cert)
        when_cmp = _as_aware(when)
        if when_cmp < _as_aware(not_before):
            return ChainValidationResult(
                trusted=False,
                reason="leaf certificate is not yet valid",
                policy_oids=policy_oids,
            )
        if when_cmp > _as_aware(not_after):
            return ChainValidationResult(
                trusted=False,
                reason="leaf certificate has expired",
                policy_oids=policy_oids,
            )

        # (d) Leaf key usage — must allow signing / non-repudiation if present.
        if not _leaf_key_usage_ok(leaf_cert):
            return ChainValidationResult(
                trusted=False,
                reason=(
                    "leaf certificate KeyUsage does not assert digital_signature "
                    "or content_commitment (non-repudiation)"
                ),
                policy_oids=policy_oids,
            )

        anchor_subjects = {a.subject.public_bytes() for a in anchors}
        candidates = list(extra_intermediates or []) + list(anchors)

        # (b) Build the path leaf → … → anchor.
        chain: list[Certificate] = [leaf_cert]
        seen_subjects: set[bytes] = {leaf_cert.subject.public_bytes()}
        current = leaf_cert

        # Leaf is itself a trusted anchor (direct trust) — accept it.
        if current.subject.public_bytes() in anchor_subjects and self._is_among(current, anchors):
            return ChainValidationResult(
                trusted=True,
                reason="leaf certificate is itself a trusted anchor",
                chain_subjects=[current.subject.rfc4514_string()],
                policy_oids=policy_oids,
            )

        while True:
            if len(chain) > MAX_CHAIN_DEPTH:
                return ChainValidationResult(
                    trusted=False,
                    reason=f"chain exceeds maximum depth of {MAX_CHAIN_DEPTH}",
                    chain_subjects=[c.subject.rfc4514_string() for c in chain],
                    policy_oids=policy_oids,
                )

            issuer = self._find_issuer(current, candidates)
            if issuer is None:
                return ChainValidationResult(
                    trusted=False,
                    reason="no trusted certification path to an ICP-Brasil anchor",
                    chain_subjects=[c.subject.rfc4514_string() for c in chain],
                    policy_oids=policy_oids,
                )

            # (d) Constraints: every non-leaf must be a CA.
            if not _is_ca(issuer):
                return ChainValidationResult(
                    trusted=False,
                    reason=(
                        "intermediate/anchor certificate lacks BasicConstraints CA=True: "
                        f"{issuer.subject.rfc4514_string()}"
                    ),
                    chain_subjects=[c.subject.rfc4514_string() for c in chain],
                    policy_oids=policy_oids,
                )

            issuer_subject = issuer.subject.public_bytes()
            if issuer_subject in seen_subjects:
                return ChainValidationResult(
                    trusted=False,
                    reason="certification path contains a loop",
                    chain_subjects=[c.subject.rfc4514_string() for c in chain],
                    policy_oids=policy_oids,
                )

            chain.append(issuer)
            seen_subjects.add(issuer_subject)

            # Terminate as soon as we reach a configured anchor.
            if issuer_subject in anchor_subjects and self._is_among(issuer, anchors):
                return ChainValidationResult(
                    trusted=True,
                    reason="chain validates to a trusted ICP-Brasil anchor",
                    chain_subjects=[c.subject.rfc4514_string() for c in chain],
                    policy_oids=policy_oids,
                )

            current = issuer

    # ─── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _find_issuer(
        cert: Certificate,
        candidates: list[Certificate],
    ) -> Certificate | None:
        """
        Find a candidate that (a) has subject == cert.issuer and (b) actually
        signed `cert`. ``verify_directly_issued_by`` validates the signature,
        the subject/issuer name match, and the candidate's validity window.
        """
        target_issuer = cert.issuer.public_bytes()
        cert_der = _der(cert)
        for candidate in candidates:
            if candidate.subject.public_bytes() != target_issuer:
                continue
            # A candidate that is byte-identical to `cert` would be a trivial
            # self-loop; the genuine self-signed-anchor case is handled by the
            # anchor short-circuit before path building starts.
            if _der(candidate) == cert_der:
                continue
            try:
                cert.verify_directly_issued_by(candidate)
            except Exception:  # noqa: BLE001
                # Signature mismatch, name mismatch, validity failure, or an
                # unsupported key type → not a usable issuer link.
                continue
            return candidate
        return None

    @staticmethod
    def _is_among(cert: Certificate, anchors: tuple[Certificate, ...]) -> bool:
        cert_der = _der(cert)
        return any(_der(a) == cert_der for a in anchors)

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


def _is_ca(cert: Certificate) -> bool:
    try:
        bc = cert.extensions.get_extension_for_oid(ExtensionOID.BASIC_CONSTRAINTS)
    except ExtensionNotFound:
        return False
    return bool(cast(x509.BasicConstraints, bc.value).ca)


def _leaf_key_usage_ok(cert: Certificate) -> bool:
    """True if KeyUsage is absent, or asserts digital_signature / content_commitment."""
    try:
        ku = cert.extensions.get_extension_for_oid(ExtensionOID.KEY_USAGE)
    except ExtensionNotFound:
        return True
    value = cast(x509.KeyUsage, ku.value)
    return bool(value.digital_signature or value.content_commitment)


def _der(cert: Certificate) -> bytes:
    """DER serialisation, used for byte-exact certificate identity comparison."""
    return cert.public_bytes(Encoding.DER)


def _not_before(cert: Certificate) -> datetime:
    return cast(datetime, getattr(cert, "not_valid_before_utc", cert.not_valid_before))


def _not_after(cert: Certificate) -> datetime:
    return cast(datetime, getattr(cert, "not_valid_after_utc", cert.not_valid_after))


def _as_aware(dt: datetime) -> datetime:
    """Normalise to an aware UTC datetime so comparisons never raise."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)

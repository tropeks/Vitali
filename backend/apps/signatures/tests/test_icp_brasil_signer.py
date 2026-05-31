"""
Tests for the ICP-Brasil signing primitive. Uses a self-signed RSA-2048 cert
packaged as PKCS#12 — the same shape an A1 cert takes — so the test suite is
self-contained and does not require an actual ICP-Brasil chain.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509 import NameOID

from apps.signatures.services.icp_brasil import (
    ICPBrasilSigner,
    ICPBrasilSignerError,
)


def _make_self_signed_pkcs12(
    *,
    subject_cn: str = "Dra Ana Silva CPF 12345678900",
    issuer_cn: str | None = None,
    password: str | None = "test-pass",
) -> tuple[bytes, x509.Certificate, rsa.RSAPrivateKey]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject_cn)])
    issuer = (
        x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer_cn)]) if issuer_cn else subject
    )
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=365))
        .sign(private_key=key, algorithm=hashes.SHA256())
    )
    pwd = password.encode("utf-8") if password else None
    encryption = serialization.BestAvailableEncryption(pwd) if pwd else serialization.NoEncryption()
    pfx = pkcs12.serialize_key_and_certificates(
        name=b"test", key=key, cert=cert, cas=None, encryption_algorithm=encryption
    )
    return pfx, cert, key


class TestICPBrasilSigner:
    def test_sign_returns_populated_result(self):
        pfx, cert, _ = _make_self_signed_pkcs12()
        document = b"Receita: Amoxicilina 500mg, 3x ao dia, 7 dias."

        result = ICPBrasilSigner.sign(document, pfx, "test-pass")

        assert result.signature
        assert isinstance(result.signature, bytes)
        # SHA-256 hash is 32 bytes → 64 hex chars
        assert len(result.document_hash_hex) == 64
        assert result.cert_subject == cert.subject.rfc4514_string()
        assert result.cert_issuer == cert.issuer.rfc4514_string()
        assert int(result.cert_serial_hex, 16) == cert.serial_number
        assert result.algorithm == "SHA256withRSA"
        # Self-signed cert with CN-only subject is NOT an ICP-Brasil cert.
        assert result.is_icp_brasil is False

    def test_sign_then_verify_roundtrip(self):
        pfx, cert, _ = _make_self_signed_pkcs12()
        document = "Encontro #42 — assinado digitalmente.".encode()

        result = ICPBrasilSigner.sign(document, pfx, "test-pass")

        assert ICPBrasilSigner.verify(document, result.signature, cert) is True

    def test_verify_fails_for_tampered_document(self):
        pfx, cert, _ = _make_self_signed_pkcs12()
        document = "Encontro #42 — assinado digitalmente.".encode()
        tampered = "Encontro #43 — assinado digitalmente.".encode()

        result = ICPBrasilSigner.sign(document, pfx, "test-pass")

        assert ICPBrasilSigner.verify(tampered, result.signature, cert) is False

    def test_wrong_password_raises_signer_error(self):
        pfx, _, _ = _make_self_signed_pkcs12(password="correct-pass")
        with pytest.raises(ICPBrasilSignerError):
            ICPBrasilSigner.sign(b"x", pfx, "wrong-pass")

    def test_malformed_bundle_raises_signer_error(self):
        with pytest.raises(ICPBrasilSignerError):
            ICPBrasilSigner.sign(b"not-a-pkcs12-blob", b"\x00\x01\x02", "pw")

    def test_no_password_pkcs12_still_signs(self):
        pfx, cert, _ = _make_self_signed_pkcs12(password=None)
        result = ICPBrasilSigner.sign(b"doc", pfx, None)
        assert ICPBrasilSigner.verify(b"doc", result.signature, cert)

    def test_is_icp_brasil_no_longer_set_from_issuer_string(self):
        # The issuer-DN string heuristic is NO LONGER the source of truth: even
        # an issuer DN that mentions "AC Raiz Brasileira" is not trusted unless
        # the cert chains to a configured anchor. With the (shipped) empty trust
        # store, the chain validator reports the store as empty and the flag is
        # False — proving the spoofable heuristic was retired.
        pfx, _, _ = _make_self_signed_pkcs12(
            subject_cn="Dr Bruno Lima CPF 98765432100",
            issuer_cn="AC Raiz Brasileira v10",
            password="pw",
        )
        result = ICPBrasilSigner.sign(b"doc", pfx, "pw")
        assert result.is_icp_brasil is False
        assert result.chain_truststore_empty is True

    def test_compute_hash_is_sha256(self):
        # SHA-256 of empty string is well-known.
        empty = ICPBrasilSigner.compute_hash(b"")
        assert empty.hex() == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

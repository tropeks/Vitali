"""
Tests for ICP-Brasil chain-of-trust validation (`ICPBrasilChainValidator`) and
its enforcement in the sign flow.

A fake ICP-Brasil-like hierarchy is generated in-memory:
    root CA  →  intermediate CA  →  leaf (policy OID under 2.16.76.1.*,
                                         KeyUsage digital_signature + CA=False)
Anchors (the root, and optionally the intermediate) are written to a tmp dir
that `ICP_BRASIL_TRUSTSTORE_DIR` is pointed at via `override_settings`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, pkcs12
from cryptography.x509 import NameOID
from cryptography.x509.oid import ObjectIdentifier
from django.test import override_settings

from apps.signatures.services.chain import ICPBrasilChainValidator
from apps.signatures.services.icp_brasil import ICPBrasilSigner, ICPBrasilSignerError

# A plausible ICP-Brasil end-entity policy OID (e-CPF A1 lives under 2.16.76.1.2.x).
LEAF_POLICY_OID = "2.16.76.1.2.1.30"


# ─── certificate factory ──────────────────────────────────────────────────────


def _key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _ca_cert(
    *,
    subject_cn: str,
    key: rsa.RSAPrivateKey,
    issuer_cn: str,
    issuer_key: rsa.RSAPrivateKey,
    not_before: datetime | None = None,
    not_after: datetime | None = None,
) -> x509.Certificate:
    now = datetime.now(UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(_name(subject_cn))
        .issuer_name(_name(issuer_cn))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before or now - timedelta(days=1))
        .not_valid_after(not_after or now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
    )
    return builder.sign(private_key=issuer_key, algorithm=hashes.SHA256())


def _leaf_cert(
    *,
    subject_cn: str,
    key: rsa.RSAPrivateKey,
    issuer_cn: str,
    issuer_key: rsa.RSAPrivateKey,
    policy_oid: str | None = LEAF_POLICY_OID,
    digital_signature: bool = True,
    not_before: datetime | None = None,
    not_after: datetime | None = None,
) -> x509.Certificate:
    now = datetime.now(UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(_name(subject_cn))
        .issuer_name(_name(issuer_cn))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before or now - timedelta(days=1))
        .not_valid_after(not_after or now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=digital_signature,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
    )
    if policy_oid:
        builder = builder.add_extension(
            x509.CertificatePolicies([x509.PolicyInformation(ObjectIdentifier(policy_oid), None)]),
            critical=False,
        )
    return builder.sign(private_key=issuer_key, algorithm=hashes.SHA256())


def _write_pem(cert: x509.Certificate, path) -> None:
    path.write_bytes(cert.public_bytes(Encoding.PEM))


def _self_signed_leaf() -> x509.Certificate:
    key = _key()
    return _leaf_cert(
        subject_cn="Untrusted Self Signed CPF 11122233344",
        key=key,
        issuer_cn="Untrusted Self Signed CPF 11122233344",
        issuer_key=key,
    )


@pytest.fixture
def hierarchy():
    """root CA → intermediate CA → leaf, all freshly generated."""
    root_key = _key()
    root = _ca_cert(
        subject_cn="AC Raiz Brasileira Teste",
        key=root_key,
        issuer_cn="AC Raiz Brasileira Teste",
        issuer_key=root_key,
    )
    inter_key = _key()
    inter = _ca_cert(
        subject_cn="AC Intermediaria Teste",
        key=inter_key,
        issuer_cn="AC Raiz Brasileira Teste",
        issuer_key=root_key,
    )
    leaf_key = _key()
    leaf = _leaf_cert(
        subject_cn="Dra Ana Silva CPF 12345678900",
        key=leaf_key,
        issuer_cn="AC Intermediaria Teste",
        issuer_key=inter_key,
    )
    return {
        "root": root,
        "root_key": root_key,
        "inter": inter,
        "inter_key": inter_key,
        "leaf": leaf,
        "leaf_key": leaf_key,
    }


@pytest.fixture
def truststore(tmp_path):
    """A tmp trust store dir + a cache-clearing override_settings context helper."""
    store = tmp_path / "truststore"
    store.mkdir()

    def _activate(*anchors: x509.Certificate):
        for i, anchor in enumerate(anchors):
            _write_pem(anchor, store / f"anchor-{i}.pem")
        ICPBrasilChainValidator.clear_cache()
        ctx = override_settings(ICP_BRASIL_TRUSTSTORE_DIR=str(store))
        ctx.enable()
        return ctx

    return store, _activate


# ─── chain validator ──────────────────────────────────────────────────────────


class TestICPBrasilChainValidator:
    def test_leaf_via_intermediate_to_trusted_root_is_trusted(self, hierarchy, truststore):
        store, activate = truststore
        ctx = activate(hierarchy["root"])
        try:
            result = ICPBrasilChainValidator().validate(
                hierarchy["leaf"], extra_intermediates=[hierarchy["inter"]]
            )
        finally:
            ctx.disable()
            ICPBrasilChainValidator.clear_cache()

        assert result.trusted is True
        assert result.is_truststore_empty is False
        assert LEAF_POLICY_OID in result.policy_oids
        # Chain reaches the root subject.
        assert any("AC Raiz Brasileira Teste" in s for s in result.chain_subjects)

    def test_self_signed_untrusted_is_not_trusted(self, truststore, hierarchy):
        store, activate = truststore
        ctx = activate(hierarchy["root"])  # populated, but not with this leaf's chain
        try:
            result = ICPBrasilChainValidator().validate(_self_signed_leaf())
        finally:
            ctx.disable()
            ICPBrasilChainValidator.clear_cache()

        assert result.trusted is False
        assert result.is_truststore_empty is False

    def test_expired_leaf_is_not_trusted(self, hierarchy, truststore):
        store, activate = truststore
        now = datetime.now(UTC)
        expired = _leaf_cert(
            subject_cn="Dr Expirado CPF 99988877766",
            key=_key(),
            issuer_cn="AC Intermediaria Teste",
            issuer_key=hierarchy["inter_key"],
            not_before=now - timedelta(days=400),
            not_after=now - timedelta(days=10),
        )
        ctx = activate(hierarchy["root"])
        try:
            result = ICPBrasilChainValidator().validate(
                expired, extra_intermediates=[hierarchy["inter"]]
            )
        finally:
            ctx.disable()
            ICPBrasilChainValidator.clear_cache()

        assert result.trusted is False
        assert "expired" in result.reason

    def test_leaf_without_signing_key_usage_is_not_trusted(self, hierarchy, truststore):
        store, activate = truststore
        no_sig = _leaf_cert(
            subject_cn="Dr Sem Assinatura CPF 55544433322",
            key=_key(),
            issuer_cn="AC Intermediaria Teste",
            issuer_key=hierarchy["inter_key"],
            digital_signature=False,
        )
        ctx = activate(hierarchy["root"])
        try:
            result = ICPBrasilChainValidator().validate(
                no_sig, extra_intermediates=[hierarchy["inter"]]
            )
        finally:
            ctx.disable()
            ICPBrasilChainValidator.clear_cache()

        assert result.trusted is False
        assert "KeyUsage" in result.reason

    def test_empty_truststore_reports_disabled(self, hierarchy, tmp_path):
        empty = tmp_path / "empty-store"
        empty.mkdir()
        ICPBrasilChainValidator.clear_cache()
        with override_settings(ICP_BRASIL_TRUSTSTORE_DIR=str(empty)):
            result = ICPBrasilChainValidator().validate(hierarchy["leaf"])
        ICPBrasilChainValidator.clear_cache()

        assert result.trusted is False
        assert result.is_truststore_empty is True
        assert result.reason == "trust store not populated"


# ─── sign-flow enforcement ────────────────────────────────────────────────────


def _pkcs12(cert: x509.Certificate, key: rsa.RSAPrivateKey, cas=None, password="pw") -> bytes:
    pwd = password.encode("utf-8") if password else None
    enc = serialization.BestAvailableEncryption(pwd) if pwd else serialization.NoEncryption()
    return pkcs12.serialize_key_and_certificates(
        name=b"test", key=key, cert=cert, cas=cas, encryption_algorithm=enc
    )


class TestSignFlowChainEnforcement:
    def test_empty_truststore_does_not_block_sign(self, hierarchy, tmp_path):
        empty = tmp_path / "empty-store"
        empty.mkdir()
        pfx = _pkcs12(hierarchy["leaf"], hierarchy["leaf_key"])
        ICPBrasilChainValidator.clear_cache()
        with override_settings(ICP_BRASIL_TRUSTSTORE_DIR=str(empty)):
            result = ICPBrasilSigner.sign(b"doc", pfx, "pw")
        ICPBrasilChainValidator.clear_cache()

        assert result.signature  # signing still happened
        assert result.is_icp_brasil is False
        assert result.chain_truststore_empty is True

    def test_populated_truststore_marks_trusted_chain(self, hierarchy, truststore):
        store, activate = truststore
        pfx = _pkcs12(hierarchy["leaf"], hierarchy["leaf_key"], cas=[hierarchy["inter"]])
        ctx = activate(hierarchy["root"])
        try:
            result = ICPBrasilSigner.sign(b"doc", pfx, "pw")
        finally:
            ctx.disable()
            ICPBrasilChainValidator.clear_cache()

        assert result.is_icp_brasil is True
        assert LEAF_POLICY_OID in result.policy_oids

    @override_settings(ICP_BRASIL_ENFORCE_CHAIN=True)
    def test_populated_truststore_enforced_untrusted_cert_raises(self, hierarchy, truststore):
        # An untrusted self-signed leaf, against a populated store with
        # enforcement on, must be REJECTED: sign() raises ICPBrasilSignerError
        # (which the view maps to HTTP 400).
        store, activate = truststore
        leaf_key = _key()
        untrusted = _leaf_cert(
            subject_cn="Impostor CPF 00011122233",
            key=leaf_key,
            issuer_cn="Impostor CPF 00011122233",
            issuer_key=leaf_key,
        )
        pfx = _pkcs12(untrusted, leaf_key)
        ctx = activate(hierarchy["root"])
        try:
            with pytest.raises(ICPBrasilSignerError):
                ICPBrasilSigner.sign(b"doc", pfx, "pw")
        finally:
            ctx.disable()
            ICPBrasilChainValidator.clear_cache()

    @override_settings(ICP_BRASIL_ENFORCE_CHAIN=False)
    def test_populated_truststore_not_enforced_untrusted_cert_allowed(self, hierarchy, truststore):
        # With enforcement OFF, an untrusted cert still signs but is recorded as
        # non-ICP-Brasil (audit-only mode).
        store, activate = truststore
        leaf_key = _key()
        untrusted = _leaf_cert(
            subject_cn="Impostor CPF 00011122233",
            key=leaf_key,
            issuer_cn="Impostor CPF 00011122233",
            issuer_key=leaf_key,
        )
        pfx = _pkcs12(untrusted, leaf_key)
        ctx = activate(hierarchy["root"])
        try:
            result = ICPBrasilSigner.sign(b"doc", pfx, "pw")
        finally:
            ctx.disable()
            ICPBrasilChainValidator.clear_cache()

        assert result.signature
        assert result.is_icp_brasil is False
        assert result.chain_truststore_empty is False

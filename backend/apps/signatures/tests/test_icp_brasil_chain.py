"""
Tests for ICP-Brasil chain-of-trust validation (`ICPBrasilChainValidator`) and
its enforcement in the sign flow.

A fake ICP-Brasil-like hierarchy is generated in-memory, made RFC 5280-valid so
it passes pyhanko-certvalidator for the trusted case:
    root CA  →  intermediate CA (BasicConstraints CA=True + KeyUsage keyCertSign)
              →  leaf (policy OID under 2.16.76.1.*, KeyUsage digital_signature +
                       non_repudiation, CA=False)
Anchors (the root, and optionally the intermediate) are written to a tmp dir
that `ICP_BRASIL_TRUSTSTORE_DIR` is pointed at via `override_settings`.

The adversarial cases below exercise the RFC 5280 obligations a cross-model
review (Gemini) found the old hand-rolled validator skipped: expired
intermediate, intermediate missing keyCertSign, and pathLenConstraint violation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from asn1crypto import crl as asn1_crl
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
    path_length: int | None = None,
    key_cert_sign: bool = True,
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
        .add_extension(x509.BasicConstraints(ca=True, path_length=path_length), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                # keyCertSign is what RFC 5280 requires for a cert that signs
                # other certs; without it pyhanko rejects the path.
                key_cert_sign=key_cert_sign,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
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
    content_commitment: bool = True,
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
                # non_repudiation (content_commitment) — required alongside
                # digital_signature by the validator's validate_usage set.
                content_commitment=content_commitment,
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


def _crl(
    *,
    issuer_cn: str,
    issuer_key: rsa.RSAPrivateKey,
    revoked_serials: list[int] | None = None,
) -> asn1_crl.CertificateList:
    """
    Build a CRL signed by ``issuer_key`` revoking ``revoked_serials`` (empty =
    a valid CRL that lists nothing), converted to asn1crypto for injection via
    ``validate(..., crls=[...])``. Fully offline — no network.
    """
    now = datetime.now(UTC)
    builder = (
        x509.CertificateRevocationListBuilder()
        .issuer_name(_name(issuer_cn))
        .last_update(now - timedelta(hours=1))
        .next_update(now + timedelta(days=1))
    )
    for serial in revoked_serials or []:
        builder = builder.add_revoked_certificate(
            x509.RevokedCertificateBuilder()
            .serial_number(serial)
            .revocation_date(now - timedelta(hours=2))
            .build()
        )
    crl = builder.sign(private_key=issuer_key, algorithm=hashes.SHA256())
    return asn1_crl.CertificateList.load(crl.public_bytes(Encoding.DER))


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
            content_commitment=False,
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
        # pyhanko reports the missing key-usage purpose(s).
        assert "digital signature" in result.reason.lower()

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

    # ─── adversarial cases (Gemini findings the hand-rolled validator missed) ──

    def test_expired_intermediate_in_path_is_not_trusted(self, hierarchy, truststore):
        # Gemini finding #1: validity-window checks on INTERMEDIATES. The leaf is
        # within its own window, but the intermediate that signed it is expired.
        store, activate = truststore
        now = datetime.now(UTC)
        inter_key = _key()
        expired_inter = _ca_cert(
            subject_cn="AC Intermediaria Expirada",
            key=inter_key,
            issuer_cn="AC Raiz Brasileira Teste",
            issuer_key=hierarchy["root_key"],
            not_before=now - timedelta(days=800),
            not_after=now - timedelta(days=30),
        )
        leaf = _leaf_cert(
            subject_cn="Dra Sob Inter Expirada CPF 10101010101",
            key=_key(),
            issuer_cn="AC Intermediaria Expirada",
            issuer_key=inter_key,
        )
        ctx = activate(hierarchy["root"])
        try:
            result = ICPBrasilChainValidator().validate(leaf, extra_intermediates=[expired_inter])
        finally:
            ctx.disable()
            ICPBrasilChainValidator.clear_cache()

        assert result.trusted is False

    def test_intermediate_without_key_cert_sign_is_not_trusted(self, hierarchy, truststore):
        # Gemini finding #3: keyCertSign KeyUsage on CA certs. The intermediate is
        # a CA (BasicConstraints CA=True) but lacks keyCertSign, so it must not be
        # accepted as a certificate issuer.
        store, activate = truststore
        inter_key = _key()
        no_kcs_inter = _ca_cert(
            subject_cn="AC Intermediaria Sem keyCertSign",
            key=inter_key,
            issuer_cn="AC Raiz Brasileira Teste",
            issuer_key=hierarchy["root_key"],
            key_cert_sign=False,
        )
        leaf = _leaf_cert(
            subject_cn="Dra Sob Inter Sem KCS CPF 20202020202",
            key=_key(),
            issuer_cn="AC Intermediaria Sem keyCertSign",
            issuer_key=inter_key,
        )
        ctx = activate(hierarchy["root"])
        try:
            result = ICPBrasilChainValidator().validate(leaf, extra_intermediates=[no_kcs_inter])
        finally:
            ctx.disable()
            ICPBrasilChainValidator.clear_cache()

        assert result.trusted is False

    def test_path_length_constraint_violation_is_not_trusted(self, hierarchy, truststore):
        # Gemini finding #2: BasicConstraints pathLenConstraint. An intermediate
        # with pathlen=0 may issue end-entity certs but NOT another CA below it.
        # Here a second intermediate sits below the pathlen=0 one → must reject.
        store, activate = truststore
        inter_a_key = _key()
        inter_a = _ca_cert(
            subject_cn="AC Intermediaria Pathlen0",
            key=inter_a_key,
            issuer_cn="AC Raiz Brasileira Teste",
            issuer_key=hierarchy["root_key"],
            path_length=0,
        )
        inter_b_key = _key()
        inter_b = _ca_cert(
            subject_cn="AC Intermediaria Abaixo Pathlen0",
            key=inter_b_key,
            issuer_cn="AC Intermediaria Pathlen0",
            issuer_key=inter_a_key,
        )
        leaf = _leaf_cert(
            subject_cn="Dra Sob Pathlen Violado CPF 30303030303",
            key=_key(),
            issuer_cn="AC Intermediaria Abaixo Pathlen0",
            issuer_key=inter_b_key,
        )
        ctx = activate(hierarchy["root"])
        try:
            result = ICPBrasilChainValidator().validate(
                leaf, extra_intermediates=[inter_a, inter_b]
            )
        finally:
            ctx.disable()
            ICPBrasilChainValidator.clear_cache()

        assert result.trusted is False


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


# ─── revocation (PR2, opt-in, OFFLINE CRL injection) ──────────────────────────


class TestICPBrasilRevocation:
    """
    Revocation checking via injected CRLs — no network. Under fail-closed
    `require` mode pyhanko-certvalidator demands revocation info for EVERY cert
    in the path, so each case injects an intermediate CRL (signed by the root)
    plus a leaf CRL (signed by the intermediate).
    """

    def _path_crls(self, hierarchy, *, revoke_leaf: bool) -> list[asn1_crl.CertificateList]:
        inter_crl = _crl(
            issuer_cn="AC Raiz Brasileira Teste",
            issuer_key=hierarchy["root_key"],
            revoked_serials=[],
        )
        leaf_crl = _crl(
            issuer_cn="AC Intermediaria Teste",
            issuer_key=hierarchy["inter_key"],
            revoked_serials=[hierarchy["leaf"].serial_number] if revoke_leaf else [],
        )
        return [inter_crl, leaf_crl]

    def test_revocation_on_with_revoking_crl_is_not_trusted(self, hierarchy, truststore):
        # (a) revocation ON + CRL revoking the leaf ⇒ trusted=False, reason
        # mentions revoked, revocation_checked=True.
        store, activate = truststore
        ctx = activate(hierarchy["root"])
        try:
            result = ICPBrasilChainValidator().validate(
                hierarchy["leaf"],
                extra_intermediates=[hierarchy["inter"]],
                check_revocation=True,
                crls=self._path_crls(hierarchy, revoke_leaf=True),
            )
        finally:
            ctx.disable()
            ICPBrasilChainValidator.clear_cache()

        assert result.trusted is False
        assert "revoked" in result.reason.lower()
        assert result.revocation_checked is True

    def test_revocation_on_with_valid_crl_is_trusted(self, hierarchy, truststore):
        # (b) revocation ON + CRL NOT listing the leaf ⇒ trusted=True,
        # revocation_checked=True.
        store, activate = truststore
        ctx = activate(hierarchy["root"])
        try:
            result = ICPBrasilChainValidator().validate(
                hierarchy["leaf"],
                extra_intermediates=[hierarchy["inter"]],
                check_revocation=True,
                crls=self._path_crls(hierarchy, revoke_leaf=False),
            )
        finally:
            ctx.disable()
            ICPBrasilChainValidator.clear_cache()

        assert result.trusted is True
        assert result.revocation_checked is True

    def test_revocation_off_ignores_revoking_crl(self, hierarchy, truststore):
        # (c) revocation OFF (default) ⇒ PR1 behaviour: leaf trusted even with a
        # revoking CRL present-but-unused, revocation_checked=False.
        store, activate = truststore
        ctx = activate(hierarchy["root"])
        try:
            result = ICPBrasilChainValidator().validate(
                hierarchy["leaf"],
                extra_intermediates=[hierarchy["inter"]],
                # check_revocation defaults to settings.ICP_BRASIL_CHECK_REVOCATION
                # (False) — pass the revoking CRL to prove it is ignored.
                crls=self._path_crls(hierarchy, revoke_leaf=True),
            )
        finally:
            ctx.disable()
            ICPBrasilChainValidator.clear_cache()

        assert result.trusted is True
        assert result.revocation_checked is False

    def test_revocation_on_with_empty_crl_list_fails_closed_offline(self, hierarchy, truststore):
        # Fix 1 (gating bug): passing crls=[] explicitly means "offline, no
        # revinfo available". Under require mode this must FAIL CLOSED with a
        # revinfo-unavailable reason — it must NOT fall through to the production
        # branch and attempt a network fetch. Everything here is offline; the
        # leaf is otherwise trusted, so a trusted=True result would prove a
        # wrongful network fetch (or fall-through). It returns promptly because
        # allow_fetching stays False (no network is ever touched).
        store, activate = truststore
        ctx = activate(hierarchy["root"])
        try:
            result = ICPBrasilChainValidator().validate(
                hierarchy["leaf"],
                extra_intermediates=[hierarchy["inter"]],
                check_revocation=True,
                crls=[],
            )
        finally:
            ctx.disable()
            ICPBrasilChainValidator.clear_cache()

        assert result.trusted is False
        # revinfo could not be obtained under require → fail closed, and since
        # the revocation step WAS reached, revocation_checked is True.
        assert "revocation information unavailable" in result.reason.lower()
        assert result.revocation_checked is True

    def test_revocation_on_expired_leaf_reports_revocation_not_checked(self, hierarchy, truststore):
        # Fix 2 (over-reporting): an expired leaf fails the validity-window check
        # BEFORE pyhanko reaches revocation, even with revocation ON. The result
        # must be trusted=False AND revocation_checked=False — revocation was
        # never evaluated, so claiming it was would pollute the audit trail.
        store, activate = truststore
        now = datetime.now(UTC)
        expired = _leaf_cert(
            subject_cn="Dr Expirado Revoc CPF 44455566677",
            key=_key(),
            issuer_cn="AC Intermediaria Teste",
            issuer_key=hierarchy["inter_key"],
            not_before=now - timedelta(days=400),
            not_after=now - timedelta(days=10),
        )
        ctx = activate(hierarchy["root"])
        try:
            result = ICPBrasilChainValidator().validate(
                expired,
                extra_intermediates=[hierarchy["inter"]],
                check_revocation=True,
                crls=self._path_crls(hierarchy, revoke_leaf=False),
            )
        finally:
            ctx.disable()
            ICPBrasilChainValidator.clear_cache()

        assert result.trusted is False
        assert "expired" in result.reason
        assert result.revocation_checked is False

    @override_settings(ICP_BRASIL_ENFORCE_CHAIN=True)
    def test_sign_enforced_with_revocation_on_and_revoked_cert_raises(
        self, hierarchy, truststore, monkeypatch
    ):
        # (d) sign() with enforce + revocation ON + revoked cert ⇒ raises. The
        # revoking CRLs are injected by patching the validator's validate() to
        # supply them (sign() doesn't expose a CRL param — production fetches
        # them; tests inject offline).
        store, activate = truststore
        pfx = _pkcs12(hierarchy["leaf"], hierarchy["leaf_key"], cas=[hierarchy["inter"]])
        crls = self._path_crls(hierarchy, revoke_leaf=True)

        original_validate = ICPBrasilChainValidator.validate

        def _patched(self, leaf_cert, extra_intermediates=None, at_time=None, **kwargs):
            return original_validate(
                self,
                leaf_cert,
                extra_intermediates=extra_intermediates,
                at_time=at_time,
                check_revocation=True,
                crls=crls,
            )

        monkeypatch.setattr(ICPBrasilChainValidator, "validate", _patched)

        ctx = activate(hierarchy["root"])
        try:
            with pytest.raises(ICPBrasilSignerError):
                ICPBrasilSigner.sign(b"doc", pfx, "pw")
        finally:
            ctx.disable()
            ICPBrasilChainValidator.clear_cache()

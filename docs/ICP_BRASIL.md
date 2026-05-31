# ICP-Brasil — Certificate Chain-of-Trust Validation

> **Refs:** [SECURITY.md](./SECURITY.md) | `apps.signatures`
> **Legal basis:** MP 2.200-2/2001 (institui a ICP-Brasil), CFM Res. 2.299/2021
> (prontuário eletrônico), ITI DOC-ICP-04 (hierarquia de confiança).

The digital-signature module (`apps.signatures`) signs clinical documents with an
ICP-Brasil A1 certificate (PKCS#12), using SHA-256 + RSA-PKCS#1 v1.5 — the
AD-RB profile of DOC-ICP-15.03. This document describes the **chain-of-trust
validation** layered on top of that primitive.

---

## What is validated now (PR1)

`ICPBrasilChainValidator` (`apps/signatures/services/chain.py`) runs during every
sign request, after the PKCS#12 bundle is loaded. It performs **offline** (no
network) validation:

1. **Certification path** — it builds a path from the end-entity ("leaf")
   certificate upward. At each step it finds an issuer among the PKCS#12's bundled
   intermediates ∪ the configured trust anchors, where the candidate's *subject*
   equals the current cert's *issuer* **and** the candidate's key actually signed
   the current cert (`Certificate.verify_directly_issued_by`, which validates the
   signature, the name match, and the issuer's validity window). The path must
   terminate at a **configured anchor**. Loops, dead ends, and paths longer than
   8 certificates are rejected.

2. **Validity window** — the leaf's own `not_before` / `not_after` are checked
   explicitly against the validation time (default: now, UTC).

3. **CA constraints** — every non-leaf certificate in the path must carry a
   BasicConstraints extension asserting `CA=True`.

4. **Key usage** — when the leaf carries a KeyUsage extension, it must assert
   `digital_signature` **or** `content_commitment` (non-repudiation) — the usages
   an ICP-Brasil signing certificate is expected to have.

5. **Policy OIDs** — certificate policy OIDs under the ICP-Brasil arc
   `2.16.76.1` are extracted from the leaf's CertificatePolicies extension and
   logged (e.g. an e-CPF A1 lives under `2.16.76.1.2.x`).

The result of this validation — **not** the old, spoofable "issuer DN contains
ICP-Brasil" string heuristic — is what sets `DigitalSignature.is_icp_brasil`. The
heuristic (`_issuer_mentions_icp_brasil`) is retained only for diagnostics.

### NOT validated yet — revocation (PR2)

Revocation status (**CRL** / **OCSP**) is **not** checked in this PR. A
certificate that has been revoked but is otherwise within its validity window and
chains to a trusted anchor will currently validate as trusted. CRL/OCSP checking
(with caching and a soft/hard-fail policy) is the explicit follow-up, **PR2**.

A3 hardware tokens (PKCS#11) remain out of scope; the flow expects an A1 PKCS#12
bundle.

---

## Populating the trust store

The validator loads its trust anchors (AC Raiz Brasileira + intermediate ACs)
from `settings.ICP_BRASIL_TRUSTSTORE_DIR` — every `*.pem` / `*.crt` file (PEM or
DER) is read and cached. Default location:

```
backend/apps/signatures/truststore/
```

Populate / refresh it from the official ITI bundle:

```sh
python manage.py refresh_icp_truststore
```

This downloads the consolidated PKCS#7 (`.p7b`) bundle published by the **ITI**
(Instituto Nacional de Tecnologia da Informação) and splits it into one PEM
anchor per CA:

- Repository: <https://www.gov.br/iti/pt-br/assuntos/repositorio/repositorio-ac-raiz>
- Bundle: `https://acraiz.icpbrasil.gov.br/credenciadas/CertificadosAC-ICP-Brasil/ACcompactado.p7b`

The command is **best-effort**: if the source is unreachable it fails with a
clear message and a non-zero exit. It is an operations tool and is **never**
required at test/CI time. For air-gapped refreshes, download the bundle manually
and pass `--file`:

```sh
python manage.py refresh_icp_truststore --file /path/to/ACcompactado.p7b
```

Anchor `*.pem` / `*.crt` / `*.p7b` files in the trust store directory are
git-ignored — anchors are operational data, not source. After refreshing,
restart the workers so the in-process anchor cache is rebuilt
(`ICPBrasilChainValidator.clear_cache()` is called by the command in-process).

---

## Enforcement & the empty-store fallback

Setting (`vitali/settings/base.py`, overridable via env):

```python
ICP_BRASIL_ENFORCE_CHAIN = env.bool("ICP_BRASIL_ENFORCE_CHAIN", default=True)
ICP_BRASIL_TRUSTSTORE_DIR = env.str("ICP_BRASIL_TRUSTSTORE_DIR", default=<truststore dir>)
```

Behaviour during a sign request:

| Trust store | `ICP_BRASIL_ENFORCE_CHAIN` | Chain result | Outcome |
|-------------|----------------------------|--------------|---------|
| **Empty**   | (any)                      | not validated | Sign **proceeds**; a WARNING is logged; `is_icp_brasil=False`. Never blocks. |
| Populated   | `True` (default)           | untrusted    | `ICPBrasilSignerError` → **HTTP 400**. |
| Populated   | `True`                     | trusted      | Sign proceeds; `is_icp_brasil=True`; policy OIDs logged. |
| Populated   | `False`                    | untrusted    | Sign proceeds (audit-only); `is_icp_brasil=False`. |

The **empty-store fallback** exists so that a fresh deployment whose trust store
has not yet been populated does not break signing — instead it degrades to
recording signatures as non-ICP-Brasil and logs a loud WARNING until an operator
runs `refresh_icp_truststore`.

---

## Where it lives

| File | Role |
|------|------|
| `apps/signatures/services/chain.py` | `ICPBrasilChainValidator`, `ChainValidationResult` |
| `apps/signatures/services/icp_brasil.py` | signing primitive + chain wiring + enforcement |
| `apps/signatures/management/commands/refresh_icp_truststore.py` | populate the trust store from ITI |
| `apps/signatures/truststore/` | trust anchors (operational data; git-ignored) |
| `vitali/settings/base.py` | `ICP_BRASIL_TRUSTSTORE_DIR`, `ICP_BRASIL_ENFORCE_CHAIN` |

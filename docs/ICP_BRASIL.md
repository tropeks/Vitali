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
sign request, after the PKCS#12 bundle is loaded. It delegates path validation to
**[`pyhanko-certvalidator`](https://pypi.org/project/pyhanko-certvalidator/)**, a
vetted **RFC 5280** path-validation implementation, and runs fully **offline**
(`allow_fetching=False` — no network in PR1).

> **Why a library, not the hand-rolled builder?** The original validator was a
> hand-rolled X.509 path builder. A **cross-model adversarial review (Gemini)**
> found it silently skipped five RFC 5280 obligations — validity-window checks on
> intermediates/anchors, BasicConstraints `pathLenConstraint`, `keyCertSign`
> KeyUsage on CA certs, NameConstraints, and weak signature-algorithm rejection.
> A real RFC 5280 validator handles all of these, so the builder was replaced.

The validator now enforces, against a `ValidationContext` whose `trust_roots`
are the configured ICP-Brasil anchors:

1. **Full RFC 5280 path validation** — a path is built and validated from the
   end-entity ("leaf") certificate up to a **configured anchor**, using the
   PKCS#12's bundled intermediates as path-building hints. For **every** cert in
   the path this checks: signature, name chaining, the **validity window**
   (leaf **and** intermediates **and** anchor), BasicConstraints (`CA=True` plus
   **`pathLenConstraint`**), **`keyCertSign`** KeyUsage on CA certs,
   **NameConstraints**, and rejection of **weak signature algorithms**.

2. **Leaf key usage** — `validate_usage({'digital_signature', 'non_repudiation'})`
   requires the leaf to assert both signing usages an ICP-Brasil signing
   certificate carries.

3. **Policy OIDs** — certificate policy OIDs under the ICP-Brasil arc
   `2.16.76.1` are extracted from the leaf's CertificatePolicies extension and
   logged (e.g. an e-CPF A1 lives under `2.16.76.1.2.x`). This is independent of
   the library's path check.

The result of this validation — **not** the old, spoofable "issuer DN contains
ICP-Brasil" string heuristic — is what sets `DigitalSignature.is_icp_brasil`. The
heuristic (`_issuer_mentions_icp_brasil`) is retained only for diagnostics.

### NOT validated yet — revocation (PR2)

Revocation status (**CRL** / **OCSP**) is **not** checked in this PR: the
`ValidationContext` is built with `allow_fetching=False` and
`revocation_mode='soft-fail'`, so no network calls are made and a certificate
that has been revoked but is otherwise within its validity window and chains to a
trusted anchor will currently validate as trusted. **PR2** enables revocation
simply by flipping `allow_fetching=True` and `revocation_mode='require'` on the
`ValidationContext` (pyhanko-certvalidator then fetches and checks CRL/OCSP).

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
| `apps/signatures/services/chain.py` | `ICPBrasilChainValidator`, `ChainValidationResult` — RFC 5280 path validation via `pyhanko-certvalidator` |
| `apps/signatures/services/icp_brasil.py` | signing primitive + chain wiring + enforcement |
| `apps/signatures/management/commands/refresh_icp_truststore.py` | populate the trust store from ITI |
| `apps/signatures/truststore/` | trust anchors (operational data; git-ignored) |
| `vitali/settings/base.py` | `ICP_BRASIL_TRUSTSTORE_DIR`, `ICP_BRASIL_ENFORCE_CHAIN` |

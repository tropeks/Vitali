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

### Revocation (CRL / OCSP) — implemented, opt-in (PR2)

Revocation status (**CRL** / **OCSP**) is now checked, but it is **opt-in and
OFF by default**, gated by `ICP_BRASIL_CHECK_REVOCATION`:

```python
ICP_BRASIL_CHECK_REVOCATION  = env.bool("ICP_BRASIL_CHECK_REVOCATION", default=False)
ICP_BRASIL_REVOCATION_TIMEOUT = env.int("ICP_BRASIL_REVOCATION_TIMEOUT", default=10)  # seconds
```

- **OFF (default):** unchanged PR1 behaviour — the `ValidationContext` uses
  `allow_fetching=False` + `revocation_mode='soft-fail'`, so no network calls are
  made and revocation is not enforced. A revoked-but-otherwise-valid certificate
  still validates as trusted. `ChainValidationResult.revocation_checked` is
  `False`.

- **ON:** `revocation_mode='require'` — **fail-closed**. Every certificate in the
  path must have valid revocation information or the path is rejected
  (`trusted=False`). A revoked cert yields `trusted=False` with a
  `"certificate revoked: …"` reason; missing/unfetchable revocation info yields
  `trusted=False` with a `"revocation information unavailable (require mode): …"`
  reason. `revocation_checked` is `True`.

  **Outbound-network implication:** in production (ON, no injected revinfo) the
  context uses `allow_fetching=True`, so **`sign()` makes outbound CRL/OCSP HTTP
  calls to ITI endpoints during the request**. Each fetch is bounded by
  `ICP_BRASIL_REVOCATION_TIMEOUT` via pyhanko-certvalidator's
  `RequestsFetcherBackend(per_request_timeout=…)`. Because `require` is
  fail-closed, **enable this only after confirming the ITI CRL/OCSP endpoints
  are reachable from the signing host** — otherwise legitimate signatures will be
  rejected when revocation info can't be fetched.

Tests exercise revocation **offline**: a CRL is built with
`cryptography.x509.CertificateRevocationListBuilder`, converted to asn1crypto,
and injected via `validate(check_revocation=True, crls=[…])` with
`allow_fetching=False` — no network is touched in CI. (Under `require`, revinfo
is required for *every* path cert, so tests inject both an intermediate CRL
signed by the root and a leaf CRL signed by the intermediate.)

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
ICP_BRASIL_ENFORCE_CHAIN      = env.bool("ICP_BRASIL_ENFORCE_CHAIN", default=True)
ICP_BRASIL_TRUSTSTORE_DIR     = env.str("ICP_BRASIL_TRUSTSTORE_DIR", default=<truststore dir>)
ICP_BRASIL_CHECK_REVOCATION   = env.bool("ICP_BRASIL_CHECK_REVOCATION", default=False)  # opt-in, fail-closed
ICP_BRASIL_REVOCATION_TIMEOUT = env.int("ICP_BRASIL_REVOCATION_TIMEOUT", default=10)     # seconds per fetch
```

A **revoked** certificate (when `ICP_BRASIL_CHECK_REVOCATION=True`) simply makes
the chain result `trusted=False`, so the table below already covers it: with
`ICP_BRASIL_ENFORCE_CHAIN=True` it maps to **HTTP 400**.

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
| `vitali/settings/base.py` | `ICP_BRASIL_TRUSTSTORE_DIR`, `ICP_BRASIL_ENFORCE_CHAIN`, `ICP_BRASIL_CHECK_REVOCATION`, `ICP_BRASIL_REVOCATION_TIMEOUT` |

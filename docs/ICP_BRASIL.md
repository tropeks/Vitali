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

**Current state and production prerequisite.** Nothing in the repository sets
`ICP_BRASIL_CHECK_REVOCATION`: staging runs `vitali.settings.production` with the
default `False`, and so would production today. A revoked certificate therefore
still signs as ICP-Brasil. **Turning revocation on is a prerequisite for
production**, in this order:

1. confirm the ITI CRL/OCSP endpoints are reachable from the signing host
   (egress/firewall);
2. sign with real doctors' `.pfx` files in staging with the flag on — `require`
   mode needs revocation info for every certificate in the path, so a bundle that
   passed under `soft-fail` (for example a `.pfx` exported without its
   intermediate chain) may start being refused. Treat that as a finding to
   resolve with the doctor, not a reason to switch back to `soft-fail`;
3. only then set `ICP_BRASIL_CHECK_REVOCATION=True` in the production environment.

A3 hardware tokens (PKCS#11) remain out of scope; the flow expects an A1 PKCS#12
bundle.

---

## Private key handling (model A)

The doctor's private key does **not** live on the server. `POST
/api/v1/signatures/sign/` receives the PKCS#12 in the request body —
`pkcs12_b64` and `pkcs12_password` are `write_only` serializer fields
(`apps/signatures/serializers.py`) — uses it for that one signature, and discards
it. `DigitalSignature` stores the signature, the document hash and certificate
metadata (subject, issuer, serial, validity, `is_icp_brasil`), never the key or
the password.

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

### Persistence across deploys (order 014)

The trust store used to live only in the image: anchors copied into the staging
container at 15:27 on 16/09 were gone after the 15:39 deploy. Since order 014 the
`django` service in **staging and production** mounts the named volume
`icp_truststore` at `/app/apps/signatures/truststore`
(`docker-compose.staging.yml`, `docker-compose.prod.yml`). Run
`refresh_icp_truststore` once **inside the container**; the anchors survive
`up -d` and image upgrades.

### Fetching the bundle: use `--file`

The online refresh fails today: `acraiz.icpbrasil.gov.br` serves TLS **without
the intermediate** and chained to `ISRG Root YE`, which is absent from current
trust stores (measured on 16/09, order 014). Do **not** work around it with
`verify=False`. Download `ACcompactado.p7b` with a browser, check it, copy it into
the container and run:

```sh
python manage.py refresh_icp_truststore --file /path/to/ACcompactado.p7b
```

Afterwards list the trust store directory and confirm it holds the anchor files,
not only `README.md`/`.gitignore`.

---

## Enforcement & the empty trust store

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
| **Empty**   | `True` (default; staging, production) | not validated | **Refused** (order 015): `ICPBrasilSignerError("trust store not populated")` → **HTTP 400**, ERROR logged, **no `DigitalSignature` row written**. |
| **Empty**   | `False` (`development.py`: dev, CI) | not validated | Sign proceeds; WARNING logged; `is_icp_brasil=False`. |
| Populated   | `True` (default)           | untrusted    | `ICPBrasilSignerError` → **HTTP 400**. |
| Populated   | `True`                     | trusted      | Sign proceeds; `is_icp_brasil=True`; policy OIDs logged. |
| Populated   | `False`                    | untrusted    | Sign proceeds (audit-only); `is_icp_brasil=False`. |

**Why an empty store refuses (order 015).** The old fallback let an unpopulated
store degrade silently: the doctor signed, the API answered `201`, and the row was
stored with `is_icp_brasil=False` — a signature without legal value and no visible
error. That happened in staging on 16/09 after a deploy wiped the anchors. Now
`ICP_BRASIL_ENFORCE_CHAIN` also covers the empty store; there is no new flag.
`vitali/settings/development.py` pins `ICP_BRASIL_ENFORCE_CHAIN=False` explicitly
so dev and CI, which do not carry the ITI bundle, keep the old behaviour by choice.

**Operational consequence:** with an empty store in staging or production, **nobody
can sign** until the store is populated. Order of operations for a new
environment (order 015): deploy the `icp_truststore` volume → run
`refresh_icp_truststore --file <ACcompactado.p7b>` inside the container → only then
expect signing to work.

---

## Where it lives

| File | Role |
|------|------|
| `apps/signatures/services/chain.py` | `ICPBrasilChainValidator`, `ChainValidationResult` — RFC 5280 path validation via `pyhanko-certvalidator` |
| `apps/signatures/services/icp_brasil.py` | signing primitive + chain wiring + enforcement |
| `apps/signatures/management/commands/refresh_icp_truststore.py` | populate the trust store from ITI |
| `apps/signatures/truststore/` | trust anchors (operational data; git-ignored) |
| `vitali/settings/base.py` | `ICP_BRASIL_TRUSTSTORE_DIR`, `ICP_BRASIL_ENFORCE_CHAIN`, `ICP_BRASIL_CHECK_REVOCATION`, `ICP_BRASIL_REVOCATION_TIMEOUT` |
| `vitali/settings/development.py` | pins `ICP_BRASIL_ENFORCE_CHAIN=False` for dev/CI (order 015) |
| `docker-compose.staging.yml`, `docker-compose.prod.yml` | `icp_truststore` volume on `/app/apps/signatures/truststore` (order 014) |
| `apps/signatures/tests/test_truststore_vazio_recusa.py` | proves the empty-store refusal: 400 with reason **and** no row written |

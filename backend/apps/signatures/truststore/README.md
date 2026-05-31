# ICP-Brasil trust store

This directory holds the trusted ICP-Brasil CA anchors (AC Raiz Brasileira +
intermediate ACs) used by `ICPBrasilChainValidator`. Each anchor is a `*.pem`
or `*.crt` file (PEM or DER).

It ships **empty on purpose** — anchors are operational data, not source. While
empty, chain validation is reported as "disabled" and signing is NOT blocked
(see `ICP_BRASIL_ENFORCE_CHAIN` and `docs/ICP_BRASIL.md`).

Populate / refresh it with:

```sh
python manage.py refresh_icp_truststore
```

`*.pem` and `*.crt` files in this directory are git-ignored so refreshed
anchors are not committed; only this README is tracked.

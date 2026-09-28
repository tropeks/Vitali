# MinIO efêmero para a prova do destino frio S3 (ordem 032). SÓ TESTE, SÓ NA LAB.
#
# Autorização do Diretor (27/09/2026): MinIO na lab, sem dado real, sem porta
# publicada, derrubado ao fim de cada recibo. Quem sobe e derruba é
# scripts/pytest.sh com PYTEST_MINIO=1; nada aqui é imagem de produção.
#
# O projeto MinIO arquivou o repositório e tirou as imagens do Docker Hub/quay e
# o dl.min.io (HTTP 410). Os binários continuam nos releases do GitHub: baixados
# com o sha256 FIXADO aqui (conferido contra o .sha256sum do release em
# 27/09/2026), não lido da rede na hora do build.
FROM python:3.12-slim

ARG MINIO_RELEASE=RELEASE.2025-09-07T16-13-09Z
ARG MINIO_SHA256=7c5bd8512c6e966455b1d198209358b2d191c77a83ab377c4073281065fb855f
ARG MC_RELEASE=RELEASE.2025-08-13T08-35-41Z
ARG MC_SHA256=01f866e9c5f9b87c2b09116fa5d7c06695b106242d829a8bb32990c00312e891

RUN python - <<PY
import hashlib, urllib.request
for name, rel, sha in (
    ("minio", "${MINIO_RELEASE}", "${MINIO_SHA256}"),
    ("mc", "${MC_RELEASE}", "${MC_SHA256}"),
):
    url = f"https://github.com/minio/{name}/releases/download/{rel}/{name}.linux-amd64.{rel}"
    data = urllib.request.urlopen(url, timeout=120).read()
    got = hashlib.sha256(data).hexdigest()
    if got != sha:
        raise SystemExit(f"{name}: sha256 {got} != {sha}")
    with open(f"/usr/local/bin/{name}", "wb") as f:
        f.write(data)
PY
RUN chmod 0755 /usr/local/bin/minio /usr/local/bin/mc

COPY setup.sh /setup.sh
COPY auditlog-cold-writer-policy.json /policy.json
ENTRYPOINT ["bash", "/setup.sh"]

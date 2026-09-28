"""Fixtures compartilhadas pelos testes do destino frio S3 (ordem 032)."""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import io
import json
import tempfile
import uuid
from pathlib import Path

import boto3
from botocore.response import StreamingBody
from dateutil.relativedelta import relativedelta

from apps.core import cold_storage
from apps.core import cold_storage_backends as csb
from apps.core.tests.test_cold_storage import _seed_one_row

BUCKET = "vitali-auditlog-cold"
AGORA = dt.datetime(2026, 9, 27, 12, 0, tzinfo=dt.UTC)
TRAVA_ATE = AGORA + relativedelta(months=240)


def b64_sha256(data: bytes) -> str:
    return base64.b64encode(hashlib.sha256(data).digest()).decode()


def cliente_falso():
    """Cliente S3 sem rede, para o ``Stubber``."""
    return boto3.client(
        "s3",
        region_name="sa-east-1",
        aws_access_key_id="teste",
        aws_secret_access_key="teste",
    )


def arquivos(tmp: Path, conteudo: bytes = b"cifrado\n", manifesto: dict | None = None):
    payload = tmp / "p.jsonl.gpg"
    payload.write_bytes(conteudo)
    manifest = tmp / "p.manifest.json"
    manifest.write_text(json.dumps(manifesto or {"row_count": 1}))
    return payload, manifest


def corpo(data: bytes) -> StreamingBody:
    return StreamingBody(io.BytesIO(data), len(data))


def exporta_de_verdade(backend) -> cold_storage.ColdExportReceipt:
    """Uma partição real, com uma linha, exportada pelo caminho de produção."""
    leaf = _seed_one_row(schema_name=f"drill{uuid.uuid4().hex[:6]}")
    return cold_storage.export_and_verify_partition(leaf, backend=backend)


class Guarda:
    """Backend local que guarda os arquivos exatos que o export gravou, para o
    ``Stubber`` servir o conteúdo cifrado real no ``get_object``."""

    def __init__(self):
        self.dir = Path(tempfile.mkdtemp(prefix="cold-guarda-"))
        self.local = csb.LocalDiskColdStorageBackend(directory=self.dir)

    def store(self, **kw):
        return self.local.store(**kw)

    def verify_stored(self, location, sha):
        return self.local.verify_stored(location, sha)

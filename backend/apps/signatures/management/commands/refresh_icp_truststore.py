"""
Management command: refresh_icp_truststore
===========================================
Downloads the official ITI ICP-Brasil CA bundle and writes each CA certificate
as an individual PEM anchor into ``settings.ICP_BRASIL_TRUSTSTORE_DIR``, where
``ICPBrasilChainValidator`` (apps.signatures.services.chain) picks them up.

Usage:
    python manage.py refresh_icp_truststore
    python manage.py refresh_icp_truststore --url <override>
    python manage.py refresh_icp_truststore --file /path/to/local_bundle.p7b
    python manage.py refresh_icp_truststore --dir /custom/truststore

Official source (ITI — Instituto Nacional de Tecnologia da Informação):
    https://www.gov.br/iti/pt-br/assuntos/repositorio/repositorio-ac-raiz
The consolidated PKCS#7 bundle of every ICP-Brasil AC is published as:
    https://acraiz.icpbrasil.gov.br/credenciadas/CertificadosAC-ICP-Brasil/ACcompactado.zip
    https://acraiz.icpbrasil.gov.br/credenciadas/CertificadosAC-ICP-Brasil/ACcompactado.p7b
This command defaults to the ``.p7b`` PKCS#7 bundle and splits it into one PEM
file per CA certificate.

Network is BEST-EFFORT: this is an operations tool. If the source is
unreachable, the command fails with a clear message and a NON-zero exit code,
but it is NEVER required at test/CI time (the validator degrades gracefully
when the trust store is empty).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding, pkcs7
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

# Official ITI consolidated PKCS#7 bundle of all ICP-Brasil ACs.
DEFAULT_BUNDLE_URL = (
    "https://acraiz.icpbrasil.gov.br/credenciadas/CertificadosAC-ICP-Brasil/ACcompactado.zip"
)


class Command(BaseCommand):
    help = (
        "Download the official ITI ICP-Brasil CA bundle and write each CA cert "
        "as an individual PEM anchor into ICP_BRASIL_TRUSTSTORE_DIR. "
        "Official source: https://www.gov.br/iti (acraiz.icpbrasil.gov.br). "
        "Network is best-effort and never required at test/CI time."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--url",
            default=DEFAULT_BUNDLE_URL,
            help=f"PKCS#7/.p7b bundle URL (default: {DEFAULT_BUNDLE_URL})",
        )
        parser.add_argument(
            "--file",
            default=None,
            help="Read the PKCS#7/.p7b bundle from a local file instead of the network.",
        )
        parser.add_argument(
            "--dir",
            default=None,
            help="Override the trust store directory (default: ICP_BRASIL_TRUSTSTORE_DIR).",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=30,
            help="HTTP timeout in seconds (default: 30).",
        )

    def handle(self, *args, **options):
        target_dir = Path(options["dir"] or settings.ICP_BRASIL_TRUSTSTORE_DIR)
        target_dir.mkdir(parents=True, exist_ok=True)

        raw = self._load_bundle(options)
        certs = self._parse_bundle(raw)
        if not certs:
            raise CommandError("Bundle contained no certificates.")

        written = self._write_anchors(certs, target_dir)
        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {written} ICP-Brasil CA anchor(s) to {target_dir}. "
                "Restart workers so the anchor cache is rebuilt."
            )
        )

    # ─── loading ────────────────────────────────────────────────────────────

    def _load_bundle(self, options) -> bytes:
        local = options.get("file")
        if local:
            path = Path(local)
            if not path.is_file():
                raise CommandError(f"--file not found: {path}")
            self.stdout.write(f"Reading ICP-Brasil bundle from {path} …")
            return path.read_bytes()

        url = options["url"]
        self.stdout.write(f"Downloading ICP-Brasil bundle from {url} …")
        try:
            import requests

            resp = requests.get(url, timeout=options["timeout"], verify=False)
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001 — best-effort ops tool, any failure is fatal-but-clear.
            raise CommandError(
                f"Could not download the ICP-Brasil bundle from {url}: {exc}\n"
                "This is an operations tool and is not required at test/CI time. "
                "Check connectivity, or pass --file with a manually downloaded "
                "bundle from https://www.gov.br/iti (acraiz.icpbrasil.gov.br)."
            ) from exc
        return resp.content

    # ─── parsing ──────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_bundle(raw: bytes) -> list[x509.Certificate]:
        """Parse a ZIP bundle or a single PKCS#7 / PEM / DER file."""
        import io
        import zipfile

        certs = []
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                for name in z.namelist():
                    if name.endswith(".crt") or name.endswith(".cer") or name.endswith(".pem"):
                        content = z.read(name)
                        try:
                            # Try to parse as DER
                            certs.append(x509.load_der_x509_certificate(content))
                        except ValueError:
                            # Try PEM
                            try:
                                certs.append(x509.load_pem_x509_certificate(content))
                            except ValueError:
                                pass
            return certs
        except zipfile.BadZipFile:
            pass  # Fallback to parsing as pkcs7

        is_pem = b"-----BEGIN" in raw[:64] or raw.lstrip().startswith(b"-----BEGIN")
        try:
            if is_pem:
                return pkcs7.load_pem_pkcs7_certificates(raw)
            return pkcs7.load_der_pkcs7_certificates(raw)
        except ValueError as exc:
            raise CommandError(f"Could not parse the bundle: {exc}") from exc

    # ─── writing ────────────────────────────────────────────────────────────

    def _write_anchors(self, certs: list[x509.Certificate], target_dir: Path) -> int:
        written = 0
        for cert in certs:
            pem = cert.public_bytes(Encoding.PEM)
            name = self._anchor_filename(cert)
            (target_dir / name).write_bytes(pem)
            written += 1
            self.stdout.write(f"  + {name}  ({cert.subject.rfc4514_string()})")
        return written

    @staticmethod
    def _anchor_filename(cert: x509.Certificate) -> str:
        """Stable, filesystem-safe filename derived from the subject CN + fingerprint."""
        try:
            cn = cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)[0].value
        except (IndexError, ValueError):
            cn = "ca"
        slug = re.sub(r"[^A-Za-z0-9._-]+", "_", str(cn)).strip("_")[:48] or "ca"
        fp = hashlib.sha256(cert.public_bytes(Encoding.DER)).hexdigest()[:12]
        return f"{slug}-{fp}.pem"

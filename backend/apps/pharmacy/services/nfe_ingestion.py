import hashlib
import re
import xml.etree.ElementTree as ET
from decimal import Decimal

from django.db import IntegrityError, transaction

from ..models import NFeReceipt, NFeReceiptItem


def ingest_xml(raw: bytes, *, source: str, uploaded_by=None, external_id: str = ""):
    """Parse and quarantine NF-e. Never mutates stock."""
    digest = hashlib.sha256(raw).hexdigest()
    if NFeReceipt.objects.filter(payload_sha256=digest).exists():
        return NFeReceipt.objects.get(payload_sha256=digest), False
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError("XML inválido") from exc
    ns = {"n": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}
    pref = "n:" if ns else ""
    inf = root.find(f".//{pref}infNFe", ns)
    if inf is None:
        raise ValueError("NF-e ausente")
    key = re.sub(r"\D", "", inf.attrib.get("Id", "").replace("NFe", ""))
    def text(path):
        node = root.find(f".//{pref}{path.replace('/', f'/{pref}')}", ns)
        return (node.text or "").strip() if node is not None else ""
    issuer, recipient = text("emit/CNPJ"), text("dest/CNPJ")
    if len(key) != 44 or len(issuer) not in (11, 14) or len(recipient) not in (11, 14):
        raise ValueError("Chave, emitente ou destinatário inválido")
    if NFeReceipt.objects.filter(access_key=key).exists():
        return NFeReceipt.objects.get(access_key=key), False
    with transaction.atomic():
        receipt = NFeReceipt.objects.create(access_key=key, issuer_cnpj=issuer,
            recipient_cnpj=recipient, xml=raw.decode("utf-8", "replace"),
            uploaded_by=uploaded_by, source=source, external_id=external_id,
            payload_sha256=digest)
        for i, node in enumerate(root.findall(f".//{pref}det", ns), 1):
            prod = node.find(f"{pref}prod", ns)
            def p(name):
                el = prod.find(f"{pref}{name}", ns) if prod is not None else None
                return (el.text or "").strip() if el is not None else ""
            NFeReceiptItem.objects.create(receipt=receipt, sequence=i,
                supplier_code=p("cProd"), description=p("xProd")[:300],
                quantity=Decimal(p("qCom") or "0"), unit_price=Decimal(p("vUnCom") or "0"),
                ncm=p("NCM"), barcode=p("cEAN"))
    return receipt, True

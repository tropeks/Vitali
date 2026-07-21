"""Small, strict LIS boundary. It intentionally does not implement a wire transport."""

import hashlib
import json

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.models import AuditLog
from apps.emr.models import LabIntegrationMessage, LabOrder


def payload_digest(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_hl7_oru(raw: str) -> dict:
    if len(raw) > 1_000_000 or "\x00" in raw:
        raise ValidationError("Mensagem HL7 inválida ou grande demais.")
    segments = [line.strip() for line in raw.replace("\n", "\r").split("\r") if line.strip()]
    if not segments or not segments[0].startswith("MSH|"):
        raise ValidationError("MSH ausente.")
    msh = segments[0].split("|")
    if len(msh) < 10 or not msh[9].strip():
        raise ValidationError("MSH-10 (message id) é obrigatório.")
    message_type = msh[8].split("^")[0] if len(msh) > 8 else ""
    if message_type != "ORU":
        raise ValidationError("A entrada HL7 aceita somente ORU.")
    obr = next((segment.split("|") for segment in segments if segment.startswith("OBR|")), None)
    if not obr or len(obr) < 4 or not obr[3].strip():
        raise ValidationError("OBR-3 (accession) é obrigatório.")
    results = []
    for segment in segments:
        if not segment.startswith("OBX|"):
            continue
        fields = segment.split("|")
        if len(fields) < 6 or not fields[3].strip() or not fields[5].strip():
            raise ValidationError("Cada OBX requer código em OBX-3 e valor em OBX-5.")
        code_parts = fields[3].split("^")
        results.append(
            {
                "code": code_parts[0],
                "code_system": code_parts[2] if len(code_parts) > 2 else "local",
                "value": fields[5],
                "unit": fields[6] if len(fields) > 6 else "",
                "reference_range": fields[7] if len(fields) > 7 else "",
                "flag": fields[8] if len(fields) > 8 else "",
            }
        )
    if not results:
        raise ValidationError("Ao menos um OBX é obrigatório.")
    return {"message_id": msh[9], "accession_number": obr[3], "results": results}


def parse_canonical(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValidationError("Payload canônico deve ser um objeto.")
    allowed = {"message_id", "accession_number", "results", "specimens", "instrument"}
    if not set(value).issubset(allowed):
        raise ValidationError("Payload canônico contém campos desconhecidos.")
    if not value.get("message_id") or not value.get("accession_number"):
        raise ValidationError("message_id e accession_number são obrigatórios.")
    results = value.get("results")
    if not isinstance(results, list) or not results:
        raise ValidationError("results deve ser uma lista não vazia.")
    for result in results:
        if not isinstance(result, dict) or not result.get("code") or "value" not in result:
            raise ValidationError("Cada resultado requer code e value.")
        if not isinstance(result["value"], str | int | float | bool):
            raise ValidationError("value deve ser escalar.")
    return value


def normalize_payload(format_name: str, payload: object) -> tuple[dict, str]:
    if format_name == LabIntegrationMessage.Format.HL7_V2:
        if not isinstance(payload, str):
            raise ValidationError("Payload HL7 deve ser texto.")
        return parse_hl7_oru(payload), payload
    if format_name in (
        LabIntegrationMessage.Format.CANONICAL,
        LabIntegrationMessage.Format.ASTM,
    ):
        canonical = parse_canonical(payload)
        return canonical, json.dumps(payload, sort_keys=True, separators=(",", ":"))
    raise ValidationError("Formato não suportado.")


def apply_message(message: LabIntegrationMessage, user, ip_address="") -> LabIntegrationMessage:
    try:
        with transaction.atomic():
            message = LabIntegrationMessage.objects.select_for_update().get(pk=message.pk)
            if message.status != LabIntegrationMessage.Status.PENDING:
                raise ValidationError("Somente mensagens pendentes podem ser aplicadas.")
            payload = message.canonical_payload
            try:
                order = LabOrder.objects.select_for_update().get(
                    accession_number=payload["accession_number"]
                )
            except LabOrder.DoesNotExist as exc:
                raise ValidationError("Accession não corresponde a um pedido.") from exc
            if order.status not in (LabOrder.Status.COLLECTED, LabOrder.Status.IN_PROGRESS):
                raise ValidationError("Pedido não está coletado e aberto.")
            items = {item.test.code: item for item in order.items.select_related("test")}
            items.update({item.loinc_code: item for item in items.values() if item.loinc_code})
            resolved = []
            for result in payload["results"]:
                item = items.get(result["code"])
                if not item or item.is_validated:
                    raise ValidationError(
                        f"Resultado não corresponde a item aberto: {result['code']}"
                    )
                resolved.append((item, result))
            for item, result in resolved:
                item.result_value = str(result["value"])
                item.result_data = {"lis": result}
                item.resulted_at = timezone.now()
                item.save(update_fields=["result_value", "result_data", "resulted_at"])
            order.status = LabOrder.Status.IN_PROGRESS
            order.save(update_fields=["status"])
            message.status = LabIntegrationMessage.Status.APPLIED
            message.lab_order = order
            message.applied_by = user
            message.applied_at = timezone.now()
            message.save(update_fields=["status", "lab_order", "applied_by", "applied_at"])
    except ValidationError as exc:
        message = LabIntegrationMessage.objects.get(pk=message.pk)
        message.status = LabIntegrationMessage.Status.REJECTED
        message.error = str(exc.detail)
        message.save(update_fields=["status", "error"])
        AuditLog.objects.create(
            user=user,
            action="lis_message_reject",
            resource_type="LabIntegrationMessage",
            resource_id=str(message.id),
            new_data={"source": message.source, "message_id": message.message_id},
            ip_address=ip_address or None,
        )
        raise
    AuditLog.objects.create(
        user=user,
        action="lis_message_apply",
        resource_type="LabIntegrationMessage",
        resource_id=str(message.id),
        new_data={"order": str(order.id), "result_count": len(resolved)},
        ip_address=ip_address or None,
    )
    return message


def render_orm(order: LabOrder, message_id: str) -> str:
    timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
    lines = [
        f"MSH|^~\\&|VITALI|VITALI|LIS|LAB|{timestamp}||ORM^O01|{message_id}|P|2.5.1",
        f"PID|||{order.patient.medical_record_number}",
        f"ORC|NW|{order.id}|{order.accession_number}",
    ]
    for index, item in enumerate(order.items.select_related("test"), 1):
        code = item.loinc_code or item.test.code
        system = "LN" if item.loinc_code else "99VITALI"
        lines.append(
            f"OBR|{index}|{order.id}|{order.accession_number}|{code}^{item.test_name}^{system}"
        )
    return "\r".join(lines) + "\r"

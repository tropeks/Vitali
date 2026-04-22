"""
S-063: AI Prescription Safety Checker.

Checks a new PrescriptionItem for drug interactions, allergy crossings,
dose issues, and contraindications using Claude Haiku.

Key design decisions:
- Feature flag ai_prescription_safety defaults OFF (LGPD DPA required).
- Cache key includes schema_name for LGPD tenant isolation.
- Fail-open: any LLM error → SafetyResult(is_safe=True, degraded=True).
- AIDPAStatus must be signed before LLM is called.
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field

from django.core.cache import cache
from django.db import connection

from apps.ai.circuit_breaker import is_open, record_failure, record_success
from apps.ai.gateway import ClaudeGateway, LLMGatewayError
from apps.ai.rate_limiter import is_rate_limited
from apps.ai.services import get_tenant_ai_config

logger = logging.getLogger(__name__)

SAFETY_CACHE_TTL = 3600  # 1 hour

VALID_ALERT_TYPES = {"drug_interaction", "allergy", "dose", "contraindication"}
VALID_SEVERITIES = {"caution", "contraindication"}


@dataclass
class SafetyAlert:
    alert_type: str  # 'drug_interaction', 'allergy', 'dose', 'contraindication'
    severity: str  # 'caution', 'contraindication'
    message: str
    recommendation: str = ""


@dataclass
class SafetyResult:
    is_safe: bool
    alerts: list[SafetyAlert] = field(default_factory=list)
    cached: bool = False
    degraded: bool = False


def _build_cache_key(
    schema_name: str, drug_name: str, other_drugs: list, allergy_names: list
) -> str:
    """
    Build a tenant-scoped cache key for safety check results.
    Includes schema_name to prevent cross-tenant cache leakage (LGPD).
    """
    raw = "|".join(
        [
            drug_name.lower().strip(),
            ",".join(sorted(d.lower().strip() for d in other_drugs)),
            ",".join(sorted(a.lower().strip() for a in allergy_names)),
            schema_name,
        ]
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"ai:safety:{schema_name}:{digest}"


def _check_dpa_signed(schema_name: str) -> bool:
    """
    Check if the tenant has a signed DPA (required for health data AI processing).
    Fail-open: if DPA status cannot be determined, return False (block AI).
    """
    try:
        from apps.core.models import AIDPAStatus, Tenant

        tenant = Tenant.objects.get(schema_name=schema_name)
        try:
            dpa = tenant.ai_dpa_status
            return dpa.is_signed
        except AIDPAStatus.DoesNotExist:
            return False
    except Exception:
        logger.warning("Could not check DPA status for schema %s", schema_name, exc_info=True)
        return False


class PrescriptionSafetyChecker:
    """
    Checks a PrescriptionItem for safety issues using AI.

    Always fail-open: errors → SafetyResult(is_safe=True, degraded=True).
    Feature flag ai_prescription_safety must be True AND DPA must be signed.
    """

    def check(self, prescription_item, prescription) -> SafetyResult:
        """
        Run safety check for a PrescriptionItem.

        1. Check feature flag ai_prescription_safety (OFF by default)
        2. Check DPA signed status (LGPD requirement)
        3. Check rate limit / circuit breaker
        4. Build context: patient allergies + other drugs + schema_name
        5. Cache hit → return cached result
        6. Call LLM (Claude Haiku, max_tokens=512)
        7. Parse + validate JSON response
        8. Cache result (1h TTL)
        9. Return SafetyResult
        """
        schema_name = connection.schema_name

        # 1. Feature flag check
        config = get_tenant_ai_config(schema_name)
        # TenantAIConfig may not have ai_prescription_safety; default to False
        if not getattr(config, "ai_prescription_safety", False):
            logger.debug("ai_prescription_safety flag is OFF for %s", schema_name)
            return SafetyResult(is_safe=True, alerts=[], degraded=False)

        # 2. DPA signed check (LGPD)
        if not _check_dpa_signed(schema_name):
            logger.info("DPA not signed for %s — skipping safety check", schema_name)
            return SafetyResult(is_safe=True, alerts=[], degraded=False)

        # 3. Rate limit check (fail-open)
        try:
            if is_rate_limited(schema_name, limit=getattr(config, "rate_limit_per_hour", 500)):
                logger.warning("Rate limit exceeded for safety check in %s", schema_name)
                return SafetyResult(is_safe=True, alerts=[], degraded=True)
        except Exception:
            pass  # fail-open

        # 3b. Circuit breaker check (fail-open)
        try:
            if is_open(schema_name, "prescription_safety"):
                logger.warning("Circuit breaker OPEN for safety in %s", schema_name)
                return SafetyResult(is_safe=True, alerts=[], degraded=True)
        except Exception:
            pass  # fail-open

        # 4. Build context
        try:
            patient = prescription.patient
            allergy_names = list(
                patient.allergies.filter(status="active").values_list("substance", flat=True)
            )
            # All other drugs in same prescription (excluding current item)
            other_items = prescription.items.exclude(id=prescription_item.id)
            other_drugs = [
                item.generic_name or (item.drug.name if item.drug_id else "")
                for item in other_items
            ]
            other_drugs = [d for d in other_drugs if d]

            drug_name = (
                prescription_item.generic_name
                or (prescription_item.drug.name if prescription_item.drug_id else "")
                or "Medicamento desconhecido"
            )
        except Exception:
            logger.warning("Could not build safety check context", exc_info=True)
            return SafetyResult(is_safe=True, alerts=[], degraded=True)

        # 5. Cache check
        cache_key = _build_cache_key(schema_name, drug_name, other_drugs, allergy_names)
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            try:
                alerts = [SafetyAlert(**a) for a in cached_data.get("alerts", [])]
                return SafetyResult(
                    is_safe=len(alerts) == 0,
                    alerts=alerts,
                    cached=True,
                    degraded=False,
                )
            except Exception:
                pass  # stale/corrupt cache — fall through to LLM

        # 6. Call LLM
        try:
            gateway = ClaudeGateway()
            system_prompt = (
                "Você é um especialista em segurança farmacológica. "
                "Analise possíveis interações medicamentosas, alergias cruzadas, "
                "problemas de dose ou contraindicações. "
                "Responda APENAS com um JSON válido no formato: "
                '{"alerts": [{"type": "drug_interaction|allergy|dose|contraindication", '
                '"severity": "caution|contraindication", '
                '"message": "...", "recommendation": "..."}]}. '
                'Se não houver alertas, retorne {"alerts": []}. '
                "Não inclua nenhum outro texto."
            )

            allergies_text = ", ".join(allergy_names) if allergy_names else "Nenhuma registrada"
            other_drugs_text = ", ".join(other_drugs) if other_drugs else "Nenhum"
            user_prompt = (
                f"Novo medicamento sendo prescrito: {drug_name}\n"
                f"Outros medicamentos já na receita: {other_drugs_text}\n"
                f"Alergias conhecidas do paciente: {allergies_text}\n\n"
                "Verifique interações, alergias cruzadas, dose e contraindicações. "
                "Retorne um JSON com os alertas encontrados."
            )

            text, tokens_in, tokens_out = gateway.complete(
                system=system_prompt,
                user=user_prompt,
                max_tokens=512,
            )
            record_success(schema_name, "prescription_safety")
        except LLMGatewayError:
            record_failure(schema_name, "prescription_safety")
            logger.warning("LLM error during safety check", exc_info=True)
            return SafetyResult(is_safe=True, alerts=[], degraded=True)
        except Exception:
            logger.warning("Unexpected error during safety check", exc_info=True)
            return SafetyResult(is_safe=True, alerts=[], degraded=True)

        # 7. Parse + validate JSON
        try:
            data = json.loads(text)
            raw_alerts = data.get("alerts", [])
            validated_alerts = []
            for alert_dict in raw_alerts:
                alert_type = alert_dict.get("type", "")
                severity = alert_dict.get("severity", "")
                if alert_type not in VALID_ALERT_TYPES:
                    logger.debug("Skipping unknown alert_type: %s", alert_type)
                    continue
                if severity not in VALID_SEVERITIES:
                    logger.debug("Skipping unknown severity: %s", severity)
                    continue
                validated_alerts.append(
                    SafetyAlert(
                        alert_type=alert_type,
                        severity=severity,
                        message=alert_dict.get("message", ""),
                        recommendation=alert_dict.get("recommendation", ""),
                    )
                )
        except (json.JSONDecodeError, Exception):
            logger.warning("Failed to parse LLM safety response: %s", text[:200])
            return SafetyResult(is_safe=True, alerts=[], degraded=True)

        # 8. Cache result
        try:
            serializable = [
                {
                    "alert_type": a.alert_type,
                    "severity": a.severity,
                    "message": a.message,
                    "recommendation": a.recommendation,
                }
                for a in validated_alerts
            ]
            cache.set(cache_key, {"alerts": serializable}, SAFETY_CACHE_TTL)
        except Exception:
            pass  # cache failure is non-fatal

        return SafetyResult(
            is_safe=len(validated_alerts) == 0,
            alerts=validated_alerts,
            cached=False,
            degraded=False,
        )

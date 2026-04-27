"""
S-081: DPA-signed cascade service — Sprint 19 / F-05.

Locked architecture decisions (mirroring Sprint 18 hr/services.py):
  1A — Service-layer orchestrator, DPASignView.post() is a thin wrapper.
  1B — Atomic DB block + transaction.on_commit fail-open for admin email.
  2A — AuditLog correlation_id in new_data JSON for full cascade tracing.

Usage:
    service = DPASigningService(requesting_user=request.user)
    result = service.sign(tenant=request.tenant, ip_address=..., user_agent=...)
"""

from uuid import uuid4

from django.db import transaction


class DPASigningService:
    """
    Orchestrates DPA signing + per-tenant AI FeatureFlag enablement in one
    atomic transaction. Admin notification email is queued post-commit (fail-open).

    Locked decision 1A: explicit service-layer, NOT inline view logic.
    Locked decision 1B: transaction.on_commit for Celery — DB never rolls back
        due to email failure.
    Locked decision 2A: all AuditLog entries share correlation_id.
    """

    AI_MODULE_KEYS = ("ai_scribe", "ai_tuss", "ai_prescription_safety", "ai_cid10")

    def __init__(self, requesting_user) -> None:
        self.requesting_user = requesting_user
        self.correlation_id = str(uuid4())

    def sign(self, *, tenant, ip_address: str = "", user_agent: str = "") -> dict:
        """
        Signs the DPA + atomically enables the per-tenant AI FeatureFlag rows
        + queues admin notification email (fail-open via on_commit).

        Returns:
            {
                'dpa_status': AIDPAStatus,
                'flags_enabled': list[str],  # only newly-flipped flags
                'already_signed': bool,
            }
        """
        from datetime import date

        from apps.core.models import AIDPAStatus, FeatureFlag
        from apps.core.tasks import send_dpa_signed_admin_email

        with transaction.atomic():
            dpa_status, _ = AIDPAStatus.objects.get_or_create(tenant=tenant)

            if dpa_status.is_signed:
                return {
                    "dpa_status": dpa_status,
                    "flags_enabled": [],
                    "already_signed": True,
                }

            # 1. Mark DPA signed
            dpa_status.dpa_signed_date = date.today()
            dpa_status.signed_by_user = self.requesting_user
            dpa_status.save(update_fields=["dpa_signed_date", "signed_by_user"])

            # 2. Atomic bulk-enable AI feature flags (same atomic block as the audit —
            #    eng review D3: flags and audit are committed atomically together).
            flags_to_enable = []
            for module_key in self.AI_MODULE_KEYS:
                flag, _ = FeatureFlag.objects.get_or_create(
                    tenant=tenant,
                    module_key=module_key,
                    defaults={"is_enabled": False},
                )
                if not flag.is_enabled:
                    flag.is_enabled = True
                    flag.save(update_fields=["is_enabled"])
                    flags_to_enable.append(module_key)

            # 3. AuditLog the cascade chain — single correlation_id ties
            #    dpa_signed → flags_enabled → email_queued (decision 2A).
            self._audit(
                "dpa_signed",
                "ai_dpa_status",
                dpa_status.id,
                new_data={
                    "signed_at": dpa_status.dpa_signed_date.isoformat(),
                    "signed_by_id": str(self.requesting_user.id),
                    "ip_address": ip_address,
                    "user_agent": user_agent[:500],
                },
            )
            for module_key in flags_to_enable:
                self._audit(
                    "ai_feature_flag_enabled",
                    "feature_flag",
                    f"{tenant.schema_name}:{module_key}",
                    new_data={"module_key": module_key},
                )

            # 4. Queue admin notification email — fail-open via on_commit (decision 1B).
            admin_user_id = str(self.requesting_user.id)
            correlation_id = self.correlation_id
            transaction.on_commit(
                lambda: send_dpa_signed_admin_email.delay(
                    admin_user_id, list(self.AI_MODULE_KEYS), correlation_id
                )
            )
            self._audit("dpa_admin_email_queued", "user", admin_user_id)

        return {
            "dpa_status": dpa_status,
            "flags_enabled": flags_to_enable,
            "already_signed": False,
        }

    def _audit(
        self,
        action: str,
        resource_type: str,
        resource_id: object,
        new_data: dict | None = None,
    ) -> None:
        """Write an AuditLog entry tagged with this service invocation's correlation_id."""
        from apps.core.models import AuditLog

        data = dict(new_data) if new_data else {}
        data["correlation_id"] = self.correlation_id
        AuditLog.objects.create(
            user=self.requesting_user,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id),
            new_data=data,
        )

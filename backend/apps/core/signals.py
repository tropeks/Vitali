"""
Core signals — auto-create FeatureFlags, audit logging for model changes.
"""

import logging

from django.db.models.deletion import ProtectedError
from django.db.models.signals import post_delete, post_save, pre_delete
from django.dispatch import receiver

logger = logging.getLogger(__name__)

# ─── Models that trigger automatic audit logs ─────────────────────────────────
# Add model labels here as new clinical apps are introduced.
AUDITED_MODELS = {
    "core.User": "user",
    # Future apps:
    # "emr.Patient": "patient",
    # "emr.Encounter": "encounter",
    # "emr.ClinicalNote": "clinical_note",
    # "emr.Prescription": "prescription",
}


def _serialize_instance(instance):
    """Convert a model instance to a plain dict for audit storage."""
    from django.forms.models import model_to_dict

    try:
        data = model_to_dict(instance)
        # Convert non-serializable types to strings
        return {
            k: str(v)
            if not isinstance(v, str | int | float | bool | type(None) | list | dict)
            else v
            for k, v in data.items()
        }
    except Exception:
        return {"id": str(getattr(instance, "pk", None))}


def _write_audit(action: str, resource_type: str, resource_id: str, old_data=None, new_data=None):
    """Write an AuditLog entry, silently ignoring errors to never disrupt the main flow."""
    from apps.core.middleware import get_current_request
    from apps.core.models import AuditLog

    request = get_current_request()
    user = None
    ip_address = None
    user_agent = ""

    if request:
        u = getattr(request, "user", None)
        if u and u.is_authenticated:
            user = u
        ip_address = _get_client_ip(request)
        user_agent = request.META.get("HTTP_USER_AGENT", "")[:500]

    try:
        AuditLog.objects.create(
            user=user,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id),
            old_data=old_data,
            new_data=new_data,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    except Exception as exc:
        logger.warning("Failed to write audit log: %s", exc)


def _get_client_ip(request) -> str | None:
    """Extract real IP from X-Forwarded-For or REMOTE_ADDR."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


# ─── Generic audit signal handlers ───────────────────────────────────────────


def handle_post_save(sender, instance, created, **kwargs):
    label = f"{sender._meta.app_label}.{sender.__name__}"
    resource_type = AUDITED_MODELS.get(label, label.lower().replace(".", "_"))
    action = "create" if created else "update"
    new_data = _serialize_instance(instance)
    _write_audit(action, resource_type, instance.pk, new_data=new_data)


def handle_post_delete(sender, instance, **kwargs):
    label = f"{sender._meta.app_label}.{sender.__name__}"
    resource_type = AUDITED_MODELS.get(label, label.lower().replace(".", "_"))
    old_data = _serialize_instance(instance)
    _write_audit("delete", resource_type, instance.pk, old_data=old_data)


def register_audit_signals():
    """
    Call this to hook audit signals onto additional models (e.g., from emr app).
    Usage: register_audit_signals() in emr/apps.py ready()
    """
    from django.apps import apps as django_apps

    for model_label in AUDITED_MODELS:
        try:
            model = django_apps.get_model(model_label)
            post_save.connect(handle_post_save, sender=model, weak=False)
            post_delete.connect(handle_post_delete, sender=model, weak=False)
        except LookupError:
            pass  # App not yet loaded


# ─── TUSSCode cross-schema PROTECT ───────────────────────────────────────────
# PostgreSQL does not enforce FK integrity across schemas (public → tenant).
# This signal provides the application-layer PROTECT equivalent.


@receiver(pre_delete, sender="core.TUSSCode")
def protect_tuss_code_deletion(sender, instance, **kwargs):
    """Block deletion of a TUSSCode that is referenced by tenant data in any tenant.

    Covers billing references (TISSGuideItem, PriceTableItem) and clinical capture
    (emr.EncounterProcedure, emr.SurgicalProcedure) — a TUSS code used by any of
    them cannot be hard-deleted.
    """
    from django_tenants.utils import get_tenant_model, schema_context

    TenantModel = get_tenant_model()
    for tenant in TenantModel.objects.exclude(schema_name="public"):
        with schema_context(tenant.schema_name):
            from apps.billing.models import PriceTableItem, TISSGuideItem
            from apps.emr.models import EncounterProcedure, SurgicalProcedure

            if TISSGuideItem.objects.filter(tuss_code=instance).exists():
                raise ProtectedError(
                    f"TUSSCode {instance.code} is referenced by TISSGuideItem in "
                    f"schema '{tenant.schema_name}' and cannot be deleted.",
                    {instance},
                )
            if PriceTableItem.objects.filter(tuss_code=instance).exists():
                raise ProtectedError(
                    f"TUSSCode {instance.code} is referenced by PriceTableItem in "
                    f"schema '{tenant.schema_name}' and cannot be deleted.",
                    {instance},
                )
            if EncounterProcedure.objects.filter(tuss_code=instance).exists():
                raise ProtectedError(
                    f"TUSSCode {instance.code} is referenced by EncounterProcedure in "
                    f"schema '{tenant.schema_name}' and cannot be deleted.",
                    {instance},
                )
            if SurgicalProcedure.objects.filter(tuss_code=instance).exists():
                raise ProtectedError(
                    f"TUSSCode {instance.code} is referenced by SurgicalProcedure in "
                    f"schema '{tenant.schema_name}' and cannot be deleted.",
                    {instance},
                )


# ─── CID10Code cross-schema PROTECT (E1-T5) ──────────────────────────────────
# Same rationale as protect_tuss_code_deletion: PostgreSQL does not enforce FK
# integrity across schemas (public → tenant), so an application-layer PROTECT
# blocks deleting a CID-10 code referenced by clinical capture in any tenant.


@receiver(pre_delete, sender="core.CID10Code")
def protect_cid10_code_deletion(sender, instance, **kwargs):
    """Block deletion of a CID10Code referenced by tenant EMR data in any tenant.

    Covers ``emr.MedicalHistory.cid10`` (FK) and ``emr.SOAPNote.cid10`` (M2M via
    the ``SOAPNoteCID10`` through). Mirrors the EncounterProcedure→TUSSCode guard.
    """
    from django_tenants.utils import get_tenant_model, schema_context

    TenantModel = get_tenant_model()
    for tenant in TenantModel.objects.exclude(schema_name="public"):
        with schema_context(tenant.schema_name):
            from apps.emr.models import MedicalHistory, SOAPNoteCID10

            if MedicalHistory.objects.filter(cid10=instance).exists():
                raise ProtectedError(
                    f"CID10Code {instance.code} is referenced by MedicalHistory in "
                    f"schema '{tenant.schema_name}' and cannot be deleted.",
                    {instance},
                )
            if SOAPNoteCID10.objects.filter(cid10=instance).exists():
                raise ProtectedError(
                    f"CID10Code {instance.code} is referenced by SOAPNote in "
                    f"schema '{tenant.schema_name}' and cannot be deleted.",
                    {instance},
                )


# ─── AnvisaProduct cross-schema PROTECT (E3-T2) ──────────────────────────────
# Same rationale as protect_cid10_code_deletion: PostgreSQL does not enforce FK
# integrity across schemas (public → tenant), so an application-layer PROTECT
# blocks deleting an ANVISA catalog product referenced by tenant pharmacy data.


@receiver(pre_delete, sender="core.AnvisaProduct")
def protect_anvisa_product_deletion(sender, instance, **kwargs):
    """Block deletion of an AnvisaProduct referenced by tenant pharmacy data.

    Covers ``pharmacy.Drug.anvisa_product`` (FK) in every tenant. Mirrors the
    MedicalHistory→CID10Code guard.
    """
    from django_tenants.utils import get_tenant_model, schema_context

    TenantModel = get_tenant_model()
    for tenant in TenantModel.objects.exclude(schema_name="public"):
        with schema_context(tenant.schema_name):
            from apps.pharmacy.models import Drug

            if Drug.objects.filter(anvisa_product=instance).exists():
                raise ProtectedError(
                    f"AnvisaProduct {instance.code} is referenced by Drug in "
                    f"schema '{tenant.schema_name}' and cannot be deleted.",
                    {instance},
                )


# ─── CBOCode cross-schema PROTECT (M2-S1-T3) ─────────────────────────────────
@receiver(pre_delete, sender="core.CBOCode")
def protect_cbo_code_deletion(sender, instance, **kwargs):
    """Block deletion of a CBOCode referenced by tenant data in any tenant.

    Covers ``emr.Professional.cbo`` (M2-S1) and the SUS production lines
    ``billing.BpaConsolidado.cbo`` / ``billing.BpaIndividualizado.cbo`` (S2).
    """
    from django_tenants.utils import get_tenant_model, schema_context

    TenantModel = get_tenant_model()
    for tenant in TenantModel.objects.exclude(schema_name="public"):
        with schema_context(tenant.schema_name):
            from apps.billing.sus_models import BpaConsolidado, BpaIndividualizado
            from apps.emr.models import Professional

            if Professional.objects.filter(cbo=instance).exists():
                raise ProtectedError(
                    f"CBOCode {instance.code} is referenced by Professional in "
                    f"schema '{tenant.schema_name}' and cannot be deleted.",
                    {instance},
                )
            if BpaConsolidado.objects.filter(cbo=instance).exists():
                raise ProtectedError(
                    f"CBOCode {instance.code} is referenced by BpaConsolidado in "
                    f"schema '{tenant.schema_name}' and cannot be deleted.",
                    {instance},
                )
            if BpaIndividualizado.objects.filter(cbo=instance).exists():
                raise ProtectedError(
                    f"CBOCode {instance.code} is referenced by BpaIndividualizado in "
                    f"schema '{tenant.schema_name}' and cannot be deleted.",
                    {instance},
                )


# ─── SIGTAPProcedure cross-schema PROTECT (Faturamento SUS S2) ────────────────
# Same rationale as protect_tuss_code_deletion: PostgreSQL does not enforce FK
# integrity across schemas (tenant → public), so an application-layer PROTECT
# blocks deleting a SIGTAP procedure referenced by tenant SUS production / clinical
# capture in any tenant.


@receiver(pre_delete, sender="core.SIGTAPProcedure")
def protect_sigtap_procedure_deletion(sender, instance, **kwargs):
    """Block deletion of a SIGTAPProcedure referenced by tenant SUS data in any tenant.

    Covers the SUS production lines ``billing.BpaConsolidado.sigtap`` /
    ``billing.BpaIndividualizado.sigtap``, the APAC authorizations
    ``billing.ApacAutorizacao.procedimento_principal`` /
    ``billing.ApacProcedimentoSecundario.sigtap`` (S3), and the SUS coding of a
    captured procedure ``emr.EncounterProcedure.sigtap``. Mirrors the
    EncounterProcedure→TUSSCode guard.
    """
    from django_tenants.utils import get_tenant_model, schema_context

    TenantModel = get_tenant_model()
    for tenant in TenantModel.objects.exclude(schema_name="public"):
        with schema_context(tenant.schema_name):
            from apps.billing.sus_models import (
                ApacAutorizacao,
                ApacProcedimentoSecundario,
                BpaConsolidado,
                BpaIndividualizado,
            )
            from apps.emr.models import EncounterProcedure

            if BpaConsolidado.objects.filter(sigtap=instance).exists():
                raise ProtectedError(
                    f"SIGTAPProcedure {instance.code} is referenced by BpaConsolidado in "
                    f"schema '{tenant.schema_name}' and cannot be deleted.",
                    {instance},
                )
            if BpaIndividualizado.objects.filter(sigtap=instance).exists():
                raise ProtectedError(
                    f"SIGTAPProcedure {instance.code} is referenced by BpaIndividualizado in "
                    f"schema '{tenant.schema_name}' and cannot be deleted.",
                    {instance},
                )
            if ApacAutorizacao.objects.filter(procedimento_principal=instance).exists():
                raise ProtectedError(
                    f"SIGTAPProcedure {instance.code} is referenced by ApacAutorizacao in "
                    f"schema '{tenant.schema_name}' and cannot be deleted.",
                    {instance},
                )
            if ApacProcedimentoSecundario.objects.filter(sigtap=instance).exists():
                raise ProtectedError(
                    f"SIGTAPProcedure {instance.code} is referenced by ApacProcedimentoSecundario "
                    f"in schema '{tenant.schema_name}' and cannot be deleted.",
                    {instance},
                )
            if EncounterProcedure.objects.filter(sigtap=instance).exists():
                raise ProtectedError(
                    f"SIGTAPProcedure {instance.code} is referenced by EncounterProcedure in "
                    f"schema '{tenant.schema_name}' and cannot be deleted.",
                    {instance},
                )


# ─── CNESEstablishment cross-schema PROTECT (M2-S1-T3) ───────────────────────
@receiver(pre_delete, sender="core.CNESEstablishment")
def protect_cnes_establishment_deletion(sender, instance, **kwargs):
    """Block deletion of a CNESEstablishment referenced by Professional.cnes or Facility.cnes."""
    from django_tenants.utils import get_tenant_model, schema_context

    TenantModel = get_tenant_model()
    for tenant in TenantModel.objects.exclude(schema_name="public"):
        with schema_context(tenant.schema_name):
            from apps.emr.models import Professional
            from apps.organization.models import Facility

            if Professional.objects.filter(cnes=instance).exists():
                raise ProtectedError(
                    f"CNESEstablishment {instance.code} is referenced by Professional in "
                    f"schema '{tenant.schema_name}' and cannot be deleted.",
                    {instance},
                )
            if Facility.objects.filter(cnes=instance).exists():
                raise ProtectedError(
                    f"CNESEstablishment {instance.code} is referenced by Facility in "
                    f"schema '{tenant.schema_name}' and cannot be deleted.",
                    {instance},
                )


# ─── LoincCode cross-schema PROTECT (M2-S3-T2) ───────────────────────────────
@receiver(pre_delete, sender="core.LoincCode")
def protect_loinc_code_deletion(sender, instance, **kwargs):
    """Block deletion of a LoincCode referenced by ``emr.LabTest.loinc`` in any tenant."""
    from django_tenants.utils import get_tenant_model, schema_context

    TenantModel = get_tenant_model()
    for tenant in TenantModel.objects.exclude(schema_name="public"):
        with schema_context(tenant.schema_name):
            from apps.emr.models import LabTest

            if LabTest.objects.filter(loinc=instance).exists():
                raise ProtectedError(
                    f"LoincCode {instance.code} is referenced by LabTest in "
                    f"schema '{tenant.schema_name}' and cannot be deleted.",
                    {instance},
                )


# ─── Nursing taxonomies cross-schema PROTECT (N2 — SAE domain wired) ──────────
# N2 wires the tenant-side SAE domain (apps.emr.sae_models): NursingDiagnosis.nanda
# → core.NandaDiagnosis, NursingCareplan.noc → core.NocOutcome, and
# NursingCareplanIntervention.nic → core.NicIntervention. PostgreSQL does not
# enforce FK integrity across schemas (tenant → public), so — exactly like
# protect_cbo_code_deletion — these application-layer guards block hard-deleting a
# catalog row any tenant references.


@receiver(pre_delete, sender="core.NandaDiagnosis")
def protect_nanda_diagnosis_deletion(sender, instance, **kwargs):
    """Block deletion of a NandaDiagnosis referenced by ``emr.NursingDiagnosis.nanda`` in any tenant."""
    from django_tenants.utils import get_tenant_model, schema_context

    TenantModel = get_tenant_model()
    for tenant in TenantModel.objects.exclude(schema_name="public"):
        with schema_context(tenant.schema_name):
            from apps.emr.models import NursingDiagnosis

            if NursingDiagnosis.objects.filter(nanda=instance).exists():
                raise ProtectedError(
                    f"NandaDiagnosis {instance.code} is referenced by NursingDiagnosis in "
                    f"schema '{tenant.schema_name}' and cannot be deleted.",
                    {instance},
                )


@receiver(pre_delete, sender="core.NicIntervention")
def protect_nic_intervention_deletion(sender, instance, **kwargs):
    """Block deletion of a NicIntervention referenced by ``emr.NursingCareplanIntervention.nic``."""
    from django_tenants.utils import get_tenant_model, schema_context

    TenantModel = get_tenant_model()
    for tenant in TenantModel.objects.exclude(schema_name="public"):
        with schema_context(tenant.schema_name):
            from apps.emr.models import NursingCareplanIntervention

            if NursingCareplanIntervention.objects.filter(nic=instance).exists():
                raise ProtectedError(
                    f"NicIntervention {instance.code} is referenced by NursingCareplanIntervention "
                    f"in schema '{tenant.schema_name}' and cannot be deleted.",
                    {instance},
                )


@receiver(pre_delete, sender="core.NocOutcome")
def protect_noc_outcome_deletion(sender, instance, **kwargs):
    """Block deletion of a NocOutcome referenced by ``emr.NursingCareplan.noc`` in any tenant."""
    from django_tenants.utils import get_tenant_model, schema_context

    TenantModel = get_tenant_model()
    for tenant in TenantModel.objects.exclude(schema_name="public"):
        with schema_context(tenant.schema_name):
            from apps.emr.models import NursingCareplan

            if NursingCareplan.objects.filter(noc=instance).exists():
                raise ProtectedError(
                    f"NocOutcome {instance.code} is referenced by NursingCareplan in "
                    f"schema '{tenant.schema_name}' and cannot be deleted.",
                    {instance},
                )


# ─── BedType cross-schema PROTECT (L1 — ADT/Leitos structure wired) ───────────
# L1 wires the tenant-side bed hierarchy (apps.emr.adt_models): Bed.bed_type and
# InpatientUnit.default_bed_type → core.BedType. PostgreSQL does not enforce FK
# integrity across schemas (tenant → public), so — exactly like
# protect_nanda_diagnosis_deletion — this application-layer guard blocks
# hard-deleting a bed type any tenant references.


@receiver(pre_delete, sender="core.BedType")
def protect_bed_type_deletion(sender, instance, **kwargs):
    """Block deletion of a BedType referenced by tenant bed structure in any tenant.

    Covers ``emr.Bed.bed_type`` (FK) and ``emr.InpatientUnit.default_bed_type``
    (FK). Mirrors the NursingDiagnosis→NandaDiagnosis guard.
    """
    from django_tenants.utils import get_tenant_model, schema_context

    TenantModel = get_tenant_model()
    for tenant in TenantModel.objects.exclude(schema_name="public"):
        with schema_context(tenant.schema_name):
            from apps.emr.models import Bed, InpatientUnit

            if Bed.objects.filter(bed_type=instance).exists():
                raise ProtectedError(
                    f"BedType {instance.code} is referenced by Bed in "
                    f"schema '{tenant.schema_name}' and cannot be deleted.",
                    {instance},
                )
            if InpatientUnit.objects.filter(default_bed_type=instance).exists():
                raise ProtectedError(
                    f"BedType {instance.code} is referenced by InpatientUnit in "
                    f"schema '{tenant.schema_name}' and cannot be deleted.",
                    {instance},
                )


# ─── BloodComponentCatalog cross-schema PROTECT (H1 — Banco de Sangue wired) ──
# H1 wires the tenant-side blood stock (apps.emr.bloodbank_models): BloodBag.component
# → core.BloodComponentCatalog. PostgreSQL does not enforce FK integrity across
# schemas (tenant → public), so — exactly like protect_bed_type_deletion — this
# application-layer guard blocks hard-deleting a hemocomponente any tenant references.


@receiver(pre_delete, sender="core.BloodComponentCatalog")
def protect_blood_component_deletion(sender, instance, **kwargs):
    """Block deletion of a BloodComponentCatalog referenced by tenant blood stock.

    Covers ``emr.BloodBag.component`` (H1) and ``emr.TransfusionRequest.component``
    (H3), both as FKs in every tenant. Mirrors the Bed→BedType guard.
    """
    from django_tenants.utils import get_tenant_model, schema_context

    TenantModel = get_tenant_model()
    for tenant in TenantModel.objects.exclude(schema_name="public"):
        with schema_context(tenant.schema_name):
            from apps.emr.models import BloodBag, TransfusionRequest

            if BloodBag.objects.filter(component=instance).exists():
                raise ProtectedError(
                    f"BloodComponentCatalog {instance.code} is referenced by BloodBag in "
                    f"schema '{tenant.schema_name}' and cannot be deleted.",
                    {instance},
                )
            if TransfusionRequest.objects.filter(component=instance).exists():
                raise ProtectedError(
                    f"BloodComponentCatalog {instance.code} is referenced by "
                    f"TransfusionRequest in schema '{tenant.schema_name}' and cannot be deleted.",
                    {instance},
                )


# ─── Manchester catalog cross-schema PROTECT (E2 — PS/Emergência wired) ───────
# E2 wires the tenant-side PS/Emergência domain (apps.emr.emergency_models):
# RiskClassification.flowchart → core.ManchesterFlowchart and
# RiskClassification.discriminator → core.ManchesterDiscriminator. PostgreSQL does
# not enforce FK integrity across schemas (tenant → public), so — exactly like
# protect_bed_type_deletion — these application-layer guards block hard-deleting a
# governed catalog row any tenant references from a risk classification.


@receiver(pre_delete, sender="core.ManchesterFlowchart")
def protect_manchester_flowchart_deletion(sender, instance, **kwargs):
    """Block deletion of a ManchesterFlowchart referenced by ``emr.RiskClassification`` in any tenant."""
    from django_tenants.utils import get_tenant_model, schema_context

    TenantModel = get_tenant_model()
    for tenant in TenantModel.objects.exclude(schema_name="public"):
        with schema_context(tenant.schema_name):
            from apps.emr.models import RiskClassification

            if RiskClassification.objects.filter(flowchart=instance).exists():
                raise ProtectedError(
                    f"ManchesterFlowchart {instance.code} is referenced by RiskClassification "
                    f"in schema '{tenant.schema_name}' and cannot be deleted.",
                    {instance},
                )


@receiver(pre_delete, sender="core.ManchesterDiscriminator")
def protect_manchester_discriminator_deletion(sender, instance, **kwargs):
    """Block deletion of a ManchesterDiscriminator referenced by ``emr.RiskClassification`` in any tenant."""
    from django_tenants.utils import get_tenant_model, schema_context

    TenantModel = get_tenant_model()
    for tenant in TenantModel.objects.exclude(schema_name="public"):
        with schema_context(tenant.schema_name):
            from apps.emr.models import RiskClassification

            if RiskClassification.objects.filter(discriminator=instance).exists():
                raise ProtectedError(
                    f"ManchesterDiscriminator {instance.code} is referenced by RiskClassification "
                    f"in schema '{tenant.schema_name}' and cannot be deleted.",
                    {instance},
                )


# ─── Tenant → TenantAIConfig + emr FeatureFlag ───────────────────────────────


@receiver(post_save, sender="core.Tenant")
def create_tenant_defaults_on_new_tenant(sender, instance, created, **kwargs):
    """
    On new tenant creation:
    1. Auto-create TenantAIConfig (all-disabled defaults — explicit state in Admin)
    2. Auto-create emr FeatureFlag (enabled) — every tenant gets EMR from day one,
       even before a Subscription is created. This prevents new tenants from being
       locked out of the core clinical workflow while Vitali sets up their plan.
    """
    if not created:
        return
    from apps.core.models import FeatureFlag, TenantAIConfig

    TenantAIConfig.objects.get_or_create(tenant=instance)
    FeatureFlag.objects.get_or_create(
        tenant=instance,
        module_key="emr",
        defaults={"is_enabled": True},
    )


# ─── Subscription → FeatureFlags ─────────────────────────────────────────────


@receiver(post_save, sender="core.Subscription")
def create_feature_flags_on_subscription(sender, instance, created, **kwargs):
    """Automatically enable FeatureFlags for the modules in a new subscription."""
    if not created:
        return

    from apps.core.models import FeatureFlag

    for module_key in instance.active_modules:
        FeatureFlag.objects.get_or_create(
            tenant=instance.tenant,
            module_key=module_key,
            defaults={"is_enabled": True},
        )

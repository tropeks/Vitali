"""Contract test — apps.core.mixins.AuditReadMixin coverage (Onda 3, item 3.3).

CFM Res. 1.821/2007 requires traceability of *access* to the electronic
record, not just changes. This walks every DRF viewset defined directly in
the clinical modules and asserts each one either:

* declares ``audit_resource_type`` while inheriting ``AuditReadMixin`` (reads
  are logged to the immutable ``AuditLog``), or
* is on the reviewed ``_EXEMPT`` allowlist below, with a one-line reason.

A new viewset that serves PHI and forgets the mixin fails this test by name.
A new viewset that genuinely carries no clinical content (equipment catalog,
accounting, procurement) must be added to ``_EXEMPT`` explicitly — that edit
is visible in code review, so "this doesn't carry PHI" becomes a reviewed
decision instead of a silent gap. This is the mechanism that keeps the read
audit from regressing the next time someone adds an endpoint.
"""

import importlib
import inspect

import pytest
from rest_framework import viewsets

from apps.core.mixins import AuditReadMixin

_MODULES = (
    "apps.emr.views",
    "apps.emr.views_adt",
    "apps.emr.views_bloodbank",
    "apps.emr.views_blood_donor",
    "apps.emr.views_diagnostics",
    "apps.emr.views_emergency",
    "apps.emr.views_lis",
    "apps.emr.views_microbiology",
    "apps.emr.views_pathology",
    "apps.emr.views_problems",
    "apps.emr.views_reconciliation",
    "apps.emr.views_sae",
    "apps.emr.views_surgery",
    "apps.emr.views_transfusion",
    "apps.emr.views_transfusion_admin",
    "apps.pharmacy.views",
    "apps.billing.views",
    "apps.imaging.views",
)

# Reviewed 2026-08 (Onda 3 / 3.3): no Patient FK, no clinical narrative — pure
# catalog, facility/equipment config, inventory/procurement, or accounting.
_EXEMPT = {
    "apps.emr.views.ProfessionalViewSet": "staff directory, not patient data",
    "apps.emr.views.ScheduleConfigViewSet": "professional's agenda config, not a record",
    "apps.emr.views.ClinicalFormTemplateViewSet": "form template/schema, not a filled record",
    "apps.emr.views.LabTestViewSet": "catalog of exam types, not a result",
    "apps.emr.views_adt.InpatientUnitViewSet": "facility structure",
    "apps.emr.views_adt.RoomViewSet": "facility structure",
    "apps.emr.views_adt.BedViewSet": "facility structure",
    "apps.emr.views_adt.BedStatusEventViewSet": "bed hygiene-cycle log, no patient FK",
    "apps.emr.views_bloodbank.BloodComponentViewSet": "hemocomponent catalog/inventory",
    "apps.emr.views_bloodbank.BloodBagViewSet": "physical stock, no patient FK yet (pre-transfusion)",
    "apps.emr.views_diagnostics.LabInstrumentViewSet": "lab equipment catalog",
    "apps.emr.views_reconciliation.OrderSetViewSet": "order-set template/catalog",
    "apps.emr.views_surgery.OperatingRoomViewSet": "facility structure",
    "apps.pharmacy.views.NFeReceiptViewSet": "supplier invoice ingestion, no patient link",
    "apps.pharmacy.views.SupplierContractViewSet": "procurement",
    "apps.pharmacy.views.SupplierInvoiceViewSet": "procurement",
    "apps.pharmacy.views.StockReceiptViewSet": "inventory receiving",
    "apps.pharmacy.views.ThreeWayMatchViewSet": "procurement reconciliation",
    "apps.pharmacy.views.WarehouseViewSet": "facility structure",
    "apps.pharmacy.views.StorageLocationViewSet": "facility structure",
    "apps.pharmacy.views.InventoryCountViewSet": "inventory",
    "apps.pharmacy.views.StockTransferViewSet": "inventory",
    "apps.pharmacy.views.LotRecallViewSet": "inventory/quality",
    "apps.pharmacy.views.DrugViewSet": "drug catalog",
    "apps.pharmacy.views.MaterialViewSet": "material catalog",
    "apps.pharmacy.views.StockItemViewSet": "inventory",
    "apps.pharmacy.views.StockMovementViewSet": "inventory ledger (patient-linked cases covered via SurgicalMaterialViewSet)",
    "apps.pharmacy.views.SupplierViewSet": "procurement",
    "apps.pharmacy.views.PurchaseOrderViewSet": "procurement",
    "apps.pharmacy.views.DoseRuleViewSet": "safety-engine catalog",
    "apps.pharmacy.views.AllergenClassViewSet": "catalog",
    "apps.pharmacy.views.DrugInteractionViewSet": "catalog",
    "apps.billing.views.ProfessionalSettlementViewSet": "professional payout, not clinical",
    "apps.billing.views.AccountsReceivableViewSet": "financial ledger, not clinical content",
    "apps.billing.views.AccountingCategoryViewSet": "accounting catalog",
    "apps.billing.views.AccountingEntryViewSet": "financial ledger",
    "apps.billing.views.BankTransactionViewSet": "financial reconciliation",
    "apps.billing.views.PayableViewSet": "financial ledger",
    "apps.billing.views.CashFlowEntryViewSet": "financial ledger",
    "apps.billing.views.TUSSCodeViewSet": "procedure-code catalog",
    "apps.billing.views.InsuranceProviderViewSet": "catalog",
    "apps.billing.views.PriceTableViewSet": "catalog",
    "apps.billing.views.InpatientFeeViewSet": "fee-schedule application, not clinical narrative",
    "apps.billing.views.TISSBatchViewSet": "batch container of many patients' guides, no single-record PHI view",
    "apps.imaging.views.ImagingModalityViewSet": "equipment catalog",
}


def _clinical_viewsets():
    found = []
    for path in _MODULES:
        module = importlib.import_module(path)
        for name, obj in vars(module).items():
            if (
                inspect.isclass(obj)
                and issubclass(obj, viewsets.GenericViewSet)
                and obj.__module__ == module.__name__
                and not name.startswith("_")
            ):
                found.append((f"{path}.{name}", obj))
    return found


@pytest.mark.parametrize(
    "qualname,cls", _clinical_viewsets(), ids=lambda x: x if isinstance(x, str) else ""
)
def test_clinical_viewset_audits_reads_or_is_exempt(qualname, cls):
    if qualname in _EXEMPT:
        pytest.skip(f"exempt: {_EXEMPT[qualname]}")
    assert issubclass(cls, AuditReadMixin), (
        f"{qualname} is not on the reviewed exempt allowlist and does not inherit "
        "AuditReadMixin — reads of it leave no trace in AuditLog (CFM 1.821/2007). "
        "Add AuditReadMixin + audit_resource_type, or add this viewset to _EXEMPT "
        "in this test with a one-line reason if it truly carries no PHI."
    )
    assert cls.audit_resource_type, (
        f"{qualname} inherits AuditReadMixin but never sets audit_resource_type "
        "— it will fall back to the class name, which is fine, but set it "
        "explicitly so the AuditLog trail is stable across refactors."
    )


def test_exempt_list_has_no_stale_entries():
    """Every _EXEMPT key must name a viewset that still exists — otherwise a
    rename/removal silently shrinks coverage instead of failing loudly."""
    known = {qualname for qualname, _ in _clinical_viewsets()}
    stale = set(_EXEMPT) - known
    assert not stale, f"_EXEMPT references viewsets that no longer exist: {stale}"

"""
Sprint M1-S2 — services for the controlled-substance escrituração book.

``ControlledLedgerBuilder`` reconstructs a period's book from the append-only
``StockMovement`` ledger (never mutates stock). ``ControlledLedgerClosingService``
signs and closes a period with maker-checker segregation and emits the
exportable escrituração report (SNGPC seed).
"""

from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from ..models import (
    ControlledLedgerClosing,
    ControlledSubstanceLedger,
    StockMovement,
)

# Permission a user's role must grant to sign/close a controlled book (RT/
# farmacêutico responsável). Mirrors pharmacy.clinical_validate on
# PharmacistValidation.
CLOSE_PERMISSION = "pharmacy.controlled_book_sign"


def _presentation(drug):
    parts = [p for p in (drug.dosage_form, drug.concentration) if p]
    return " ".join(parts).strip()


class ControlledLedgerBuilder:
    """Reconstructs a ``ControlledSubstanceLedger`` from the movement ledger."""

    @staticmethod
    @transaction.atomic
    def build(*, drug, period_start, period_end, actor=None, opening_balance=None):
        if not drug.is_controlled:
            raise ValidationError(
                "Somente medicamentos controlados (Portaria 344) são escriturados."
            )
        if period_end < period_start:
            raise ValidationError("period_end não pode ser anterior a period_start.")

        # A signed closing freezes the period — no rebuild allowed.
        existing = (
            ControlledSubstanceLedger.objects.filter(
                drug=drug, period_start=period_start, period_end=period_end
            )
            .select_related("closing")
            .first()
        )
        if existing is not None and existing.is_closed:
            raise ValidationError("Período já fechado e assinado — o livro é imutável.")
        if existing is not None:
            # Open book being re-run: discard the stale open snapshot and rebuild
            # (delete() is guarded, so drop via queryset — allowed while open).
            ControlledSubstanceLedger.objects.filter(pk=existing.pk).delete()

        movements = StockMovement.objects.filter(stock_item__drug=drug)

        # Opening = running total strictly before the period (unless overridden).
        if opening_balance is None:
            opening_balance = movements.filter(created_at__date__lt=period_start).aggregate(
                s=Sum("quantity")
            )["s"] or Decimal("0")

        in_period = movements.filter(
            created_at__date__gte=period_start, created_at__date__lte=period_end
        )
        entries = in_period.filter(quantity__gt=0).aggregate(s=Sum("quantity"))["s"] or Decimal("0")
        exits_signed = in_period.filter(quantity__lt=0).aggregate(s=Sum("quantity"))[
            "s"
        ] or Decimal("0")
        exits = -exits_signed  # store as a positive magnitude
        closing_balance = opening_balance + entries - exits

        return ControlledSubstanceLedger.objects.create(
            drug=drug,
            controlled_class=drug.controlled_class,
            presentation=_presentation(drug),
            period_start=period_start,
            period_end=period_end,
            opening_balance=opening_balance,
            total_entries=entries,
            total_exits=exits,
            closing_balance=closing_balance,
            built_by=actor,
        )


class ControlledLedgerClosingService:
    """Signed period closing with maker-checker segregation + escrituração report."""

    @staticmethod
    @transaction.atomic
    def close(*, ledger, signer, checked_balance, signature_hash=""):
        # Lock the book row so two signers cannot race a double-close.
        ledger = ControlledSubstanceLedger.objects.select_for_update().get(pk=ledger.pk)

        if ControlledLedgerClosing.objects.filter(ledger=ledger).exists():
            raise ValidationError("Este período já foi fechado.")

        # Signer must be an RT/farmacêutico.
        if not signer.has_role_permission(CLOSE_PERMISSION):
            raise PermissionDenied(
                f"O fechamento exige um farmacêutico/RT com permissão {CLOSE_PERMISSION}."
            )

        # Maker-checker: quem montou o livro não pode assiná-lo.
        if ledger.built_by_id is not None and ledger.built_by_id == signer.pk:
            raise PermissionDenied(
                "Maker-checker: quem reconstruiu o livro não pode assinar o "
                "fechamento (dupla conferência)."
            )

        return ControlledLedgerClosing.objects.create(
            ledger=ledger,
            checked_balance=checked_balance,
            signed_by=signer,
            signature_hash=signature_hash,
            closed_at=timezone.now(),
        )

    @staticmethod
    def export_report(closing):
        """Structured escrituração report — SNGPC seed data.

        Returns a JSON-serialisable dict reflecting the reconciled book balances,
        the RT's checked balance, the signature, and per-movement detail lines
        for the period (the granularity SNGPC transmission needs).
        """
        ledger = closing.ledger
        drug = ledger.drug
        signer = closing.signed_by

        period_movements = (
            StockMovement.objects.filter(stock_item__drug=drug)
            .filter(
                Q(created_at__date__gte=ledger.period_start)
                & Q(created_at__date__lte=ledger.period_end)
            )
            .select_related("stock_item")
            .order_by("created_at")
        )

        return {
            "ledger_id": str(ledger.id),
            "drug": {"id": str(drug.id), "name": drug.name},
            "controlled_class": ledger.controlled_class,
            "presentation": ledger.presentation,
            "period": {
                "start": ledger.period_start.isoformat(),
                "end": ledger.period_end.isoformat(),
            },
            "opening_balance": str(ledger.opening_balance),
            "total_entries": str(ledger.total_entries),
            "total_exits": str(ledger.total_exits),
            "closing_balance": str(ledger.closing_balance),
            "checked_balance": str(closing.checked_balance),
            "reconciles": closing.reconciles,
            "divergence": str(closing.divergence),
            "signer": {
                "id": str(signer.id),
                "email": signer.email,
                "name": getattr(signer, "full_name", "") or "",
            },
            "signature_hash": closing.signature_hash,
            "closed_at": closing.closed_at.isoformat(),
            "movements": [
                {
                    "id": str(m.id),
                    "type": m.movement_type,
                    "quantity": str(m.quantity),
                    "lot": m.stock_item.lot_number,
                    "reference": m.reference,
                    "at": m.created_at.isoformat(),
                }
                for m in period_movements
            ],
        }

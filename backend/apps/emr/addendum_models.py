"""Sprint E6 — Adendo pós-assinatura (CFM Res. 1.821/2007 + 2.299/2021).

A signed clinical document (``Encounter`` or ``ClinicalDocument``) is
IMMUTABLE. Corrections/complements happen via an APPENDED ``EncounterAddendum``
that references the signed target — never by editing the original.

Design notes:
  - Polymorphic target reference mirrors the existing
    ``apps.signatures.models.DigitalSignature`` pattern (``document_type`` +
    ``document_id`` string pair) rather than Django's ``contenttypes``
    framework, which nothing else in this codebase uses yet. ``target_type``
    + ``target_id`` identify the signed row; ``target`` resolves it lazily.
  - Append-only: ``save()`` rejects any UPDATE (mirrors
    ``pharmacy.StockMovement``); ``delete()`` always raises. The original
    document's row is only ever READ (to check ``signed_at``), never written.
  - Ordered chain: ``sequence`` (1-based, per target) + ``previous_addendum``
    (self-FK to the immediately preceding addendum, ``null`` for the first
    addendum in the chain — which references the original document directly
    via ``target_type``/``target_id``). Both are assigned atomically inside
    ``save()`` under a row lock on the target so concurrent creates cannot
    race onto the same sequence number.
"""

import uuid

from django.db import models, transaction
from encrypted_model_fields.fields import EncryptedTextField


class EncounterAddendumManager(models.Manager):
    def create_addendum(self, *, target, author, reason, body, **extra):
        """Convenience constructor: derive target_type/target_id from `target`.

        `extra` may carry the optional own-signature fields (signed_at,
        signed_by, signature_hash, is_icp_brasil) — set once, at creation,
        since the row is append-only afterwards.
        """
        addendum = self.model(
            target_type=self.model.target_type_for(target),
            target_id=str(target.pk),
            author=author,
            reason=reason,
            body=body,
            **extra,
        )
        addendum.save()
        return addendum

    def for_target(self, target):
        """Return the ordered addendum chain for `target` (oldest first)."""
        return self.filter(
            target_type=self.model.target_type_for(target),
            target_id=str(target.pk),
        ).order_by("sequence")


class EncounterAddendum(models.Model):
    """Append-only correction/complement attached to an already-signed
    clinical document.

    CFM compliance: the original is preserved byte-identical (we never write
    to it); the addendum carries its own author, reason, and timestamp, and
    an optional signature of its own. The chain is ordered and each entry
    references the prior entry (or the original document, for the first
    entry in the chain).
    """

    TARGET_ENCOUNTER = "encounter"
    TARGET_CLINICAL_DOCUMENT = "clinical_document"
    TARGET_TYPE_CHOICES = [
        (TARGET_ENCOUNTER, "Encounter"),
        (TARGET_CLINICAL_DOCUMENT, "ClinicalDocument"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Polymorphic reference to the signed document being addended — see
    # module docstring for why this mirrors DigitalSignature instead of
    # using django.contrib.contenttypes.
    target_type = models.CharField(max_length=20, choices=TARGET_TYPE_CHOICES)
    target_id = models.CharField(max_length=64)

    sequence = models.PositiveIntegerField(editable=False)
    previous_addendum = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="next_addenda",
        editable=False,
    )

    author = models.ForeignKey(
        "core.User", on_delete=models.PROTECT, related_name="encounter_addenda"
    )
    reason = EncryptedTextField(help_text="Motivo da correção/complemento (LGPD)")
    body = EncryptedTextField(help_text="Conteúdo do adendo (LGPD)")

    # Optional own signature — mirrors ClinicalDocument's signing fields.
    # Set only at creation time (never mutated afterwards — see save()).
    signed_at = models.DateTimeField(null=True, blank=True)
    signed_by = models.ForeignKey(
        "core.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="signed_addenda",
    )
    signature_hash = models.CharField(max_length=128, blank=True)
    is_icp_brasil = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    objects = EncounterAddendumManager()

    class Meta:
        ordering = ["target_type", "target_id", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["target_type", "target_id", "sequence"],
                name="emr_addendum_unique_sequence_per_target",
            )
        ]
        indexes = [
            models.Index(fields=["target_type", "target_id"]),
        ]

    def __str__(self):
        return f"Adendo #{self.sequence} — {self.target_type}:{self.target_id}"

    @property
    def is_signed(self):
        return self.signed_at is not None

    @staticmethod
    def target_type_for(target):
        """Map a model instance to its `target_type` discriminator."""
        from .models import ClinicalDocument, Encounter

        if isinstance(target, Encounter):
            return EncounterAddendum.TARGET_ENCOUNTER
        if isinstance(target, ClinicalDocument):
            return EncounterAddendum.TARGET_CLINICAL_DOCUMENT
        raise ValueError(f"Tipo de documento não suporta adendo: {type(target).__name__}")

    def _resolve_target_model(self):
        from .models import ClinicalDocument, Encounter

        mapping = {
            self.TARGET_ENCOUNTER: Encounter,
            self.TARGET_CLINICAL_DOCUMENT: ClinicalDocument,
        }
        try:
            return mapping[self.target_type]
        except KeyError as exc:
            raise ValueError(f"Tipo de documento inválido: {self.target_type!r}") from exc

    @property
    def target(self):
        """Resolve the referenced document. Read-only convenience accessor —
        never used to write back to the original."""
        model_class = self._resolve_target_model()
        return model_class.objects.filter(pk=self.target_id).first()

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("EncounterAddendum entries are immutable — create a new one instead.")

        model_class = self._resolve_target_model()

        with transaction.atomic():
            # Lock the target row for the duration of the chain-append so
            # concurrent addendum creates on the same document serialize
            # (also guards the very first addendum, where there is no prior
            # EncounterAddendum row yet to lock on).
            try:
                target = model_class.objects.select_for_update().get(pk=self.target_id)
            except model_class.DoesNotExist as exc:
                raise ValueError("Documento alvo do adendo não encontrado.") from exc

            if getattr(target, "signed_at", None) is None:
                raise ValueError(
                    "Só é possível criar adendo em um documento assinado (requisito CFM)."
                )

            prior = (
                EncounterAddendum.objects.select_for_update()
                .filter(target_type=self.target_type, target_id=self.target_id)
                .order_by("-sequence")
                .first()
            )
            self.sequence = (prior.sequence + 1) if prior else 1
            self.previous_addendum = prior

            # NOTE: `target` above is only ever read — nothing on it is
            # mutated or saved, which is what keeps the original document
            # byte-identical after an addendum is appended.
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("EncounterAddendum entries cannot be deleted — append-only chain.")

"""
Billing — Internação: ponte para diárias de leito (Sprint B2)
=============================================================
Per-tenant inpatient billing models, kept in a dedicated module (imported at the
end of ``apps/billing/models.py``) so the internação bridge integrates as an
additive leaf — exactly like ``sus_models`` / ``revenue_models`` — without
churning the TISS billing file.

Domínio
-------
Uma :class:`~apps.emr.adt_models.Admission` (internação) deve **acumular diárias
de leito** faturáveis por dia de estada. Hoje a estada morre sem virar receita;
este módulo modela o ACÚMULO. A montagem da guia TISS de internação a partir
dessas diárias é o Sprint B3 (fora do escopo aqui).

Como o preço da diária é resolvido
----------------------------------
``core.BedType`` é um catálogo CLÍNICO (CNES): tem ``code``/``display``/
``category``, mas **não tem preço nem TUSS**. Por isso o preço da diária tem de
vir de um mapeamento tenant-configurável tipo-de-leito → TUSS de diária, e o TUSS
é então precificado (no B3) pela ``PriceTable`` do convênio — o mesmo caminho de
precificação dos bridges de laboratório e cirurgia. :class:`AccommodationTuss` é
esse mapeamento; :class:`DailyCharge` é o acúmulo idempotente por dia.

Cross-schema FK note
--------------------
``core.TUSSCode`` vive no schema PUBLIC/SHARED. PostgreSQL não impõe integridade
de FK entre schemas (tenant → public), então — exatamente como
``emr.SurgicalProcedure.tuss_code`` — os FKs ``tuss_code`` usam
``on_delete=DO_NOTHING`` e confiam no signal ``protect_tuss_code_deletion``
(apps/core/signals.py) para bloquear apagar um código de diária que qualquer
tenant referencie.
"""

from __future__ import annotations

import uuid

from django.db import models


class AccommodationTuss(models.Model):
    """Mapeia um tipo de leito (``core.BedType.code``) a um código TUSS de diária.

    Configuração por tenant e fonte do TUSS que precifica a diária de um leito.
    Ao acumular, o serviço lê ``Bed.bed_type_code`` da internação e procura o
    ``AccommodationTuss`` ativo correspondente para saber qual TUSS cobrar.
    ``unique`` em ``bed_type_code`` — no máximo um TUSS de diária por tipo de leito.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Casa com core.BedType.code (max_length=32 no TerminologyCatalog) e com o
    # accessor Bed.bed_type_code. String natural key, não FK: o catálogo BedType é
    # clínico/SHARED e o mapeamento é puramente financeiro/tenant.
    bed_type_code = models.CharField(
        "Código do tipo de leito",
        max_length=32,
        help_text="Código do tipo de leito (core.BedType.code) a ser cobrado como diária.",
    )
    # FK cross-schema para o TUSSCode PUBLIC: DO_NOTHING + protect_tuss_code_deletion,
    # espelhando emr.SurgicalProcedure.tuss_code (PROTECT quebraria o Collector
    # de deleção cross-schema).
    tuss_code = models.ForeignKey(
        "core.TUSSCode",
        on_delete=models.DO_NOTHING,
        related_name="accommodation_mappings",
        verbose_name="TUSS da diária",
    )
    active = models.BooleanField("Ativo", default=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["bed_type_code"]
        verbose_name = "Mapeamento de diária (tipo de leito → TUSS)"
        verbose_name_plural = "Mapeamentos de diária (tipo de leito → TUSS)"
        constraints = [
            models.UniqueConstraint(
                fields=["bed_type_code"],
                name="uniq_accommodation_tuss_per_bed_type",
            ),
        ]

    def __str__(self):
        return f"{self.bed_type_code} → TUSS {self.tuss_code_id}"


class DailyCharge(models.Model):
    """Uma diária de leito acumulada para uma internação num dado dia.

    Acúmulo faturável (por tenant). A ``UniqueConstraint(admission, service_date)``
    garante **no máximo uma diária por dia por internação** = idempotência do
    serviço de acúmulo. ``bed_type_code`` é um **snapshot** do tipo de leito
    cobrado naquele dia (registro estável mesmo que o leito/tipo mude depois — e
    mesmo depois de a alta liberar ``Admission.current_bed``).

    Nota de precificação (B3): NÃO snapshotamos ``unit_value`` aqui. A diária é
    precificada pela ``PriceTable`` do convênio no momento em que o B3 monta a
    guia TISS de internação (mesmo padrão dos bridges de laboratório/cirurgia,
    que precificam na criação da guia, não na captura clínica). ``DailyCharge``
    carrega só o TUSS + quantidade; o valor é resolvido a jusante.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    admission = models.ForeignKey(
        "emr.Admission",
        on_delete=models.PROTECT,
        related_name="daily_charges",
        verbose_name="Internação",
    )
    service_date = models.DateField("Data da diária", db_index=True)
    # FK cross-schema para o TUSSCode PUBLIC: DO_NOTHING + protect_tuss_code_deletion.
    tuss_code = models.ForeignKey(
        "core.TUSSCode",
        on_delete=models.DO_NOTHING,
        related_name="daily_charges",
        verbose_name="TUSS da diária",
    )
    bed_type_code = models.CharField(
        "Tipo de leito (snapshot)",
        max_length=32,
        help_text="Snapshot do código do tipo de leito cobrado nesta diária.",
    )
    quantity = models.PositiveIntegerField("Quantidade", default=1)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["admission", "service_date"]
        verbose_name = "Diária de leito"
        verbose_name_plural = "Diárias de leito"
        constraints = [
            models.UniqueConstraint(
                fields=["admission", "service_date"],
                name="uniq_daily_charge_per_admission_day",
            ),
        ]
        indexes = [
            models.Index(fields=["admission", "service_date"], name="bill_dailych_adm_date_idx"),
        ]

    def __str__(self):
        return f"Diária {self.service_date} — internação {self.admission_id}"


class InpatientFee(models.Model):
    """Uma taxa ou gás medicinal lançado numa internação (B6).

    A diária de leito era a única coisa que uma estada gerava, mas na conta
    hospitalar ela é minoria: das 3.595 linhas da tabela TUSS 18, ~1.590 são TAXA
    (incubadora, almofada, equipamento) e ~890 são gases medicinais. Sem elas a
    guia de internação sai sistematicamente subfaturada.

    Por que um model separado de :class:`DailyCharge`, e não um campo a mais:

    * a diária é única por dia (``UniqueConstraint(admission, service_date)``);
      taxa não é — no mesmo dia cabem incubadora, oxigênio e bomba de infusão;
    * a taxa carrega **unidade temporal própria**, porque o TUSS 18 codifica a
      unidade no próprio termo ("TAXA DE INCUBADORA, POR DIA" é um código
      diferente de "…COM OXIGÊNIO, POR HORA"). Guardar ``quantity`` sem ``unit``
      seria guardar um número sem significado.

    Precificação segue a mesma regra da diária: NÃO se snapshota ``unit_value``.
    O valor sai da ``PriceTable`` do convênio quando a guia é montada. O que se
    snapshota é a ``description``, porque o catálogo é reimportável e o texto do
    termo pode mudar debaixo de um lançamento já feito.
    """

    class Unit(models.TextChoices):
        DIA = "dia", "Por dia"
        HORA = "hora", "Por hora"
        UNIDADE = "unidade", "Por unidade"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    admission = models.ForeignKey(
        "emr.Admission",
        on_delete=models.PROTECT,
        related_name="inpatient_fees",
        verbose_name="Internação",
    )
    service_date = models.DateField("Data do lançamento", db_index=True)
    # FK cross-schema para o TUSSCode PUBLIC: DO_NOTHING + protect_tuss_code_deletion,
    # espelhando DailyCharge (PROTECT quebraria o Collector de deleção cross-schema).
    tuss_code = models.ForeignKey(
        "core.TUSSCode",
        on_delete=models.DO_NOTHING,
        related_name="inpatient_fees",
        verbose_name="TUSS da taxa",
    )
    description = models.CharField(
        "Descrição (snapshot)",
        max_length=500,
        blank=True,
        default="",
        help_text="Texto do termo TUSS no momento do lançamento.",
    )
    quantity = models.DecimalField(
        "Quantidade",
        max_digits=10,
        decimal_places=2,
        help_text="Quantidade na unidade declarada (ex.: 6,5 horas de oxigênio).",
    )
    unit = models.CharField(
        "Unidade",
        max_length=10,
        choices=Unit.choices,
        default=Unit.UNIDADE,
        help_text="Unidade de cobrança do termo TUSS (por dia / por hora / por unidade).",
    )
    notes = models.CharField("Observação", max_length=500, blank=True, default="")
    created_by = models.ForeignKey(
        "core.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Lançado por",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["admission", "service_date"]
        verbose_name = "Taxa de internação"
        verbose_name_plural = "Taxas de internação"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="inpatient_fee_quantity_positive",
            ),
        ]
        indexes = [
            models.Index(fields=["admission", "service_date"], name="bill_inpfee_adm_date_idx"),
        ]

    def __str__(self):
        return (
            f"{self.description[:40]} ×{self.quantity} {self.unit} — internação {self.admission_id}"
        )

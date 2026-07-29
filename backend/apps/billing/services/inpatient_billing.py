"""
B2 — Admission → diárias de leito (acúmulo faturável).
======================================================
``accrue_daily_charges`` percorre a janela de estada de uma
:class:`~apps.emr.adt_models.Admission` e materializa uma :class:`DailyCharge`
por dia faturável, resolvendo o TUSS da diária a partir do tipo de leito atual
via :class:`AccommodationTuss`. É o ACÚMULO; a montagem da guia TISS de
internação a partir dessas diárias é o Sprint B3.

Regra de contagem TISS de diárias (= pernoites)
-----------------------------------------------
Diária de leito é *pernoite*: cobra-se o **dia da admissão** e **cada dia
subsequente**, mas **NÃO se cobra o dia da alta**. Formalmente, para uma
internação com alta:

    janela faturável = [admission_date, discharge_date)   (fim exclusivo)

* Internação de 3 dias — admite dia 1, alta dia 4 → diárias nos dias 1, 2 e 3
  (o dia 4, da alta, não é cobrado).
* **Exceção — admissão e alta no MESMO dia** → cobra-se **1 diária** (o dia da
  admissão), senão a estada de um dia não geraria receita nenhuma.

Para uma internação **ativa** (sem alta), não há dia de alta para excluir, então
acumula-se de ``admission_date`` até **hoje inclusive**:

    janela faturável = [admission_date, hoje]   (fim inclusivo)

Resolução do TUSS por dia
-------------------------
Para cada ``service_date`` da janela ainda sem ``DailyCharge``:

* lê ``admission.current_bed.bed_type_code`` (o accessor que devolve o code do
  ``core.BedType`` governado ou o texto legado);
* procura o ``AccommodationTuss`` **ativo** para esse ``bed_type_code``;
* se existe, cria ``DailyCharge(quantity=1, tuss_code=<da diária>,
  bed_type_code=<snapshot>)``.

Se não houver leito atual OU não houver mapeamento ativo para o tipo de leito,
aquele dia é **pulado** (nunca se inventa um TUSS). Se a internação inteira não
tiver mapeamento, retorna-se lista vazia — sem estourar exceção. O caso é
registrado em log para diagnóstico.

    ⚠️ GAP conhecido (ver reporte B3): a alta via ``adt.discharge`` libera
    ``Admission.current_bed`` (fica NULL). Portanto o acúmulo deve rodar
    **enquanto o leito ainda está atribuído** (pull/sob-demanda durante a
    estada, e uma última vez na alta antes de liberar o leito). Como cada
    ``DailyCharge`` já é imutável e snapshota ``bed_type_code``, as diárias
    acumuladas sobrevivem à liberação do leito.

Idempotência
------------
A ``UniqueConstraint(admission, service_date)`` garante no máx. uma diária por
dia. O serviço checa os dias já existentes ANTES de criar (não estoura
``IntegrityError``): rodar N vezes converge para o mesmo conjunto de diárias.

Precificação
------------
NÃO se precifica aqui. ``DailyCharge`` carrega só o TUSS + quantidade=1; o valor
(``PriceTableItem.negotiated_value`` do convênio) é resolvido pelo B3 ao montar a
guia — mesmo padrão dos bridges de laboratório/cirurgia.

``apps.billing → apps.emr`` coupling coberto pelo edge grandfathered do
import-linter (já usado pelos bridges de lab/cirurgia).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.billing.inpatient_models import AccommodationTuss, DailyCharge
from apps.billing.models import InsuranceProvider, TISSGuide, TISSGuideItem
from apps.billing.services.lab_order_billing import (
    _active_insurance,
    _active_price_table,
    _unit_value,
)
from apps.emr.models import Admission

logger = logging.getLogger(__name__)


def _billable_window_end(admission: Admission, *, today: date) -> date:
    """Último ``service_date` faturável (inclusivo) da janela de diárias.

    Aplica a regra de pernoites: com alta, exclui o dia da alta (fim exclusivo),
    salvo admissão+alta no mesmo dia (cobra 1). Sem alta (ativa), vai até hoje.
    """
    start = admission.admission_datetime.date()
    if admission.status == Admission.Status.DISCHARGED and admission.actual_discharge_datetime:
        discharge_date = admission.actual_discharge_datetime.date()
        if discharge_date <= start:
            # Mesmo dia (ou alta datada antes/igual à admissão): 1 diária, o dia da admissão.
            return start
        # Não cobra o dia da alta: última diária é a véspera da alta.
        return discharge_date - timedelta(days=1)
    # Internação ativa (ou sem alta efetiva registrada): acumula até hoje inclusive.
    return today


def accrue_daily_charges(admission: Admission) -> list[DailyCharge]:
    """Acumula (idempotentemente) as diárias de leito faturáveis de uma internação.

    Retorna a lista de ``DailyCharge`` **criadas nesta chamada** (vazia numa
    re-execução sem dias novos, ou quando não há mapeamento de diária algum).
    Nunca estoura por dia sem leito/mapeamento — apenas pula e registra em log.

    Ver o docstring do módulo para a regra exata de contagem (pernoites), a
    resolução do TUSS e o gap de ``current_bed`` liberado na alta.
    """
    today = timezone.now().date()

    with transaction.atomic():
        # of=("self",) trava só a linha da Admission: current_bed é nullable, então
        # o select_related gera um LEFT OUTER JOIN e um FOR UPDATE amplo estouraria
        # ("FOR UPDATE cannot be applied to the nullable side of an outer join").
        admission = (
            Admission.objects.select_for_update(of=("self",))
            .select_related("current_bed", "current_bed__bed_type")
            .get(pk=admission.pk)
        )

        start = admission.admission_datetime.date()
        end = _billable_window_end(admission, today=today)
        if end < start:
            return []

        # Dias já acumulados — a constraint garante unicidade; checamos antes de
        # criar para não estourar IntegrityError (idempotência).
        already = set(
            DailyCharge.objects.filter(
                admission=admission, service_date__range=(start, end)
            ).values_list("service_date", flat=True)
        )

        bed = admission.current_bed
        bed_type_code = bed.bed_type_code if bed is not None else ""
        mapping: AccommodationTuss | None = None
        if bed_type_code:
            mapping = AccommodationTuss.objects.filter(
                bed_type_code=bed_type_code, active=True
            ).first()

        if mapping is None:
            # Sem leito atual ou sem mapeamento de diária para o tipo de leito:
            # nada a acumular. Não é erro — internação particular/sem config.
            logger.info(
                "accrue_daily_charges: sem AccommodationTuss ativo (admission=%s, "
                "bed_type_code=%r) — nenhuma diária acumulada.",
                admission.pk,
                bed_type_code,
            )
            return []

        created: list[DailyCharge] = []
        service_date = start
        while service_date <= end:
            if service_date not in already:
                created.append(
                    DailyCharge.objects.create(
                        admission=admission,
                        service_date=service_date,
                        tuss_code=mapping.tuss_code,
                        bed_type_code=bed_type_code,
                        quantity=1,
                    )
                )
            service_date += timedelta(days=1)

        return created


def generate_internacao_guide_for_admission(admission: Admission) -> TISSGuide:
    """B3 — Gera (ou retorna a existente) a guia TISS de Resumo de Internação.

    Monta uma guia ``guide_type='internacao'`` a partir das :class:`DailyCharge`
    acumuladas na internação, precificando cada TUSS de diária pela ``PriceTable``
    ativa do convênio — o mesmo caminho dos bridges de laboratório/cirurgia.

    Fluxo (espelha ``generate_sadt_guide_for_surgical_case``):

      * **accrue primeiro**: chama ``accrue_daily_charges(admission)`` para
        garantir que as diárias estão atualizadas ENQUANTO o leito ainda está
        atribuído (a alta libera ``Admission.current_bed`` → o acúmulo posterior
        não teria como resolver o TUSS da diária; ver o GAP no docstring do
        módulo). O acúmulo é idempotente; as ``DailyCharge`` já criadas
        snapshotam ``bed_type_code`` e sobrevivem à liberação do leito.
      * **agrega por TUSS**: cada TUSS de diária distinto vira UM
        ``TISSGuideItem`` com ``quantity`` = nº de diárias daquele TUSS
        (transferência entre tipos de leito → múltiplos itens). ``unit_value`` é
        o valor negociado da ``PriceTable``; ``total_value`` é recalculado no
        ``TISSGuideItem.save``.

    Pré-condições (``ValidationError`` clara, PT-BR):

      * ``admission.encounter`` obrigatório (``TISSGuide.encounter`` é PROTECT —
        nunca fabricar um encounter);
      * paciente com convênio ativo cujo ANS esteja cadastrado em faturamento;
      * ao menos uma ``DailyCharge`` faturável — senão a guia recém-criada sofre
        rollback DENTRO do bloco atômico (não deixa guia vazia; mantém a
        invariante "uma guia por internação" e a idempotência).

    Idempotente: uma segunda chamada devolve a guia criada pela primeira.
    """
    with transaction.atomic():
        admission = (
            Admission.objects.select_for_update(of=("self",))
            .select_related("patient")
            .get(pk=admission.pk)
        )

        existing = TISSGuide.objects.filter(admission=admission).first()
        if existing is not None:
            return existing

        if admission.encounter_id is None:
            raise ValidationError("Internação sem atendimento (encounter) não pode gerar guia.")

        insurance = _active_insurance(admission.patient_id)
        if insurance is None:
            raise ValidationError(
                "Paciente sem convênio ativo — internação não faturável por TISS."
            )
        provider = InsuranceProvider.objects.filter(ans_code=insurance.provider_ans_code).first()
        if provider is None:
            raise ValidationError(
                f"Operadora ANS {insurance.provider_ans_code} não cadastrada em faturamento."
            )

        # Acumula as diárias enquanto o leito ainda pode estar atribuído (idempotente).
        accrue_daily_charges(admission)

        charges = list(DailyCharge.objects.filter(admission=admission).select_related("tuss_code"))
        if not charges:
            raise ValidationError("Internação sem diárias faturáveis: nenhuma diária acumulada.")

        today = timezone.now().date()
        price_table = _active_price_table(provider, today)
        competency = today.strftime("%Y-%m")

        guide = TISSGuide.objects.create(
            guide_type="internacao",
            encounter_id=admission.encounter_id,
            patient_id=admission.patient_id,
            provider=provider,
            price_table=price_table,
            admission=admission,
            status="draft",
            insured_card_number=insurance.card_number or "",
            competency=competency,
        )

        # Agrega as diárias por TUSS (transferência entre tipos de leito → 1 item
        # por TUSS distinto, quantidade = nº de diárias). Agregado em Python para
        # não esbarrar no gotcha do mypy com .values().annotate().
        aggregated: dict[int, dict] = {}
        for charge in charges:
            entry = aggregated.setdefault(
                charge.tuss_code_id, {"tuss": charge.tuss_code, "quantity": 0}
            )
            entry["quantity"] += charge.quantity

        for entry in aggregated.values():
            tuss = entry["tuss"]
            TISSGuideItem.objects.create(
                guide=guide,
                tuss_code=tuss,
                description=tuss.description or "",
                quantity=Decimal(entry["quantity"]),
                unit_value=_unit_value(price_table, tuss),
            )

        return guide

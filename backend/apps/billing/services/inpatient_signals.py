"""B5 — O billing acumula as diárias no momento da alta.

Fecha o vazamento descrito no docstring de ``inpatient_billing``: até aqui só
acumulava quem gerasse a guia, e como a alta libera ``Admission.current_bed``,
uma guia emitida depois da alta não tinha mais como resolver o tipo de leito —
as diárias sumiam sem erro.

O acoplamento é por sinal, não por import: ``apps.emr -> apps.billing`` é
proibido pelo import-linter, então o ADT publica ``admission_pre_bed_release`` e
quem se pluga é este módulo (``apps.billing -> apps.emr`` já é permitido).
"""

from __future__ import annotations

import logging

from django.dispatch import receiver

from apps.emr.services.adt_signals import admission_pre_bed_release

logger = logging.getLogger(__name__)


@receiver(admission_pre_bed_release, dispatch_uid="billing_accrue_on_discharge")
def accrue_daily_charges_on_discharge(sender, admission, **kwargs):
    """Acumula as diárias da estada enquanto o leito ainda está atribuído.

    Roda dentro da transação da alta e **engole as próprias exceções de
    propósito**. Alta é ato clínico: se o faturamento quebrar, o paciente ainda
    tem de poder sair do leito. A diária perdida é recuperável — a task diária
    ``accrue_active_admissions`` já terá acumulado quase tudo durante a estada,
    então o pior caso é perder a última — enquanto um paciente preso no leito
    por erro de billing não é recuperável.

    O erro é logado em ERROR justamente para não virar perda silenciosa, que é o
    defeito que este módulo existe para corrigir.
    """
    # Import local: no topo do módulo criaria um ciclo com inpatient_billing
    # durante o carregamento dos apps, e é o que permite o teste substituir a
    # função por um mock que estoura.
    from apps.billing.services import inpatient_billing

    try:
        created = inpatient_billing.accrue_daily_charges(admission)
    except Exception:
        logger.exception(
            "accrue_on_discharge: falha ao acumular diárias da internação %s. "
            "A alta segue; as diárias deste dia podem precisar de acúmulo manual.",
            getattr(admission, "pk", "?"),
        )
        return

    if created:
        logger.info(
            "accrue_on_discharge: %d diária(s) acumulada(s) na alta da internação %s.",
            len(created),
            admission.pk,
        )

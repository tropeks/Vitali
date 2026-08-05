"""B7 — Ponte da cirurgia para o faturamento SUS.

O eixo do convênio já existia (``generate_sadt_guide_for_surgical_case`` monta a
guia TISS a partir do ``tuss_code``). O eixo SUS não: ``SurgicalProcedure`` não
tinha código SIGTAP, então uma cirurgia feita pelo SUS não alcançava AIH, BPA nem
APAC — o ato consumia sala, equipe e material e não virava receita nenhuma.

Este módulo NÃO decide codificação. O procedimento **principal** de uma AIH é
escolha humana, e ``generate_aih_for_admission`` já recusa inferir. O que se faz
aqui é o que dá para fazer sem inventar: puxar os procedimentos cirúrgicos já
codificados para a AIH como **secundários**, e oferecer a quem codifica a lista
do que a cirurgia registrou.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError

from apps.emr.models import Admission
from apps.emr.surgery_models import SurgicalCase, SurgicalProcedure


def surgical_sigtap_lines(admission: Admission) -> list[tuple]:
    """``(sigtap, quantidade)`` das cirurgias **executadas** da internação.

    Só entra o que aconteceu de fato: ``SurgicalCase`` FINALIZADA. Uma cirurgia
    agendada ou em andamento não é ato executado, e faturá-la seria cobrar por
    algo que pode nem acontecer. Procedimento sem SIGTAP (paciente de convênio)
    é ignorado em silêncio — não é erro, é outro eixo de faturamento.
    """
    if admission.encounter_id is None:
        return []
    procs = (
        SurgicalProcedure.objects.select_related("sigtap")
        .filter(
            case__encounter_id=admission.encounter_id,
            case__status=SurgicalCase.Status.FINALIZADA,
            sigtap__isnull=False,
        )
        .order_by("created_at")
    )
    return [(p.sigtap, int(p.quantity)) for p in procs]


def sigtap_candidates_for_admission(admission: Admission) -> list:
    """Os SIGTAP que a internação registrou, para apoiar a codificação da AIH.

    Existe porque o procedimento principal é decisão de quem codifica, e decidir
    às cegas é como o erro entra. O sistema mostra o que a cirurgia registrou; a
    escolha continua sendo de uma pessoa.

    Devolve sem repetição, preservando a ordem de registro.
    """
    if admission.encounter_id is None:
        raise ValidationError(
            "Internação sem atendimento (encounter) não tem procedimentos para codificar."
        )
    vistos = set()
    out = []
    for sigtap, _qtd in surgical_sigtap_lines(admission):
        if sigtap.pk not in vistos:
            vistos.add(sigtap.pk)
            out.append(sigtap)
    return out

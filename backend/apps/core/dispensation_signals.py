"""Sinal de dispensação faturável — ponto de encontro entre farmácia e faturamento.

Mora em ``apps.core`` porque é o único lugar em que os dois lados podem se
encontrar. O contrato do import-linter isola os domínios entre si, e nem
``apps.billing -> apps.pharmacy`` nem ``apps.pharmacy -> apps.billing`` estão na
lista de exceções — só o ``core`` é hub permitido para ambos. Definir o sinal num
dos dois lados obrigaria o outro a importá-lo e quebraria a fronteira.

O payload é **deliberadamente primitivo**. Nada de passar uma ``Dispensation``:
o faturamento não deve conhecer o modelo da farmácia, senão o acoplamento volta
pela porta dos fundos, só que sem o linter enxergar. O que trafega é o mínimo
para lançar um item numa conta — quem emite resolve o resto.

kwargs:
    ``encounter_id``     — atendimento que ancora a cobrança (obrigatório).
    ``patient_id``       — paciente.
    ``anvisa_registro``  — registro ANVISA do medicamento; o billing o converte
                           em TUSS por ``core.terminology.tuss_for_anvisa_registro``.
    ``quantity``         — Decimal, quantidade dispensada.
    ``description``      — texto do medicamento no momento da dispensação.
    ``source_id``        — UUID da dispensação; é a chave de idempotência, para
                           reprocessar não cobrar duas vezes o mesmo remédio.

Como o receiver de alta do ADT, quem escuta trata as próprias exceções: uma falha
de faturamento não pode impedir um medicamento de ser dispensado a um paciente.
"""

from __future__ import annotations

from django.dispatch import Signal

dispensation_billable = Signal()

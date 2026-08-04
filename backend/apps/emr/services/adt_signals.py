"""Sinais do ADT — pontos de extensão do ciclo de vida da internação.

Existem para que outros domínios reajam a um evento de ADT **sem que o ``emr``
precise conhecê-los**. O contrato do import-linter proíbe
``apps.emr -> apps.billing`` (ver ``backend/.importlinter``), e com razão: o
prontuário não deve depender do faturamento. A direção permitida é a inversa,
então quem se acopla é o billing, ouvindo daqui.
"""

from __future__ import annotations

from django.dispatch import Signal

# Disparado por ``adt.discharge`` DEPOIS de a alta estar gravada (status,
# disposition e actual_discharge_datetime já persistidos) e ANTES de o leito ser
# liberado — ``Admission.current_bed`` ainda aponta para o leito.
#
# Essa janela é o ponto exato em que dá para faturar a estada: a data de alta já
# é conhecida (a regra de pernoites depende dela) e o tipo de leito ainda é
# resolvível. Depois da liberação, ``current_bed`` é NULL e o TUSS da diária fica
# irrecuperável.
#
# kwargs: ``admission`` (Admission, já travada na transação da alta),
#         ``actor`` (User | None).
#
# Receivers rodam DENTRO da transação da alta e não podem derrubá-la: alta é ato
# clínico, e nenhuma falha de processo administrativo justifica prender um
# paciente no leito. Quem escuta é responsável por engolir e registrar as suas
# próprias exceções.
admission_pre_bed_release = Signal()

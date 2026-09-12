"""Data de execução de um item faturado — o lado da ESCRITA da regra de fuso.

``xml_engine._to_local`` é o estrangulamento do fuso na LEITURA: toda data que
chega ao XML passa por ele antes de virar ``st_data``/``st_hora``. Este módulo é
o par dele na escrita, e existe pelo mesmo motivo.

As cinco pontes clínico→faturamento têm de reduzir um ``DateTimeField`` (aware,
gravado em UTC porque ``USE_TZ=True``) a um ``DateField``. Chamar ``.date()``
direto nesse valor devolve o dia em **UTC**: uma cirurgia incisada às 21:30 de
São Paulo, uma dispensação das 22h numa enfermaria, um exame coletado às 23h —
todos entram na conta com a data do DIA SEGUINTE. É o mesmo bug que a fatia
anterior fechou em ``dadosInternacao``, só que uma camada acima: aqui a data
errada é PERSISTIDA, então nem corrigir o filtro depois a conserta. Uma linha
com data fora do período de faturamento declarado na própria guia é glosa
pronta.

Mora num módulo próprio, e não num dos bridges, porque são CINCO produtores
independentes: deixar a regra em qualquer um deles convida o sexto a reimplementar
`.date()` sozinho.
"""

from __future__ import annotations

import datetime

from django.utils import timezone


def to_local_date(value) -> datetime.date | None:
    """Reduz ``value`` à data LOCAL da clínica (``settings.TIME_ZONE``).

    Aceita e devolve:

    * ``datetime`` aware → data no fuso da clínica (a conversão que dá nome a
      este módulo);
    * ``datetime`` naive → ``.date()`` direto. Naive já é hora de parede;
      converter suporia um fuso de origem que ninguém declarou;
    * ``date`` puro → devolvido intacto. Data sem hora não tem fuso a converter,
      e ``localtime`` sobre ela levanta ``AttributeError`` — por isso o teste de
      ``datetime`` vem ANTES (``datetime`` é subclasse de ``date``, a ordem
      inversa passaria um ``date`` adiante e estouraria);
    * ``None`` → ``None``. Ausência de fonte é resposta legítima e propaga até a
      emissão do XML, que falha alto; nunca vira ``today()``.
    """
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        if timezone.is_aware(value):
            return timezone.localtime(value).date()
        return value.date()
    return value

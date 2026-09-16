"""
Guarda: o porte da CBHPM é CÓDIGO, não número (ordem 013).

**O defeito.** ``CBHPMItem.porte`` nasceu ``DecimalField`` com o rótulo "Valor numérico
do porte (quantidade de CH)". Na CBHPM publicada pela AMB o porte é **classe
hierárquica** — ``3B``, ``13C`` — e, em toda a Medicina Laboratorial, **fração de uma
classe**: ``0,01 de 1A``. Medido na edição 2022 rev. ago/2023: das 4.883 linhas
extraídas do PDF, **zero** têm porte numérico, e **1.046** são fracionárias.

Consequência de manter decimal: ``import_cbhpm`` passa o porte por ``_to_decimal()``,
que levanta em ``"3B"`` — o ``CatalogImporter`` isolaria **todas** as linhas e o
catálogo importaria 0. E pior, se alguém "resolvesse" o erro cortando o ``0,01 de``
e gravando ``1A`` como ``1``, o porte sairia inflado **de 25 a 100 vezes** no capítulo
mais volumoso do livro — INTENT §Limites: nenhum número contratual inventado.

**A separação que esta ordem faz.** O livro dá CLASSIFICAÇÃO; a VALORAÇÃO (quantos CH
vale a classe, quanto vale o CH em reais) é negociada entre clínica e operadora — o
próprio §1.2 da CBHPM diz que os portes "não expressam valores monetários". Então:

* ``porte``    → ``CharField``: a classe como publicada.
* ``porte_ch`` → ``DecimalField``: a quantidade de CH, que só entra por tabela de
  valoração contratada, nunca do livro.
* ``valor()``  → ``porte_ch × valor_ch``, e segue devolvendo ``Decimal('0')``
  enquanto qualquer fator estiver no default inerte.

Contra o código anterior à ordem 013 estes testes falham: ``porte`` não aceita texto
e ``porte_ch`` não existe.
"""

from __future__ import annotations

from decimal import Decimal

from django.test import TestCase

from apps.core.cbhpm_models import CBHPMItem


class PorteEhCodigoTests(TestCase):
    """O porte guarda a classe publicada, com fração inclusive."""

    def test_porte_aceita_classe_hierarquica(self) -> None:
        item = CBHPMItem.objects.create(
            code="3.01.02.01-4", display="Terapia de pressão negativa", porte="5A"
        )
        item.refresh_from_db()
        self.assertEqual(item.porte, "5A")

    def test_porte_aceita_fracao_de_classe(self) -> None:
        """``0,01 de 1A`` é o porte de boa parte da Medicina Laboratorial.

        Guardar ``1A`` aqui infla o porte cem vezes. Guardar ``0,01`` perde a classe.
        A única leitura fiel é a string publicada.
        """
        item = CBHPMItem.objects.create(
            code="4.03.11.03-1", display="Alcaptonúria, pesquisa", porte="0,01 de 1A"
        )
        item.refresh_from_db()
        self.assertEqual(item.porte, "0,01 de 1A")

    def test_porte_vazio_e_o_default_inerte(self) -> None:
        item = CBHPMItem.objects.create(code="1.01.01.01-2", display="Consulta")
        self.assertEqual(item.porte, "")


class ValoracaoUsaPorteCHTests(TestCase):
    """A valoração deixa de depender do porte-classe e passa a usar o CH contratado."""

    def test_valor_multiplica_porte_ch_por_valor_ch(self) -> None:
        item = CBHPMItem.objects.create(
            code="3.01.02.01-4",
            display="Terapia de pressão negativa",
            porte="5A",
            porte_ch=Decimal("15.0000"),
            valor_ch=Decimal("3.000000"),
        )
        self.assertEqual(item.valor(), Decimal("45.0000"))

    def test_valor_e_zero_enquanto_nao_houver_valoracao_contratada(self) -> None:
        """Importar o livro NÃO produz preço — e é assim que tem de ser.

        A CBHPM classifica; quanto vale o CH é contrato. Um item recém-importado
        tem classe e custo operacional em UCO, e valor zero até alguém carregar a
        tabela de valoração negociada.
        """
        item = CBHPMItem.objects.create(
            code="4.03.11.03-1",
            display="Alcaptonúria, pesquisa",
            porte="0,01 de 1A",
            valor_ch=Decimal("0.603000"),
        )
        self.assertEqual(item.valor(), Decimal("0"))
        self.assertEqual(item.porte_ch, Decimal("0"))

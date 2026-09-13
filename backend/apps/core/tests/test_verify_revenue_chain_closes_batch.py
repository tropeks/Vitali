"""
Guarda: a cadeia de receita tem de FECHAR o lote, não imprimir uma soma (ordem 008).

**O defeito.** `verify_revenue_chain` passo 5 faz `total = sum(...)` sobre os itens das
guias, em memória, escreve o número na saída e segue. O lote fica como nasceu: `open`,
com `total_value` em 0,00. Medido na lab em 13/09, os dois lotes que a ordem 006 produziu:

    2026090001 | open | 0.00
    2026090002 | open | 0.00

Ou seja, a Prioridade 2 do INTENT — guia TISS válida → lote → **faturamento** — estava
provada como valor *apurável*, nunca como estado *persistido*. A diferença não é
acadêmica: quem lê o banco procurando faturamento encontra zero.

Não é que o sistema não saiba fechar. `TISSBatchViewSet.close` agrega `Sum("total_value")`
e grava `status`, `closed_at` e `total_value` — a prova do passo 3 da ordem 007 fechou dois
lotes por lá, com R$ 100,00 gravado em cada. O problema era que essa regra vivia dentro de
uma view, devolvendo `Response` de dentro do `atomic()`, e nenhum outro chamador conseguia
reusá-la.

Contra o código anterior à ordem 008 este teste falha (o lote termina `open` em 0,00);
depois, passa — e passa lendo do BANCO, não da saída do comando, porque foi exatamente
confiar na saída do comando que sustentou a afirmação errada de que o faturamento estava
gravado.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from django.core.management import call_command

from apps.billing.models import (
    InsuranceProvider,
    PriceTable,
    PriceTableItem,
    TISSBatch,
    TISSGuide,
)
from apps.core.models import TUSSCode, User
from apps.emr.models import Encounter, Patient, Professional
from apps.test_utils import TenantTestCase


class VerifyRevenueChainClosesBatchTests(TenantTestCase):
    """Faturamento é estado no banco, não número na tela."""

    def setUp(self) -> None:
        super().setUp()
        user = User.objects.create_user(
            email="chain-close@test.com", full_name="Dr. Close", password="Str0ng!Pass#2024"
        )
        profissional = Professional.objects.create(
            user=user, council_type="CRM", council_number="90008", council_state="SP"
        )
        # CNES é obrigatório para o XML da guia renderizar: `_cnes_obrigatorio`
        # levanta antes de qualquer validação. O valor é o fictício declarado que o
        # Imediato autorizou para staging, e não aponta para estabelecimento real.
        profissional.cnes_code = "0000000"
        # CBO pela mesma razão, e é a segunda lacuna da mesma família: `CBOS` é
        # enumeração FECHADA no XSD da ANS, então string vazia não é "campo em
        # branco" — é valor fora do conjunto, e o lote inteiro reprova. `225125`
        # é taxonomia real (médico clínico), o mesmo valor que
        # `seed_revenue_staging` usa em staging.
        profissional.cbo_code = "225125"
        profissional.save(
            update_fields=[
                "cnes",
                "legacy_cnes_text",
                "cnes_unmatched",
                "cbo",
                "legacy_cbo_text",
                "cbo_unmatched",
            ]
        )
        paciente = Patient.objects.create(
            full_name="Paciente Close",
            cpf="000.000.000-08",
            birth_date=datetime.date(1990, 8, 1),
            gender="F",
        )
        Encounter.objects.create(patient=paciente, professional=profissional)
        provider = InsuranceProvider.objects.create(
            name="Operadora Close (FICTÍCIA — staging)", ans_code="000008"
        )
        tuss = TUSSCode.objects.create(
            code="10101012", description="Consulta (teste)", table_number="22", active=True
        )
        tabela = PriceTable.objects.create(
            provider=provider,
            name="Tabela Close (FICTÍCIA — staging)",
            valid_from=datetime.date.today(),
            is_active=True,
        )
        PriceTableItem.objects.create(
            table=tabela, tuss_code=tuss, negotiated_value=Decimal("100.00")
        )

    def test_cadeia_fecha_o_lote_com_o_valor_gravado(self) -> None:
        """Percorrer a cadeia tem de deixar o lote `closed` com o valor no banco."""
        call_command("verify_revenue_chain", "--tenant", self.tenant.schema_name, "--create")

        lote = TISSBatch.objects.get()
        lote.refresh_from_db()

        self.assertEqual(
            lote.status,
            "closed",
            "a cadeia percorreu e deixou o lote aberto — faturamento não foi persistido, "
            "só impresso (verify_revenue_chain passo 5 somava em memória)",
        )
        self.assertEqual(
            lote.total_value,
            Decimal("100.00"),
            "o lote fechou sem o valor gravado — `total_value` é o campo que quem lê o "
            "banco procura para achar faturamento",
        )
        self.assertIsNotNone(
            lote.closed_at,
            "lote fechado sem `closed_at` não tem quando — e sem quando não há competência",
        )

    def test_a_guia_da_cadeia_entra_no_lote_fechado(self) -> None:
        """Fechar lote vazio não prova nada: a guia da cadeia tem de estar dentro dele.

        Guarda contra o fechamento acontecer sobre um lote que não é o da caminhada —
        seria verde sem significar nada, que é o modo de falha que esta série de ordens
        vem perseguindo.
        """
        call_command("verify_revenue_chain", "--tenant", self.tenant.schema_name, "--create")

        lote = TISSBatch.objects.get()
        guia = TISSGuide.objects.get()
        self.assertIn(
            guia,
            lote.guides.all(),
            "o lote fechado não contém a guia que a cadeia criou",
        )
        self.assertEqual(
            lote.total_value,
            sum(item.total_value for item in guia.items.all()),
            "o valor gravado no lote diverge da soma dos itens da guia que ele contém",
        )

    def test_a_guia_termina_enviada(self) -> None:
        """A guia tem de sair do rascunho: a cadeia a declara pronta e o lote a envia.

        Registrado como ressalva no fim da ordem 008 — o lote fechava e a guia ficava
        `draft`, porque nada movia `draft` para `pending` e o fechamento só promovia
        `pending`. Vira teste na ordem 009, que fez a cadeia declarar a própria guia
        pronta antes de fechar.

        Importa além da coerência: `_ACTIVE_GUIDE_STATUSES` exclui `draft`, então guia
        que nunca sai do rascunho é invisível para a checagem `duplicate` da cunha de
        glosa.
        """
        call_command("verify_revenue_chain", "--tenant", self.tenant.schema_name, "--create")

        guia = TISSGuide.objects.get()
        guia.refresh_from_db()
        self.assertEqual(
            guia.status,
            "submitted",
            "o lote fechou mas a guia continuou fora do ciclo de vida — lote fechado "
            "cheio de rascunho é o sinal verde que não significa verde",
        )

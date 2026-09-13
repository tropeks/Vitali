"""
Guarda: a guia entra no ciclo de vida, e lote fechado significa enviado (ordem 009).

**O defeito.** `GUIDE_STATUS` é `draft → pending → submitted → paid/denied/appeal`
(`billing/models.py:23-30`), mas **nada no código move `draft` para `pending`**. A única
escrita de status no caminho de lote é a promoção `pending → submitted` do fechamento, de
modo que guia nascida rascunho fica rascunho para sempre. Medido na lab em 13/09: os seis
lotes `closed` de staging contêm guias em `draft` — lote fechado cheio de rascunho.

Duas consequências além da incoerência:

* `_ACTIVE_GUIDE_STATUSES = ["pending", "submitted", "paid"]`
  (`services/glosa_safety.py:85`) exclui `draft`, e é **por isso** que a checagem
  `duplicate` da cunha de glosa era inalcançável por construção. A ordem 007 registrou o
  limite sem a causa; a causa é esta.
* A taxa de glosa (`docs/PLAN_SPRINT10.md:83`) exclui rascunho do denominador. Clínica
  cujas guias nunca saem de `draft` mede glosa sobre denominador vazio.

Decisão do Imediato em 13/09: modo **estrito**. Fechar lote significa "enviado", então
guia que ninguém declarou pronta não pode ir no XML — INTENT §Limites, "sinal verde tem
que significar verde", e compliance como gate.

Contra o código anterior à ordem 009 os dois primeiros testes falham (o fechamento aceita
rascunho, e não existe transição); depois, passam.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError

from apps.billing.models import (
    InsuranceProvider,
    PriceTable,
    PriceTableItem,
    TISSBatch,
    TISSGuide,
    TISSGuideItem,
)
from apps.core.models import AuditLog, TUSSCode, User
from apps.emr.models import Encounter, Patient, Professional
from apps.test_utils import TenantTestCase


class GuideLifecycleTests(TenantTestCase):
    """Declarar uma guia pronta é ato auditável; fechar lote com rascunho é recusado."""

    def setUp(self) -> None:
        super().setUp()
        self.user = User.objects.create_user(
            email="ciclo@test.com", full_name="Dr. Ciclo", password="Str0ng!Pass#2024"
        )
        profissional = Professional.objects.create(
            user=self.user, council_type="CRM", council_number="90009", council_state="SP"
        )
        # CNES e CBO pelo mesmo motivo das ordens 007 e 008: sem eles a guia não
        # renderiza (CNES é st_texto7 com minLength=1) e o lote reprova no XSD
        # (CBOS é enumeração FECHADA, string vazia é valor fora do conjunto).
        # Valores fictícios declarados, autorizados para staging.
        profissional.cnes_code = "0000000"
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
            full_name="Paciente Ciclo",
            cpf="000.000.000-09",
            birth_date=datetime.date(1990, 9, 1),
            gender="F",
        )
        encontro = Encounter.objects.create(patient=paciente, professional=profissional)
        self.provider = InsuranceProvider.objects.create(
            name="Operadora Ciclo (FICTÍCIA — staging)", ans_code="000009"
        )
        tuss = TUSSCode.objects.create(
            code="10101012", description="Consulta (teste)", table_number="22", active=True
        )
        tabela = PriceTable.objects.create(
            provider=self.provider,
            name="Tabela Ciclo (FICTÍCIA — staging)",
            valid_from=datetime.date.today(),
            is_active=True,
        )
        PriceTableItem.objects.create(
            table=tabela, tuss_code=tuss, negotiated_value=Decimal("100.00")
        )
        # `patient` e `executor` são obrigatórios. Omiti-los produz um
        # `IntegrityError` que o laço de `TISSGuide.save()` engole e relata como
        # "Failed to generate a unique guide number after 3 attempts" — mensagem
        # que aponta para o lugar errado. Perdi uma rodada nisso.
        self.guia = TISSGuide.objects.create(
            patient=paciente,
            executor=profissional,
            encounter=encontro,
            provider=self.provider,
            price_table=tabela,
            guide_type="consulta",
            status="draft",
            competency=datetime.date.today().replace(day=1).strftime("%Y-%m"),
            total_value=Decimal("100.00"),
            insured_card_number="FICTICIA-STAGING",
        )
        TISSGuideItem.objects.create(
            guide=self.guia,
            tuss_code=tuss,
            description="Consulta (teste)",
            quantity=1,
            unit_value=Decimal("100.00"),
            total_value=Decimal("100.00"),
        )

    # ── a transição ──────────────────────────────────────────────────────────

    def test_marcar_pronta_move_draft_para_pending(self) -> None:
        from apps.billing.services.batch_lifecycle import marcar_pronta_para_envio

        marcar_pronta_para_envio(guia=self.guia, actor=self.user)

        self.guia.refresh_from_db()
        self.assertEqual(
            self.guia.status,
            "pending",
            "declarar a guia pronta tem de movê-la para 'pending' — é o estado que "
            "significa 'pronta, ainda não enviada'",
        )

    def test_marcar_pronta_escreve_no_auditlog(self) -> None:
        """Declarar que uma guia pode ir à operadora é ato auditável.

        Mesma razão do override de glosa da ordem 007: é um humano afirmando algo
        sobre dado que vai sair da clínica. Sem a linha, não há quem nem quando.
        """
        from apps.billing.services.batch_lifecycle import marcar_pronta_para_envio

        antes = AuditLog.objects.filter(action="guide_marked_ready").count()
        marcar_pronta_para_envio(guia=self.guia, actor=self.user)
        depois = AuditLog.objects.filter(action="guide_marked_ready").count()

        self.assertEqual(depois, antes + 1, "a transição não deixou linha no AuditLog")
        linha = AuditLog.objects.filter(action="guide_marked_ready").order_by("-created_at").first()
        assert linha is not None
        self.assertEqual(linha.resource_type, "tiss_guide")
        self.assertEqual(linha.resource_id, str(self.guia.pk))
        self.assertEqual(linha.old_data.get("status"), "draft")
        self.assertEqual(linha.new_data.get("status"), "pending")
        self.assertEqual(
            linha.new_data.get("guide_number"),
            self.guia.guide_number,
            "a linha tem de dizer QUAL guia foi declarada pronta, não só o id interno",
        )

    def test_marcar_pronta_recusa_estado_de_origem_invalido(self) -> None:
        """Só rascunho vira pendente. Re-declarar uma guia já enviada é erro, não no-op."""
        from apps.billing.services.batch_lifecycle import marcar_pronta_para_envio

        self.guia.status = "submitted"
        self.guia.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            marcar_pronta_para_envio(guia=self.guia, actor=self.user)

        self.guia.refresh_from_db()
        self.assertEqual(self.guia.status, "submitted", "a guia mudou apesar da recusa")

    # ── o fechamento estrito ─────────────────────────────────────────────────

    def test_fechar_lote_recusa_rascunho_e_nomeia_a_guia(self) -> None:
        """Lote com guia em rascunho não fecha, e a recusa diz quais guias faltam."""
        from apps.billing.services.batch_lifecycle import LoteComRascunho, fechar_lote

        lote = TISSBatch.objects.create(provider=self.provider)
        lote.guides.add(self.guia)

        with self.assertRaises(LoteComRascunho) as ctx:
            fechar_lote(lote=lote, actor=self.user)

        numeros = [g.guide_number for g in ctx.exception.rascunhos]
        self.assertIn(
            self.guia.guide_number,
            numeros,
            "a recusa não nomeou a guia em rascunho — quem fecha precisa saber qual "
            "declarar pronta, não só que 'há rascunho'",
        )
        lote.refresh_from_db()
        self.assertEqual(lote.status, "open", "o lote fechou apesar da recusa")
        self.assertEqual(lote.total_value, Decimal("0.00"), "o lote gravou valor apesar da recusa")

    def test_fechar_lote_promove_pendente_para_enviada(self) -> None:
        """Com a guia declarada pronta, o fechamento a marca como enviada."""
        from apps.billing.services.batch_lifecycle import fechar_lote, marcar_pronta_para_envio

        marcar_pronta_para_envio(guia=self.guia, actor=self.user)
        lote = TISSBatch.objects.create(provider=self.provider)
        lote.guides.add(self.guia)

        fechar_lote(lote=lote, actor=self.user)

        lote.refresh_from_db()
        self.guia.refresh_from_db()
        self.assertEqual(lote.status, "closed")
        self.assertEqual(lote.total_value, Decimal("100.00"))
        self.assertEqual(
            self.guia.status,
            "submitted",
            "o lote fechou mas a guia continuou 'pending' — fechar lote significa enviar",
        )

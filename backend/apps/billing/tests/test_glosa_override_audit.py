"""
O override de alerta de glosa tem de entrar no AuditLog (ordem 007, emenda).

**Por que.** O `README.md` descreve a camada de interceptação como um flywheel de
``AuditLog``: *alerta → override → desfecho*. Medido em 2026-09-12, na cunha de
glosa ligada sobre guias reais de staging, o flywheel tinha **duas pernas de três**:

    glosa_alert_raised  →  6 linhas no AuditLog
    override            →  AuditLog antes: 429 | depois: 429 | linhas novas: 0

O override ficava durável no próprio alerta (``acknowledged_by``,
``override_reason``, ``acknowledged_at``) e o endpoint escrevia um ``logger.info``.
Nada chegava à tabela de auditoria.

**Por que isso não é uma linha faltando.** Override é o sinal mais valioso dos três:
é o humano discordando da máquina, com motivo escrito. Se o que aprende com o
flywheel lê ``AuditLog``, esse sinal é invisível para ele — e sobra a máquina
aprendendo só com os próprios acertos, que é o oposto de um flywheel.

O registro vive em ``GlosaSafetyAlert.acknowledge()``, não na view, de propósito:
qualquer caminho que reconheça um alerta — endpoint, management command, shell de
manutenção — passa por ali. Foi justamente por um override feito fora da view que a
lacuna apareceu.

Contra o código anterior à emenda este teste falha; depois, passa.
"""

from __future__ import annotations

import datetime

from apps.billing.models import GlosaSafetyAlert, InsuranceProvider, TISSGuide
from apps.core.models import AuditLog, User
from apps.emr.models import Encounter, Patient, Professional
from apps.test_utils import TenantTestCase


class GlosaOverrideAuditTests(TenantTestCase):
    """Reconhecer um alerta bloqueante tem de deixar rastro auditável."""

    def setUp(self) -> None:
        super().setUp()
        self.user = User.objects.create_user(
            email="glosa-override@test.com",
            full_name="Faturista Teste",
            password="Str0ng!Pass#2024",
        )
        profissional = Professional.objects.create(
            user=self.user, council_type="CRM", council_number="90008", council_state="SP"
        )
        paciente = Patient.objects.create(
            full_name="Paciente Override",
            cpf="000.000.000-08",
            birth_date=datetime.date(1990, 8, 1),
            gender="F",
        )
        encontro = Encounter.objects.create(patient=paciente, professional=profissional)
        provider = InsuranceProvider.objects.create(
            name="Operadora Override (FICTÍCIA — staging)", ans_code="000008"
        )
        self.guia = TISSGuide.objects.create(
            patient=paciente,
            executor=profissional,
            encounter=encontro,
            provider=provider,
            guide_type="consulta",
            status="draft",
            competency=datetime.date.today().replace(day=1).strftime("%Y-%m"),
        )
        self.alerta = GlosaSafetyAlert.objects.create(
            guide=self.guia,
            check_code="not_in_table",
            severity=GlosaSafetyAlert.Severity.BLOCK,
            status=GlosaSafetyAlert.Status.FLAGGED,
            source="engine",
            message="Procedimento não consta na tabela de preços vigente da operadora.",
            ans_glosa_code="01",
        )

    def test_override_escreve_no_auditlog(self) -> None:
        """A perna que faltava do flywheel."""
        antes = AuditLog.objects.count()
        motivo = "contrato aditivo assinado em 01/09, procedimento passa a ser coberto"

        self.alerta.acknowledge(self.user, motivo)

        self.assertEqual(
            AuditLog.objects.count(),
            antes + 1,
            "override de glosa não deixou linha no AuditLog — o flywheel fica sem a perna do override",
        )
        linha = AuditLog.objects.order_by("-created_at").first()
        assert linha is not None
        self.assertEqual(linha.user_id, self.user.id)
        self.assertEqual(linha.resource_id, str(self.guia.id))
        self.assertIn(
            motivo,
            str(linha.new_data),
            "o MOTIVO é o sinal que vale — sem ele o registro não ensina nada",
        )

    def test_override_registra_o_que_foi_contornado(self) -> None:
        """Não basta dizer que houve override: tem de dizer override de quê."""
        self.alerta.acknowledge(self.user, "motivo suficientemente longo para um bloqueio")

        linha = AuditLog.objects.order_by("-created_at").first()
        assert linha is not None
        dados = str(linha.new_data)
        self.assertIn("not_in_table", dados, "o check contornado tem de estar no registro")
        self.assertIn("01", dados, "o código ANS contornado tem de estar no registro")

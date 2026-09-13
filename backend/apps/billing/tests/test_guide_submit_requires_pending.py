"""
Guarda: `submit` respeita o ciclo de vida da guia (ordem 010, issue #213).

**O defeito.** `TISSGuideViewSet.submit` aceitava guia em `draft` e gravava `submitted`
direto, pulando `pending` — contra a própria docstring, que diz
``"(status: pending → submitted)"``. Uma guia virava **"Enviada"** sem ter entrado em
lote, sem ter sido validada contra o XSD oficial da ANS e sem ninguém tê-la declarado
pronta.

`submitted` não é rótulo inofensivo:

* entra em `_ACTIVE_GUIDE_STATUSES` (`services/glosa_safety.py:85`), contando como
  apresentada para a checagem `duplicate` da cunha de glosa — inclusive uma guia que
  nunca saiu em XML nenhum;
* entra no denominador da taxa de glosa (`docs/PLAN_SPRINT10.md:83`), que passa a medir
  sobre envios que não aconteceram.

Era a porta dos fundos que anulava o que a ordem 009 construiu: `draft → pending` como
ato explícito e auditado, `pending → submitted` no fechamento do lote.

Contra o código anterior à ordem 010 o primeiro teste falha por asserção — hoje o
endpoint devolve 200 e grava `submitted` sobre um rascunho.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from apps.billing.models import InsuranceProvider, TISSGuide
from apps.core.models import AuditLog, User
from apps.emr.models import Encounter, Patient, Professional
from apps.test_utils import TenantTestCase


class GuideSubmitRequiresPendingTests(TenantTestCase):
    """Só guia declarada pronta pode ser enviada."""

    def setUp(self) -> None:
        super().setUp()
        self.user = User.objects.create_user(
            email="submit@test.com", full_name="Faturista Submit", password="Str0ng!Pass#2024"
        )
        profissional = Professional.objects.create(
            user=self.user, council_type="CRM", council_number="90010", council_state="SP"
        )
        paciente = Patient.objects.create(
            full_name="Paciente Submit",
            cpf="000.000.000-10",
            birth_date=datetime.date(1990, 10, 1),
            gender="F",
        )
        encontro = Encounter.objects.create(patient=paciente, professional=profissional)
        provider = InsuranceProvider.objects.create(
            name="Operadora Submit (FICTÍCIA — staging)", ans_code="000010"
        )
        self.guia = TISSGuide.objects.create(
            patient=paciente,
            executor=profissional,
            encounter=encontro,
            provider=provider,
            guide_type="consulta",
            status="draft",
            competency=datetime.date.today().replace(day=1).strftime("%Y-%m"),
            total_value=Decimal("100.00"),
            insured_card_number="FICTICIA-STAGING",
        )

    def test_enviar_rascunho_e_recusado(self) -> None:
        """Guia em rascunho não pode ser enviada, e a recusa diz o que fazer."""
        from django.core.exceptions import ValidationError

        from apps.billing.services.batch_lifecycle import marcar_enviada

        with self.assertRaises(ValidationError) as ctx:
            marcar_enviada(guia=self.guia, actor=self.user)

        mensagem = " ".join(ctx.exception.messages)
        self.assertIn(
            "pronta",
            mensagem.lower(),
            "a recusa não diz o que falta — quem recebe o erro precisa saber que o "
            "caminho é declarar a guia pronta antes",
        )
        self.guia.refresh_from_db()
        self.assertEqual(
            self.guia.status,
            "draft",
            "a guia foi enviada apesar da recusa — era a porta dos fundos da issue #213",
        )

    def test_enviar_pendente_funciona_e_e_auditado(self) -> None:
        """Guia declarada pronta é enviada, e o envio deixa rastro consultável."""
        from apps.billing.services.batch_lifecycle import marcar_enviada, marcar_pronta_para_envio

        marcar_pronta_para_envio(guia=self.guia, actor=self.user)
        antes = AuditLog.objects.filter(action="guide_submitted").count()

        marcar_enviada(guia=self.guia, actor=self.user)

        self.guia.refresh_from_db()
        self.assertEqual(self.guia.status, "submitted")
        depois = AuditLog.objects.filter(action="guide_submitted").count()
        self.assertEqual(depois, antes + 1, "o envio não deixou linha no AuditLog")
        linha = AuditLog.objects.filter(action="guide_submitted").order_by("-created_at").first()
        assert linha is not None
        self.assertEqual(linha.resource_type, "tiss_guide")
        self.assertEqual((linha.old_data or {}).get("status"), "pending")
        self.assertEqual((linha.new_data or {}).get("status"), "submitted")
        self.assertEqual(
            (linha.new_data or {}).get("guide_number"),
            self.guia.guide_number,
            "a linha tem de dizer QUAL guia foi enviada",
        )

    def test_endpoint_recusa_rascunho_com_400_nomeando_o_caminho(self) -> None:
        """Pelo HTTP: 400 com código próprio e o nome do endpoint que destrava."""
        from django.urls import reverse
        from rest_framework.test import APIClient

        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        client = APIClient()
        # `SERVER_NAME` com o domínio do tenant, como o resto da suíte já faz
        # (`test_billing.py:212`). Sem ele o middleware do django-tenants não
        # resolve tenant nenhum, a requisição cai no `public` — 404 — e, pior, a
        # conexão FICA no `public`: os testes seguintes da mesma classe morrem com
        # `relation "emr_professional" does not exist`, apontando para um problema
        # de migration que não existe. Perdi uma rodada nisso.
        client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        client.force_authenticate(user=self.user)

        url = reverse("guide-submit", args=[self.guia.pk])
        resp = client.post(url, {}, format="json")

        self.assertEqual(
            resp.status_code,
            400,
            f"esperava 400 ao enviar rascunho, veio {resp.status_code}: "
            f"{getattr(resp, 'data', None)}",
        )
        self.assertEqual((resp.data or {}).get("code"), "guide_not_ready")
        self.assertIn(
            "marcar-pronta",
            str((resp.data or {}).get("detail", "")),
            "a resposta não nomeia o endpoint que destrava — erro que não diz o próximo "
            "passo obriga quem recebe a ler o código",
        )
        self.guia.refresh_from_db()
        self.assertEqual(self.guia.status, "draft")

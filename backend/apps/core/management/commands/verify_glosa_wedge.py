"""
Management command: verify_glosa_wedge  (core — ordem 007)
===========================================================
Exercita a **cunha de interceptação de glosa** sobre as guias TISS que existem de
verdade no tenant, e relata o que ela decidiu. É para a cunha o que o
``verify_revenue_chain`` é para a cadeia: a versão executável de uma afirmação que
até agora só existia em teste.

Por que existe
--------------
Sete cunhas foram construídas com a flag desligada, e a de glosa nunca julgou uma
guia real: medido em 2026-09-12, ``billing_glosasafetyalert`` tinha **0 linhas**. O
motor tem teste e nunca viu dado de operação.

Isso mudou porque a ordem 006 produziu as primeiras guias TISS deste sistema fora de
fixtura. A Prioridade 2 destravou a Prioridade 4 — exatamente na ordem que o
``.maestro/INTENT.md`` prevê.

O que ele mede, e o que NÃO mede
---------------------------------
Mede o **julgamento** (o motor determinístico diz o quê, com qual código ANS) e a
**decisão de bloqueio** (``blocking_glosa_alerts_for_guides``), que é a mesma que o
endpoint de fechar lote consulta antes de devolver 409.

**Não** exercita o HTTP: o 409 é a renderização dessa decisão pela view, e chamá-lo
exigiria credencial de staging, que não existe (mesma lacuna registrada na ordem 001,
passo 4.4). Onde a prova para, está dito — não se conclui HTTP a partir de serviço.

O motor é determinístico por construção (``glosa_checker``: "NO LLM, NO network, NO
clock"), então este comando não invoca modelo nenhum, e o resultado é reprodutível.

Uso
---
    python manage.py verify_glosa_wedge --tenant demo             # só relata
    python manage.py verify_glosa_wedge --tenant demo --evaluate  # avalia e persiste
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Roda a cunha de glosa sobre as guias reais do tenant e relata o veredicto (ordem 007)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--tenant", required=True)
        parser.add_argument(
            "--demo-uncovered",
            action="store_true",
            help=(
                "Cria uma guia faturando um TUSS que NÃO está na tabela de preço ativa — "
                "o cenário que a cunha BLOQUEIA (not_in_table / ANS 01). É o único "
                "veredicto bloqueante alcançável hoje: `duplicate` exige guia já "
                "APRESENTADA, e as de staging estão em draft."
            ),
        )
        parser.add_argument(
            "--evaluate",
            action="store_true",
            help="Avalia as guias e PERSISTE os alertas (sem isto, só lê o que já existe)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        from django_tenants.utils import tenant_context

        from apps.core.models import Tenant

        try:
            tenant = Tenant.objects.get(schema_name=options["tenant"])
        except Tenant.DoesNotExist as exc:
            raise CommandError(f"tenant inexistente: {options['tenant']}") from exc

        with tenant_context(tenant):
            if options["demo_uncovered"]:
                self._guia_nao_coberta()
            self._rodar(bool(options["evaluate"]))

    def _rodar(self, avaliar: bool) -> None:
        from apps.billing.models import GlosaSafetyAlert, TISSGuide
        from apps.billing.services.glosa_safety import GlosaSafetyService
        from apps.core.models import User

        ligada = GlosaSafetyService.is_enabled()
        self.stdout.write(f"flag glosa_safety : {'ON' if ligada else 'OFF'}")
        guias = list(TISSGuide.objects.all().order_by("guide_number"))
        self.stdout.write(f"guias no tenant   : {len(guias)}")
        self.stdout.write(f"alertas hoje      : {GlosaSafetyAlert.objects.count()}")

        if not guias:
            raise CommandError("nenhuma guia no tenant — rode `verify_revenue_chain --create`")

        if avaliar:
            if not ligada:
                raise CommandError(
                    "flag glosa_safety está OFF neste tenant: o service é no-op por desenho. "
                    "Ligue a flag antes, e desligue depois (ordem 007, passos 1 e 5)."
                )
            usuario = User.objects.filter(is_active=True).order_by("id").first()
            if usuario is None:
                raise CommandError("nenhum usuário ativo para atribuir a avaliação")
            servico = GlosaSafetyService(requesting_user=usuario)
            self.stdout.write("")
            self.stdout.write("avaliando com gate='batch_close' (o mesmo do fechamento de lote)")
            for guia in guias:
                servico.evaluate_guide(guia, gate="batch_close")
                self.stdout.write(f"  {guia.guide_number} avaliada")

        self.stdout.write("")
        self.stdout.write("veredictos")
        alertas = GlosaSafetyAlert.objects.select_related("guide").order_by(
            "guide__guide_number", "check_code"
        )
        if not alertas:
            self.stdout.write("  (nenhum alerta — a cunha não achou o que interceptar)")
        for a in alertas:
            self.stdout.write(
                f"  {a.guide.guide_number}  {a.check_code:<14} ANS {a.ans_glosa_code:<5} "
                f"[{a.severity}/{a.status}]"
            )
            self.stdout.write(f"      {a.message}")

        # A MESMA consulta que o endpoint de fechar lote faz antes de devolver 409.
        bloqueantes = GlosaSafetyService.blocking_glosa_alerts_for_guides([g.id for g in guias])
        self.stdout.write("")
        # O retorno é `[(guide, [alerts])]` — o payload por guia do 409, não uma
        # lista de alertas. Li o contrato depois de assumir errado.
        self.stdout.write(f"guias que bloqueariam o fechamento do lote: {len(bloqueantes)}")
        for guia_bloq, alertas_bloq in bloqueantes:
            codigos = ", ".join(f"{a.check_code}/ANS {a.ans_glosa_code}" for a in alertas_bloq)
            self.stdout.write(f"  {guia_bloq.guide_number}  {codigos}")
        self.stdout.write("")
        self.stdout.write(
            "soft-stop: com alerta bloqueante aberto, o endpoint de fechar lote devolve 409 "
            "com as guias ofensoras e NÃO fecha o lote (billing/views.py, gate batch_close)."
        )

    def _guia_nao_coberta(self) -> None:
        """Guia faturando procedimento fora da tabela — o caso que a cunha bloqueia.

        Não é cenário artificial: é o erro de faturamento mais comum que existe.
        O catálogo tem 54.139 TUSS e a tabela negociada tem 1; cobrar algo de fora
        dela é exatamente o que a operadora glosa com "procedimento não coberto".
        """
        import datetime
        from decimal import Decimal

        from apps.billing.models import (
            InsuranceProvider,
            PriceTable,
            PriceTableItem,
            TISSGuide,
            TISSGuideItem,
        )
        from apps.core.models import TUSSCode
        from apps.emr.models import Encounter

        provider = InsuranceProvider.objects.first()
        tabela = PriceTable.objects.filter(is_active=True).first()
        encontro = Encounter.objects.select_related("patient", "professional").first()
        if not (provider and tabela and encontro):
            raise CommandError("cadastro incompleto — rode `seed_revenue_staging` antes")

        cobertos = set(
            PriceTableItem.objects.filter(table=tabela).values_list("tuss_code_id", flat=True)
        )
        fora = (
            TUSSCode.objects.filter(active=True).exclude(id__in=cobertos).order_by("code").first()
        )
        if fora is None:
            raise CommandError("todo TUSS ativo está na tabela — não há caso não-coberto")

        guia = TISSGuide.objects.create(
            patient=encontro.patient,
            executor=encontro.professional,
            encounter=encontro,
            provider=provider,
            price_table=tabela,
            guide_type="consulta",
            status="draft",
            competency=datetime.date.today().replace(day=1).strftime("%Y-%m"),
            total_value=Decimal("100.00"),
            insured_card_number="FICTICIA-STAGING",
        )
        TISSGuideItem.objects.create(
            guide=guia,
            tuss_code=fora,
            description=fora.description[:200],
            quantity=1,
            unit_value=Decimal("100.00"),
            total_value=Decimal("100.00"),
        )
        self.stdout.write(
            f"guia não-coberta criada: {guia.guide_number} com TUSS {fora.code} "
            f"(fora da tabela '{tabela.name}')"
        )

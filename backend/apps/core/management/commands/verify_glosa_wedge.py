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
        parser.add_argument(
            "--prove-block",
            action="store_true",
            help=(
                "Exercita o soft-stop DE VERDADE, pelos endpoints HTTP: fecha um lote "
                "com alerta bloqueante aberto (espera 409), faz o override (espera a "
                "linha no AuditLog) e fecha de novo (espera sucesso). Sem isto o "
                "comando só DESCREVE o gate — e descrição não é prova."
            ),
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
            if options["prove_block"]:
                self._provar_bloqueio(tenant)

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

    def _provar_bloqueio(self, tenant: Any) -> None:
        """Passo 3 da ordem 007: o lote com alerta aberto é bloqueado, e o override é auditado.

        Passa pelos ENDPOINTS, não pelo service. A diferença não é cerimônia: o
        gate de fechamento vive em `billing/views.py` e o registro de override
        vive em `GlosaSafetyAlert.acknowledge()`. Chamar o service direto
        provaria o segundo e pularia o primeiro — e foi exatamente um override
        feito fora da view que expôs, na primeira rodada desta ordem, que o
        AuditLog não recebia nada.
        """
        from django.urls import reverse
        from rest_framework.test import APIClient

        from apps.billing.models import GlosaSafetyAlert, TISSBatch
        from apps.billing.services.batch_lifecycle import marcar_pronta_para_envio
        from apps.core.models import AuditLog, User

        self.stdout.write("")
        self.stdout.write("prova do soft-stop (endpoints reais)")

        # Escolhe um alerta cuja guia ainda POSSA entrar num lote.
        #
        # Ordenar por `guide__guide_number` crescente pegava a guia mais ANTIGA, e em
        # staging as antigas já estão em lote fechado. `lote.guides.add()` então
        # levantava `ValidationError: já consta no lote ... Double-billing bloqueado`
        # — a guarda de dupla apresentação funcionando, sobre um cenário que este
        # harness montou errado. Excluir as já finalizadas e pegar a guia mais NOVA
        # resolve: a que `--demo-uncovered` acabou de criar é a que se quer exercitar.
        ja_finalizadas = TISSBatch.objects.filter(status__in=["closed", "submitted"]).values_list(
            "guides__pk", flat=True
        )
        alerta = (
            GlosaSafetyAlert.objects.select_related("guide")
            .filter(severity="block", status="flagged")
            .exclude(guide__pk__in=[pk for pk in ja_finalizadas if pk is not None])
            .order_by("-guide__guide_number")
            .first()
        )
        if alerta is None:
            raise CommandError(
                "nenhum alerta BLOQUEANTE aberto sobre guia que ainda possa ser "
                "lotada. Rode antes: verify_glosa_wedge --tenant <t> "
                "--demo-uncovered --evaluate"
            )
        guia = alerta.guide
        self.stdout.write(
            f"  alerta aberto : {alerta.check_code} ANS {alerta.ans_glosa_code} "
            f"na guia {guia.guide_number}"
        )

        lote = TISSBatch.objects.filter(guides=guia, status="open").first()
        if lote is None:
            lote = TISSBatch.objects.create(provider=guia.provider)
            lote.guides.add(guia)
            self.stdout.write(f"  lote criado   : {lote.batch_number or lote.pk}")
        else:
            self.stdout.write(f"  lote existente: {lote.batch_number or lote.pk}")

        # Escolhe por CAPACIDADE, não por flag de superusuário: `IsFaturistaOrAdmin`
        # aceita superuser OU quem tem `billing.read`/`billing.write`. Filtrar por
        # `is_superuser` reprovava num tenant que simplesmente não tem nenhum — e
        # reprovava por endereço errado, dizendo "sem superusuário" quando o que
        # o endpoint quer é o papel.
        # Preferência explícita: quem ESCREVE em billing. Fechar lote e contornar
        # alerta são escrita; pegar o primeiro que tem `billing.read` daria um
        # usuário com menos direito do que a operação exige e provaria menos.
        usuario = None
        for teste in (
            lambda u: u.is_superuser,
            lambda u: u.has_role_permission("billing.write"),
            lambda u: u.has_role_permission("billing.read"),
        ):
            for candidato in User.objects.filter(is_active=True).order_by("id"):
                if teste(candidato):
                    usuario = candidato
                    break
            if usuario is not None:
                break
        if usuario is None:
            raise CommandError(
                "nenhum usuário ativo com billing.read/billing.write (nem superusuário) "
                "para exercitar os endpoints — o gate é IsFaturistaOrAdmin"
            )
        self.stdout.write(f"  usuário       : {usuario.email}")

        dominio = tenant.domains.filter(is_primary=True).first()
        if dominio is None:
            raise CommandError(f"tenant {tenant.schema_name} sem domínio primário")

        # `secure=True` em toda chamada: production.py liga SECURE_SSL_REDIRECT, e
        # sem isso o test client leva 301 do middleware e nunca alcança a view —
        # o comando reprovaria dizendo "esperava 409, veio 301", culpando o gate
        # por um redirect de esquema.
        client = APIClient()
        client.force_authenticate(user=usuario)
        host = dominio.domain

        url_close = reverse("batch-close", args=[lote.pk])

        # Portão 1 — rascunho (ordem 009). O fechamento estrito barra ANTES de
        # julgar glosa, então este harness passa pelos dois portões em ordem. Até a
        # ordem 009 ele só conhecia o segundo, e quebrou quando o primeiro nasceu:
        # exercitar um gate com dado que o gate anterior recusa não prova o segundo.
        r0 = client.post(url_close, {}, format="json", HTTP_HOST=host, secure=True)
        self.stdout.write(f"  POST {url_close} (guia em rascunho) -> {r0.status_code}")
        if r0.status_code != 409 or (r0.data or {}).get("code") != "batch_has_draft_guides":
            raise CommandError(
                f"esperava 409 batch_has_draft_guides com a guia em rascunho, veio "
                f"{r0.status_code}: {getattr(r0, 'data', None)}"
            )
        self.stdout.write(f"    409 nomeando o rascunho: {(r0.data or {}).get('guides')}")
        lote.refresh_from_db()
        if lote.status != "open":
            raise CommandError(f"o lote fechou apesar do rascunho: {lote.status}")

        marcar_pronta_para_envio(guia=guia, actor=usuario)
        guia.refresh_from_db()
        self.stdout.write(f"  guia declarada pronta -> {guia.status}")

        # Portão 2 — glosa bloqueante.
        r1 = client.post(url_close, {}, format="json", HTTP_HOST=host, secure=True)
        self.stdout.write(f"  POST {url_close} -> {r1.status_code}")
        if r1.status_code != 409:
            raise CommandError(
                f"esperava 409 com alerta bloqueante aberto, veio {r1.status_code}: "
                f"{getattr(r1, 'data', None)}"
            )
        ofensoras = (r1.data or {}).get("guides") or (r1.data or {}).get("guias") or r1.data
        self.stdout.write(f"    409 com as guias ofensoras: {ofensoras}")
        lote.refresh_from_db()
        if lote.status != "open":
            raise CommandError(f"o lote mudou de status apesar do 409: {lote.status}")
        self.stdout.write(f"    lote continua '{lote.status}' — o soft-stop não fechou nada")

        antes = AuditLog.objects.filter(action="glosa_alert_overridden").count()
        url_ack = reverse("glosa-safety-alert-acknowledge", args=[alerta.pk])
        motivo = "ordem 007 passo 3: procedimento acordado fora da tabela vigente (staging)"
        r2 = client.post(
            # O corpo é `{"reason": ...}` — o campo do MODELO chama-se
            # `override_reason`, e mandar esse nome aqui produz um 400 enganoso:
            # "o motivo deve ter pelo menos 10 caracteres" sobre um motivo longo,
            # porque a view lê `reason` e recebe string vazia.
            url_ack,
            {"reason": motivo},
            format="json",
            HTTP_HOST=host,
            secure=True,
        )
        self.stdout.write(f"  POST {url_ack} -> {r2.status_code}")
        if r2.status_code not in (200, 201):
            raise CommandError(f"override recusado ({r2.status_code}): {getattr(r2, 'data', None)}")
        depois = AuditLog.objects.filter(action="glosa_alert_overridden").count()
        self.stdout.write(f"    AuditLog glosa_alert_overridden: {antes} -> {depois}")
        if depois != antes + 1:
            raise CommandError(
                "o override NÃO gerou linha no AuditLog — sem isso não há flywheel "
                "alerta -> override -> desfecho (ordem 007, emenda do Imediato)"
            )
        linha = (
            AuditLog.objects.filter(action="glosa_alert_overridden").order_by("-created_at").first()
        )
        assert linha is not None
        self.stdout.write(f"    linha: resource={linha.resource_type}/{linha.resource_id}")
        self.stdout.write(f"    old_data={linha.old_data}")
        self.stdout.write(f"    new_data={linha.new_data}")

        r3 = client.post(url_close, {}, format="json", HTTP_HOST=host, secure=True)
        self.stdout.write(f"  POST {url_close} (apos override) -> {r3.status_code}")
        if r3.status_code >= 400:
            raise CommandError(
                f"apos o override o fechamento ainda falhou ({r3.status_code}): "
                f"{getattr(r3, 'data', None)}"
            )
        lote.refresh_from_db()
        self.stdout.write(f"    lote agora: status={lote.status} total_value={lote.total_value}")
        self.stdout.write("")
        self.stdout.write(
            "PROVADO: alerta aberto bloqueia (409), override audita, fechamento libera"
        )

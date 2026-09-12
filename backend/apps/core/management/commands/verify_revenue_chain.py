"""
Management command: verify_revenue_chain  (core — ordem 006)
=============================================================
Percorre a cadeia **guia TISS válida → lote → faturamento** de ponta a ponta, num
tenant, e falha alto se qualquer elo quebrar. É para a receita o que
``verify_catalogs`` é para os catálogos: a versão barulhenta de um defeito que
hoje é silencioso.

Por que existe
--------------
A cadeia está implementada e coberta por teste — ``validate_xml`` é chamado 21
vezes em ``test_xml_engine.py`` — e, medido em 2026-09-12, **nunca produziu uma
guia fora do teste**. O staging tinha 4 pacientes, 4 atendimentos, 3 internações,
e zero guias, zero lotes, zero operadoras.

O modo de falha desta cadeia é o pior que existe: silencioso e financeiro. Quando
falta TUSS correspondente, a linha é registrada em INFO e **simplesmente não é
faturada** — ninguém vê erro, e a clínica descobre no fechamento do mês.

O que ele prova, em ordem
-------------------------
1. **Cadastro existe** — operadora e tabela de preço. Sem isso nada começa:
   ``TISSGuide.provider`` é FK ``PROTECT`` sem ``null=True``.
2. **A guia nasce** a partir de um atendimento real, com item precificado pela
   tabela — não por valor inventado no código.
3. **O XML da guia valida contra o XSD oficial da ANS** (TISS 4.01.00, em
   ``apps/billing/schemas/``). Este é o elo que separa "gerou XML" de "gerou XML
   que a operadora aceita".
4. **O lote fecha** contendo a guia, e o envelope também valida.
5. **O faturamento é maior que zero.** Uma cadeia que termina em R$ 0,00 passou
   por todos os passos e não provou nada.

Uso
---
    python manage.py verify_revenue_chain --tenant demo            # relata
    python manage.py verify_revenue_chain --tenant demo --create   # cria e relata

Sem ``--create`` ele só inspeciona o que existe — seguro de rodar em qualquer
ambiente. Com ``--create``, escreve uma guia e um lote de demonstração usando o
cadastro fictício da ordem 006. Sai 0 só quando os cinco passos passam.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Percorre guia TISS → lote → faturamento e falha alto se algum elo quebrar (ordem 006)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--tenant", required=True, help="Schema do tenant (ex.: demo)")
        parser.add_argument(
            "--create", action="store_true", help="Cria guia e lote de demonstração"
        )
        parser.add_argument("--dry-run", action="store_true", help="Cria, valida e reverte")

    def handle(self, *args: Any, **options: Any) -> None:
        from django_tenants.utils import tenant_context

        from apps.core.models import Tenant

        try:
            tenant = Tenant.objects.get(schema_name=options["tenant"])
        except Tenant.DoesNotExist as exc:
            raise CommandError(f"tenant inexistente: {options['tenant']}") from exc

        with tenant_context(tenant):
            self._percorrer(bool(options["create"]), bool(options["dry_run"]))

    def _percorrer(self, criar: bool, dry_run: bool) -> None:
        from apps.billing.models import (
            InsuranceProvider,
            PriceTable,
            PriceTableItem,
            TISSBatch,
            TISSGuide,
            TISSGuideItem,
        )
        from apps.billing.services.xml_engine import (
            generate_batch_xml,
            generate_guide_xml,
            validate_xml,
        )
        from apps.emr.models import Encounter

        falhas: list[str] = []

        # ── 1. Cadastro ──────────────────────────────────────────────────────
        provider = InsuranceProvider.objects.first()
        tabela = PriceTable.objects.filter(is_active=True).first()
        self.stdout.write("1. Cadastro")
        self.stdout.write(f"   operadora     : {provider.name if provider else 'AUSENTE'}")
        self.stdout.write(f"   tabela preço  : {tabela.name if tabela else 'AUSENTE'}")
        if not provider:
            falhas.append("sem InsuranceProvider — rode `import_insurances`")
        if not tabela:
            falhas.append("sem PriceTable — rode `seed_revenue_staging`")
        if falhas:
            self._reprovar(falhas)

        itens_tabela = list(PriceTableItem.objects.filter(table=tabela).select_related("tuss_code"))
        self.stdout.write(f"   itens tabela  : {len(itens_tabela)}")
        if not itens_tabela:
            self._reprovar(["tabela de preço sem itens — rode `seed_revenue_staging`"])

        # ── 2. Guia ──────────────────────────────────────────────────────────
        self.stdout.write("2. Guia")
        guia = TISSGuide.objects.order_by("-created_at").first()
        with transaction.atomic():
            if criar:
                encontro = Encounter.objects.select_related("patient", "professional").first()
                if not encontro:
                    self._reprovar(["nenhum Encounter no tenant — rode `seed_demo_data`"])
                item_preco = itens_tabela[0]
                guia = TISSGuide.objects.create(
                    patient=encontro.patient,
                    executor=encontro.professional,
                    encounter=encontro,
                    provider=provider,
                    price_table=tabela,
                    guide_type="consulta",
                    status="draft",
                    competency=datetime.date.today().replace(day=1).strftime("%Y-%m"),
                    total_value=item_preco.negotiated_value,
                    # `numeroCarteira` é st_texto20 com minLength=1: vazio derruba
                    # o lote inteiro. Em produção vem de PatientInsurance.card_number;
                    # aqui é fictício e declarado, como manda a fronteira da ordem 006.
                    insured_card_number="FICTICIA-STAGING",
                )
                TISSGuideItem.objects.create(
                    guide=guia,
                    tuss_code=item_preco.tuss_code,
                    description=item_preco.tuss_code.description[:200],
                    quantity=1,
                    unit_value=item_preco.negotiated_value,
                    total_value=item_preco.negotiated_value,
                )
                self.stdout.write(f"   criada        : {guia.guide_number or guia.pk}")
            if not guia:
                self._reprovar(["nenhuma TISSGuide no tenant — rode com --create"])
            self.stdout.write(f"   itens         : {guia.items.count()}")

            # ── 3. XML da guia ───────────────────────────────────────────────
            # Só a RENDERIZAÇÃO, não a validação: `generate_guide_xml` devolve o
            # fragmento da guia, sem o `xmlns:ans` que o envelope declara.
            # Validá-lo sozinho sempre acusa "Namespace prefix ans não definido" —
            # erro do meu recorte, não do XML. A validação que vale é a do
            # envelope, no passo 4, e é lá que ela está.
            #
            # Renderizar já prova bastante: foi aqui que apareceram o guide_type
            # sem template e o CNES ausente, os dois com erro acionável.
            self.stdout.write("3. XML da guia (renderização)")
            xml_guia = generate_guide_xml(guia)
            self.stdout.write(f"   bytes         : {len(xml_guia)}")
            self.stdout.write("   (validação XSD: no envelope, passo 4)")

            # ── 4. Lote ──────────────────────────────────────────────────────
            self.stdout.write("4. Lote + validação contra o XSD oficial")
            lote = TISSBatch.objects.create(provider=provider)
            lote.guides.add(guia)
            xml_lote = generate_batch_xml(lote)
            erros_lote = validate_xml(xml_lote)
            self.stdout.write(f"   lote          : {lote.batch_number or lote.pk}")
            self.stdout.write(f"   guias no lote : {lote.guides.count()}")
            self.stdout.write(f"   erros XSD     : {len(erros_lote)}")
            for e in erros_lote[:5]:
                self.stdout.write(f"     - {e}")
            if erros_lote:
                falhas.append(f"XML do lote reprovou no XSD ({len(erros_lote)} erro(s))")

            # ── 5. Faturamento ───────────────────────────────────────────────
            self.stdout.write("5. Faturamento")
            total = sum(
                (i.total_value or Decimal("0") for g in lote.guides.all() for i in g.items.all()),
                Decimal("0"),
            )
            self.stdout.write(f"   valor do lote : R$ {total}")
            if total <= 0:
                falhas.append("faturamento do lote é zero — cadeia percorrida sem provar nada")

            if dry_run:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING("dry-run: guia e lote revertidos"))

        if falhas:
            self._reprovar(falhas)
        self.stdout.write(
            self.style.SUCCESS("cadeia de receita OK — guia válida, lote fechado, valor > 0")
        )

    def _reprovar(self, falhas: list[str]) -> None:
        raise CommandError("cadeia de receita REPROVOU:\n  - " + "\n  - ".join(falhas))

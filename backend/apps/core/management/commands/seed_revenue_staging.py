"""
Management command: seed_revenue_staging  (core — ordem 006)
=============================================================
Cria a **tabela de preço fictícia** que liga a operadora de staging aos códigos
TUSS já carregados, para que a cadeia *guia TISS válida → lote → faturamento*
possa ser percorrida num ambiente novo **por comando, sem `INSERT` à mão**.

Por que existe
--------------
Medido em 2026-09-12 no staging: 4 pacientes, 4 atendimentos, 3 internações — e
**zero** operadoras, **zero** tabelas de preço, **zero** guias, **zero** lotes.
A cadeia de receita está implementada e coberta por teste (``validate_xml`` é
chamado 21 vezes em ``test_xml_engine.py``), e nunca produziu uma guia fora do
teste. O que faltava não era código: era o cadastro.

``import_insurances`` já resolve a operadora. Para tabela de preço não havia
comando nenhum — só `INSERT`, que não é repetível e não sobrevive a um ambiente
novo. Esta é a peça que faltava.

O dado é fictício, e isso é declarado, não implícito
-----------------------------------------------------
Fronteira definida pelo Imediato na ordem 006: operadora e tabela de staging são
**fictícias e rotuladas**. O nome carrega ``(FICTÍCIA — staging)``, os valores são
**redondos** para a conta do lote ser conferível de cabeça, e o CSV diz em
comentário que não são preços praticados por ninguém.

Isto **não** conflita com ``.maestro/INTENT.md`` §Limites ("nenhum número clínico,
contratual ou ANS inventado em código"). O que a direção proíbe é fabricar
valor que se passe por real. Aqui o dado é de teste, marcado como tal na própria
string que aparece na tela, e vive num CSV de staging — não em código, não em
produção.

O que o comando NÃO faz
-----------------------
**Não inventa código TUSS.** Cada linha referencia ``core.TUSSCode`` pelo código,
e uma referência que não existe é **erro**, não um registro criado na hora: preço
de procedimento inexistente seria exatamente o número inventado que a direção
proíbe. Rode ``seed_catalogs`` antes.

**Não roda em produção.** ``ENVIRONMENT=production`` recusa, porque dado fictício
em ambiente real é pior que dado faltando — ele parece verdadeiro.

Uso
---
    python manage.py import_insurances --file scripts/staging/operadoras-staging.csv \\
        --tenant demo
    python manage.py seed_revenue_staging --tenant demo \\
        --price-csv scripts/staging/precos-staging.csv --dry-run
    python manage.py seed_revenue_staging --tenant demo \\
        --price-csv scripts/staging/precos-staging.csv

Idempotente: reexecutar atualiza os valores em vez de duplicar a tabela.
"""

from __future__ import annotations

import csv
import datetime
import logging
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

logger = logging.getLogger(__name__)

NOME_TABELA = "Tabela Didática (FICTÍCIA — staging)"


class Command(BaseCommand):
    help = "Cria a tabela de preço fictícia de staging, ligada ao catálogo TUSS real (ordem 006)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--tenant", required=True, help="Schema do tenant (ex.: demo)")
        parser.add_argument(
            "--price-csv", required=True, help="CSV de preços (ver scripts/staging/)"
        )
        parser.add_argument(
            "--provider-ans",
            default="000000",
            help="Código ANS da operadora fictícia já importada (default: 000000)",
        )
        parser.add_argument(
            "--cnes",
            default="0000000",
            help=(
                "CNES fictício para os profissionais sem cadastro (default: 0000000). "
                "Sete dígitos porque o XSD exige st_texto7; zeros porque não é um "
                "estabelecimento atribuído."
            ),
        )
        parser.add_argument(
            "--cbo",
            default="225125",
            help=(
                "CBO para profissionais sem cadastro (default: 225125, Médico clínico). "
                "É código REAL do catálogo, e deve ser: o XSD tem enumeração fechada de "
                "CBOS e rejeita qualquer coisa fora dela. CBO é taxonomia, como TUSS e "
                "CID-10 — usar o código certo não é inventar dado."
            ),
        )
        parser.add_argument("--delimiter", default=";")
        parser.add_argument("--dry-run", action="store_true", help="Valida e reverte tudo")

    def handle(self, *args: Any, **options: Any) -> None:
        ambiente = str(getattr(settings, "ENVIRONMENT", "")).lower()
        if ambiente == "production":
            raise CommandError(
                "recusado: ENVIRONMENT=production. Dado fictício em ambiente real é pior "
                "que dado faltando — ele parece verdadeiro."
            )

        caminho = Path(options["price_csv"]).expanduser()
        if not caminho.is_file():
            raise CommandError(f"CSV de preços não encontrado: {caminho}")

        from django_tenants.utils import tenant_context

        from apps.core.models import Tenant

        try:
            tenant = Tenant.objects.get(schema_name=options["tenant"])
        except Tenant.DoesNotExist as exc:
            raise CommandError(f"tenant inexistente: {options['tenant']}") from exc

        linhas = self._ler_csv(caminho, options["delimiter"])
        if not linhas:
            raise CommandError(f"CSV sem nenhuma linha de dado: {caminho}")

        with tenant_context(tenant):
            self._semear(linhas, options["provider_ans"], bool(options["dry_run"]))
            self._cnes_dos_profissionais(options["cnes"], bool(options["dry_run"]))
            self._cbo_dos_profissionais(options["cbo"], bool(options["dry_run"]))

    def _ler_csv(self, caminho: Path, delimiter: str) -> list[dict[str, str]]:
        with caminho.open(encoding="utf-8-sig", newline="") as fh:
            uteis = [ln for ln in fh if ln.strip() and not ln.lstrip().startswith("#")]
        return list(csv.DictReader(uteis, delimiter=delimiter))

    def _semear(self, linhas: list[dict[str, str]], ans: str, dry_run: bool) -> None:
        from apps.billing.models import InsuranceProvider, PriceTable, PriceTableItem
        from apps.core.models import TUSSCode

        try:
            provider = InsuranceProvider.objects.get(ans_code=ans)
        except InsuranceProvider.DoesNotExist as exc:
            raise CommandError(
                f"operadora com ans_code={ans} não existe neste tenant. "
                f"Rode antes: manage.py import_insurances "
                f"--file scripts/staging/operadoras-staging.csv --tenant <schema>"
            ) from exc

        with transaction.atomic():
            tabela, criada = PriceTable.objects.update_or_create(
                provider=provider,
                name=NOME_TABELA,
                defaults={"valid_from": datetime.date.today(), "is_active": True},
            )
            self.stdout.write(f"tabela: {tabela.name} ({'criada' if criada else 'atualizada'})")

            criados = atualizados = 0
            ausentes: list[str] = []
            for linha in linhas:
                codigo = (linha.get("tuss_code") or "").strip()
                bruto = (linha.get("negotiated_value") or "").strip()
                if not codigo:
                    continue
                try:
                    valor = Decimal(bruto)
                except (InvalidOperation, ValueError) as exc:
                    raise CommandError(f"valor inválido para TUSS {codigo}: {bruto!r}") from exc

                tuss = TUSSCode.objects.filter(code=codigo).first()
                if tuss is None:
                    # Não se cria TUSS aqui: preço de procedimento inexistente
                    # seria número inventado. Ver docstring.
                    ausentes.append(codigo)
                    continue

                _item, item_criado = PriceTableItem.objects.update_or_create(
                    table=tabela,
                    tuss_code=tuss,
                    defaults={"negotiated_value": valor},
                )
                criados += int(item_criado)
                atualizados += int(not item_criado)
                self.stdout.write(f"  {codigo}  R$ {valor}  ({tuss.description[:40]})")

            if ausentes:
                raise CommandError(
                    "códigos TUSS inexistentes no catálogo: "
                    + ", ".join(ausentes)
                    + ". Rode `seed_catalogs` antes — este comando não inventa código."
                )

            self.stdout.write(
                self.style.SUCCESS(f"itens: {criados} criados, {atualizados} atualizados")
            )
            if dry_run:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING("dry-run: tudo revertido"))

    def _cnes_dos_profissionais(self, cnes: str, dry_run: bool) -> None:
        """Dá CNES fictício a quem não tem — sem apontar para estabelecimento real.

        O XSD exige ``CNES`` (st_texto7) e ``codigoPrestadorNaOperadora``
        (st_texto14) com ``minLength=1``, e emitir vazio **invalida o lote
        inteiro**, não só a guia — a operadora rejeita sem dizer qual prestador
        está sem cadastro.

        Por que não apontar para o catálogo real. ``Professional.cnes`` é FK para
        ``core.CNESEstablishment``, e o catálogo tem 627.706 estabelecimentos
        **reais**. Ligar um profissional fictício a um deles nomearia um hospital
        existente como executante de atendimento que nunca houve — no XML que iria
        para uma operadora. É a armadilha que o `docs/DEPTH_BACKLOG.md` §P1 já
        registra: o seed usou o CNES 2077469 rotulado como "Hospital das Clínicas"
        quando o código é do HOSP DOM ALVARENGA, e virou duplicata quando o
        catálogo real entrou.

        `0000000` não está no catálogo, então o setter de ``cnes_code`` guarda em
        ``legacy_cnes_text`` e marca ``cnes_unmatched=True`` — o registro se
        autodeclara não-casado, que é a verdade.
        """
        from apps.emr.models import Professional

        # Transação PRÓPRIA: este método roda fora do `atomic()` do `_semear`,
        # então sem isto o `--dry-run` reverteria a tabela de preço e gravaria o
        # CNES — um dry-run que escreve metade é pior que nenhum, porque ensina a
        # confiar nele.
        with transaction.atomic():
            alterados = 0
            for prof in Professional.objects.all():
                if (prof.cnes_code or "").strip():
                    continue
                prof.cnes_code = cnes
                prof.save(update_fields=["cnes", "legacy_cnes_text", "cnes_unmatched"])
                alterados += 1
            self.stdout.write(
                f"CNES fictício {cnes}: {alterados} profissional(is) sem cadastro atualizado(s)"
            )
            if dry_run:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING("dry-run: CNES revertido"))

    def _cbo_dos_profissionais(self, cbo_code: str, dry_run: bool) -> None:
        """CBO real para quem não tem — o XSD não aceita outra coisa.

        ``CBOS`` no XSD é enumeração FECHADA: o valor vazio produz
        ``SCHEMAV_CVC_ENUMERATION_VALID`` e derruba o lote. E não existe "CBO
        fictício": qualquer código fora da lista da ANS é rejeitado.

        Isso não conflita com a fronteira de dado fictício da ordem 006. CBO é
        **taxonomia de ocupação**, da mesma família de TUSS e CID-10, que este
        ambiente já carrega de fontes oficiais. Usar o código certo de "médico
        clínico" não identifica pessoa nem estabelecimento — descreve um ofício.
        O que é fictício aqui é o profissional, não a profissão.
        """
        from apps.core.models import CBOCode
        from apps.emr.models import Professional

        cbo = CBOCode.objects.filter(code=cbo_code).first()
        if cbo is None:
            raise CommandError(
                f"CBO {cbo_code} não está no catálogo. Rode `seed_catalogs` antes — "
                f"este comando não cria código de taxonomia."
            )
        with transaction.atomic():
            alterados = Professional.objects.filter(cbo__isnull=True).update(cbo=cbo)
            self.stdout.write(f"CBO {cbo_code} ({cbo.display}): {alterados} profissional(is)")
            if dry_run:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING("dry-run: CBO revertido"))

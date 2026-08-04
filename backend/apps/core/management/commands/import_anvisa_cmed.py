"""
Management command: import_anvisa_cmed  (core)
==============================================
Carrega as **apresentações** comerciais dos medicamentos —
:class:`~apps.core.catalog_models.AnvisaPresentation` — a partir da lista de
preços da CMED (Câmara de Regulação do Mercado de Medicamentos), publicada como
dado aberto pela ANVISA.

Por que um comando separado do ``import_anvisa``: as duas fontes públicas têm
granularidades diferentes. O dado aberto de medicamentos é por **produto**
(registro de 9 dígitos) e **não publica código de barras**; a lista CMED é por
**apresentação** (registro de 13 dígitos = os 9 do produto + 4 da apresentação)
e é quem publica o EAN. Como a NF-e traz o código de barras da caixa, é a
apresentação que carrega o EAN — e é ela que faz
``AnvisaProduct.by_ean`` resolver.

Ordem de execução: rode ``import_anvisa`` primeiro. Uma apresentação cujo
produto não esteja no catálogo é **pulada e reportada**, nunca cria um produto
fantasma — o nome/DCB do produto é verdade do outro dataset, e inventá-lo aqui
seria fabricar dado clínico.

Uso:
    python manage.py import_anvisa_cmed --source /caminho/anvisa_cmed.csv
    python manage.py import_anvisa_cmed --source cmed.csv --cmed-version 2026-08 --dry-run

CSV esperado (';'-delimitado, UTF-8; linhas iniciadas por '#' são comentário):
    REGISTRO;REGISTRO_PRODUTO;APRESENTACAO;EAN;PF;PMC

`REGISTRO` (13 díg) e `REGISTRO_PRODUTO` (9 díg) são obrigatórios. Preço vazio
vira **NULL** ("não publicado"), nunca 0 — R$ 0,00 num catálogo de preços seria
uma afirmação falsa. Aceita vírgula decimal, que é como a CMED publica.
"""

import csv
import logging
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.catalog_models import AnvisaPresentation, AnvisaProduct

logger = logging.getLogger(__name__)

_ALIASES = {
    "code": ("REGISTRO", "registro", "REGISTRO_APRESENTACAO", "code"),
    "product_code": ("REGISTRO_PRODUTO", "registro_produto", "PRODUTO", "product_code"),
    "presentation": ("APRESENTACAO", "apresentacao", "Apresentação", "presentation"),
    "ean": ("EAN", "ean", "EAN1", "EAN 1", "GTIN"),
    "price_pf": ("PF", "pf", "PRECO_FABRICA", "price_pf"),
    "price_pmc": ("PMC", "pmc", "price_pmc"),
}


def _pick(raw: dict, key: str) -> str:
    for alias in _ALIASES[key]:
        if alias in raw and raw[alias] is not None:
            return raw[alias].strip()
    return ""


def _price(value: str) -> Decimal | None:
    """Preço -> Decimal. Vazio/ilegível vira None, nunca 0.

    Aceita os dois formatos que chegam aqui, e a distinção importa: a vírgula é
    o que marca o formato brasileiro. Com vírgula ("13.274.524,58"), os pontos
    são separador de milhar e caem; sem vírgula ("13274524.58" — como o ETL já
    entrega), o ponto **é** o separador decimal e não pode ser tocado. Aplicar a
    regra brasileira nos dois casos multiplicava o preço por 100 a cada casa
    decimal.
    """
    value = (value or "").strip()
    if not value or value in {"-", "*", "(*)"}:
        return None
    if "," in value:
        value = value.replace(".", "").replace(",", ".")
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


class Command(BaseCommand):
    help = "Importa apresentações (EAN/preço) da lista CMED para core.AnvisaPresentation"

    def add_arguments(self, parser):
        parser.add_argument("--source", required=True, help="CSV da CMED já passado pelo ETL")
        parser.add_argument("--delimiter", default=";")
        # dest é 'cmed_version' — NÃO 'version', que colidiria com o --version
        # embutido do BaseCommand (mesma pegadinha do import_tuss).
        parser.add_argument(
            "--cmed-version", default="", help='Competência da lista, ex. "2026-08".'
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Valida e mostra o que faria, revertendo toda a escrita.",
        )

    def handle(self, *args, **options):
        source = Path(options["source"])
        if not source.exists():
            raise CommandError(f"Source file not found: {source}")

        version = options["cmed_version"]
        dry_run = options["dry_run"]
        self.stdout.write(f"Importando apresentações CMED de {source} (dry_run={dry_run}) …")

        with open(source, encoding="utf-8-sig", newline="") as fh:
            lines = [ln for ln in fh if not ln.lstrip().startswith("#")]
        if not lines:
            raise CommandError("CSV vazio ou só com comentários.")

        rows = list(csv.DictReader(lines, delimiter=options["delimiter"]))
        if not rows:
            raise CommandError("CSV tem cabeçalho mas nenhuma linha de dados.")

        # Um SELECT só para o catálogo inteiro: 10k produtos cabem em memória e
        # evitam 25k roundtrips.
        known = dict(AnvisaProduct.objects.values_list("code", "id"))

        created = updated = orphan = skipped = 0
        orphan_examples: list[str] = []
        with transaction.atomic():
            for raw in rows:
                code = _pick(raw, "code")
                product_code = _pick(raw, "product_code")
                if not code or not product_code:
                    skipped += 1
                    continue
                product_id = known.get(product_code)
                if product_id is None:
                    orphan += 1
                    if len(orphan_examples) < 5:
                        orphan_examples.append(f"{code} (produto {product_code})")
                    continue
                _, was_created = AnvisaPresentation.objects.update_or_create(
                    code=code,
                    defaults={
                        "product_id": product_id,
                        "presentation": _pick(raw, "presentation"),
                        "ean": _pick(raw, "ean"),
                        "price_pf": _price(_pick(raw, "price_pf")),
                        "price_pmc": _price(_pick(raw, "price_pmc")),
                        "version": version,
                        "active": True,
                    },
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

            if dry_run:
                transaction.set_rollback(True)

        verbo = "Importaria" if dry_run else "Importado"
        self.stdout.write(
            f"{verbo}: {created} criadas, {updated} atualizadas, "
            f"{orphan} órfãs (produto fora do catálogo), {skipped} sem registro."
        )
        if orphan_examples:
            self.stdout.write(
                "  Órfãs — rode import_anvisa antes se elas deveriam existir. "
                f"Exemplos: {', '.join(orphan_examples)}"
            )

"""
Management command: seed_catalogs  (core — ordem 002 / Prioridade 2)
====================================================================
Executa a carga dos catálogos governados a partir de um **manifesto versionado**,
chamando os ``import_*`` que já existem — este comando **não** importa nada por
conta própria e **não** conhece formato de fonte nenhum. Ele é o orquestrador que
faltava entre ``scripts/catalogs/README.md`` (o procedimento, escrito para humano)
e o banco (o resultado).

Por que existe
--------------
Até 2026-09-11 a carga vivia em dois lugares e nenhum era executável: o README ao
lado dos ETLs, e o resultado no banco que o recebeu em 04/08. Ambiente novo nascia
vazio, e ``verify_catalogs`` — o gate — só sabia dizer que estava vazio, não como
encher. A auditoria de 30/08 leu o ``grep`` ("ninguém chama os importers") e
concluiu que os catálogos nunca foram carregados; estavam, por mão humana. O que
não existia era **caminho reproduzível**. É isto.

O que este comando NÃO faz, de propósito
----------------------------------------
**Não adivinha o rótulo de versão.** ``version`` vazio no manifesto é ERRO, com o
nome do catálogo e o que preencher. O rótulo diz QUAL release da fonte oficial foi
baixada; só quem baixou sabe. Inventá-lo fabricaria proveniência — o que
``.maestro/INTENT.md`` §Limites proíbe ("nenhum número clínico, contratual ou ANS
inventado em código") e o que o docstring de ``verify_catalogs`` já explicava como
a razão de a carga não ser automática. Este comando não torna a carga automática:
torna-a **repetível**, que é outra coisa.

**Não baixa fonte.** Os CSVs saem dos ETLs em ``scripts/catalogs/`` e não são
versionados (são grandes e oficiais). Aponte ``--source-dir`` para onde eles estão.

**Não tem default de manifesto.** A imagem do backend é construída a partir de
``./backend`` — ``scripts/`` **não entra nela** (verificado em 2026-09-11 contra
``vitali-backend@sha256:da58aae3``). Um default apontando para um caminho que não
existe dentro do container seria pior que nenhum. ``--manifest`` é obrigatório.

A verificação de contagem
-------------------------
Depois de cada import, conta as linhas do modelo e compara com ``expected_rows``
do manifesto (que vem do README, catálogo por catálogo). **Falha se ficou ABAIXO
do esperado** — é exatamente o que teria gritado em 31/07, quando o CID-O entrou
``partial`` com 772 de 816 linhas e ninguém olhou o log de proveniência. Ficar
*acima* não falha: um banco já semeado tem linhas legítimas a mais (o staging tem
2.455 CBO contra 2.445 do ETL, por causa de um seed anterior de 10).

Uso
---
    # plano: o que seria feito, sem tocar em nada
    python manage.py seed_catalogs --manifest /mnt/catalogs/manifest.toml --plan

    # ensaio: valida fonte, versão e importers; o import roda com --dry-run
    python manage.py seed_catalogs --manifest /mnt/catalogs/manifest.toml \
        --source-dir /mnt/catalogs --dry-run

    # carga real
    python manage.py seed_catalogs --manifest /mnt/catalogs/manifest.toml \
        --source-dir /mnt/catalogs

    # um catálogo só (repetível)
    python manage.py seed_catalogs ... --only cid10 --only sigtap

Saída: 0 quando todo catálogo pedido carregou e bateu a contagem; 1 caso contrário.
Depois desta, rode ``verify_catalogs`` — este comando carrega, aquele atesta.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any

from django.apps import apps as django_apps
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


@dataclass(frozen=True)
class CatalogSpec:
    """Uma entrada do manifesto, já validada estruturalmente."""

    key: str
    command: str
    source_arg: str
    version_arg: str
    file: str
    model: str
    expected_rows: int
    version: str
    etl: str = ""
    blocked: str = ""


def load_manifest(path: Path) -> list[CatalogSpec]:
    """Lê o manifesto TOML e devolve as entradas na ordem declarada.

    Erro de estrutura aqui é erro do manifesto, não do ambiente: reporta o campo
    que falta e o catálogo, em vez de estourar um KeyError sem contexto.
    """
    if not path.is_file():
        raise CommandError(f"manifesto não encontrado: {path}")
    try:
        raw: dict[str, Any] = tomllib.load(path.open("rb"))
    except tomllib.TOMLDecodeError as exc:
        raise CommandError(f"manifesto inválido ({path}): {exc}") from exc

    entries = raw.get("catalog") or []
    if not entries:
        raise CommandError(f"manifesto sem nenhuma entrada [[catalog]]: {path}")

    required = ("key", "command", "source_arg", "version_arg", "file", "model", "expected_rows")
    specs: list[CatalogSpec] = []
    for index, entry in enumerate(entries):
        missing = [field for field in required if field not in entry]
        if missing:
            name = entry.get("key", f"[[catalog]] #{index + 1}")
            raise CommandError(
                f"{name}: campo(s) obrigatório(s) ausente(s) no manifesto: {', '.join(missing)}"
            )
        specs.append(
            CatalogSpec(
                key=entry["key"],
                command=entry["command"],
                source_arg=entry["source_arg"],
                version_arg=entry["version_arg"],
                file=entry["file"],
                model=entry["model"],
                expected_rows=int(entry["expected_rows"]),
                version=str(entry.get("version", "")).strip(),
                etl=str(entry.get("etl", "")),
                blocked=str(entry.get("blocked", "")),
            )
        )
    return specs


def count_rows(model_label: str) -> int:
    """Conta as linhas do modelo do catálogo (todos são SHARED/public)."""
    try:
        model = django_apps.get_model(model_label)
    except LookupError as exc:
        raise CommandError(f"modelo do manifesto não existe: {model_label}") from exc
    return int(model.objects.count())


class Command(BaseCommand):
    help = "Carrega os catálogos governados a partir do manifesto versionado (ordem 002)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--manifest",
            required=True,
            help="Caminho do manifest.toml (fica em scripts/catalogs/, que NÃO está na imagem — monte-o).",
        )
        parser.add_argument(
            "--source-dir",
            help="Diretório com os CSVs produzidos pelos ETLs. Obrigatório exceto com --plan.",
        )
        parser.add_argument(
            "--only",
            action="append",
            default=[],
            metavar="KEY",
            help="Carrega apenas este catálogo (repetível). Sem isto, todos os não bloqueados.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Propaga --dry-run para cada importer: valida e reverte, não persiste.",
        )
        parser.add_argument(
            "--plan",
            action="store_true",
            help="Só relata o que seria feito e o que falta. Não chama importer nenhum.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        manifest_path = Path(options["manifest"]).expanduser()
        specs = load_manifest(manifest_path)

        only: list[str] = options["only"]
        if only:
            known = {spec.key for spec in specs}
            unknown = sorted(set(only) - known)
            if unknown:
                raise CommandError(
                    f"--only desconhecido: {', '.join(unknown)}. Disponíveis: {', '.join(sorted(known))}"
                )
            specs = [spec for spec in specs if spec.key in only]

        plan_only: bool = options["plan"]
        dry_run: bool = options["dry_run"]
        source_dir: Path | None = None
        if not plan_only:
            if not options.get("source_dir"):
                raise CommandError("--source-dir é obrigatório (ou use --plan para só relatar)")
            source_dir = Path(options["source_dir"]).expanduser()
            if not source_dir.is_dir():
                raise CommandError(f"--source-dir não é um diretório: {source_dir}")

        self.stdout.write(f"Manifesto: {manifest_path}")
        if source_dir:
            self.stdout.write(f"Fontes   : {source_dir}")
        self.stdout.write("")

        failures: list[str] = []
        skipped: list[str] = []
        loaded: list[str] = []

        for spec in specs:
            label = f"{spec.key:12}"

            if spec.blocked:
                # Bloqueio é fato registrado, não falha: LOINC espera cadastro,
                # CBHPM espera compra. Nenhum dos dois se resolve aqui.
                skipped.append(spec.key)
                self.stdout.write(f"  {label} BLOQUEADO — {spec.blocked}")
                continue

            if not spec.version:
                # A recusa central deste comando. Ver o docstring.
                failures.append(spec.key)
                self.stdout.write(
                    self.style.ERROR(
                        f'  {label} SEM VERSÃO — preencha `version` em [[catalog]] key="{spec.key}" '
                        f"do manifesto com a release da fonte que você baixou "
                        f"(o rótulo vai para {spec.version_arg}). Não há default: adivinhar "
                        f"fabricaria proveniência."
                    )
                )
                continue

            before = count_rows(spec.model)

            if plan_only:
                self.stdout.write(
                    f"  {label} carregaria {spec.command} {spec.source_arg} <{spec.file}> "
                    f"{spec.version_arg} {spec.version}  (tem {before}, espera >= {spec.expected_rows})"
                )
                continue

            assert source_dir is not None  # garantido acima; mantém o mypy honesto
            source_file = source_dir / spec.file
            if not source_file.is_file():
                failures.append(spec.key)
                hint = f" — gere com scripts/catalogs/{spec.etl}" if spec.etl else ""
                self.stdout.write(self.style.ERROR(f"  {label} FONTE AUSENTE: {source_file}{hint}"))
                continue

            argv = [spec.source_arg, str(source_file), spec.version_arg, spec.version]
            if dry_run:
                argv.append("--dry-run")

            buffer = StringIO()
            try:
                call_command(spec.command, *argv, stdout=buffer, stderr=buffer)
            except Exception as exc:  # noqa: BLE001 — um catálogo ruim não aborta os outros
                failures.append(spec.key)
                self.stdout.write(self.style.ERROR(f"  {label} FALHOU: {exc}"))
                continue

            after = count_rows(spec.model)

            if dry_run:
                # O importer reverteu tudo; contagem não muda e não prova nada.
                loaded.append(spec.key)
                self.stdout.write(f"  {label} dry-run ok (nada persistido)")
                continue

            if after < spec.expected_rows:
                failures.append(spec.key)
                self.stdout.write(
                    self.style.ERROR(
                        f"  {label} INCOMPLETO: {after} linhas, esperado >= {spec.expected_rows} "
                        f"(entrou {after - before}). Confira TerminologyImportLog: import `partial` "
                        f"costuma ser linha rejeitada por campo curto demais."
                    )
                )
                continue

            loaded.append(spec.key)
            extra = (
                f", {after - spec.expected_rows} acima do esperado"
                if after > spec.expected_rows
                else ""
            )
            self.stdout.write(
                self.style.SUCCESS(f"  {label} OK: {after} linhas (entrou {after - before}{extra})")
            )

        self.stdout.write("")
        self.stdout.write(
            f"carregados={len(loaded)}  bloqueados={len(skipped)}  falhas={len(failures)}"
        )
        if failures:
            raise CommandError(f"catálogos com problema: {', '.join(failures)}")
        if not plan_only and not dry_run and loaded:
            self.stdout.write("Agora rode: manage.py verify_catalogs")

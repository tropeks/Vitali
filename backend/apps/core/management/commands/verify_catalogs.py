"""
Management command: verify_catalogs  (core — Onda 2 / item 2.6)
=================================================================
Deploy-time gate for the essential governed catalogs (CID-10, TUSS, CNES,
ANVISA, SIGTAP, CBO, CID-O, UCUM — all SHARED/public-schema models in
``apps.core``). Reports each catalog's row count and, if any essential
catalog is EMPTY, exits non-zero (fails the deploy step).

Why this exists: the ETLs in ``scripts/catalogs/`` and the ``import_*``
commands they feed are idempotent upserts, but nothing calls them as part of
any deploy/CI pipeline (grep confirms zero hits for ``import_tuss`` /
``import_cid10`` etc. in workflows, Dockerfiles or entrypoints — see
docs/DEPTH_BACKLOG.md P1). A clean production deploy today boots with these
tables empty, and B6-B9 billing (TUSS/ANVISA/SIGTAP-dependent) then fails
*silently* — "sem TUSS correspondente" is logged at INFO and the line is
just never billed. This command is the loud version of that failure.

This command is intentionally VERIFY-ONLY, not an auto-loader. Every
``import_*`` command accepts an optional ``--<name>-version`` label (and
``import_tuss`` REQUIRES ``--tuss-version``) that documents which release of
the source data was loaded — that label comes from the filename/competência
of the file ops downloaded (see scripts/catalogs/README.md), and this command
has no way to know it without guessing. Guessing would fabricate provenance
metadata, which is exactly what CatalogImporter's docstring says never to do
("No clinical/terminology value is ever fabricated here"). So: this command
verifies; loading remains the explicit, human-run
``manage.py import_<x> --source <file> --<x>-version <label>`` steps in
scripts/catalogs/README.md. Wire this command into the deploy pipeline as a
gate AFTER those import steps run (see docs/DEPLOY.md).

Usage:
    python manage.py verify_catalogs                 # human-readable report, exits 1 if any catalog is empty
    python manage.py verify_catalogs --quiet          # only print on failure
    python manage.py verify_catalogs --json           # machine-readable report for deploy scripts
    python manage.py verify_catalogs --allow-empty ucum --allow-empty cido
                                                       # skip specific catalogs (e.g. partial rollout)

Exit code: 0 when every essential catalog (minus any --allow-empty) has at
least one row; 1 otherwise. Read-only — never writes to the database.
"""

import json

from django.apps import apps as django_apps
from django.core.management.base import BaseCommand, CommandError

# (model label, import command name, human description, --allow-empty key,
#  example invocation shown in the failure hint — matches each command's real
#  argument names, which are NOT uniform: import_tuss takes --file (not
#  --source) and a REQUIRED --tuss-version; the others take --source and an
#  optional --<x>-version. Do not derive these strings — copy from the
#  command's own add_arguments().)
ESSENTIAL_CATALOGS = (
    (
        "core.CID10Code",
        "import_cid10",
        "CID-10 (diagnósticos)",
        "cid10",
        "import_cid10 --source <arquivo> --cid-version <ano>",
    ),
    (
        "core.TUSSCode",
        "import_tuss",
        "TUSS (faturamento B6-B9)",
        "tuss",
        "import_tuss --file <arquivo> --tuss-version <competência>",
    ),
    (
        "core.CNESEstablishment",
        "import_cnes",
        "CNES (estabelecimentos)",
        "cnes",
        "import_cnes --source <arquivo> --cnes-version <competência>",
    ),
    (
        "core.AnvisaProduct",
        "import_anvisa",
        "ANVISA medicamentos (faturamento B6-B9)",
        "anvisa",
        "import_anvisa --source <arquivo> --anvisa-version <mês>",
    ),
    (
        "core.AnvisaPresentation",
        "import_anvisa_cmed",
        "ANVISA/CMED apresentações (casamento de NF-e)",
        "anvisa_cmed",
        "import_anvisa_cmed --source <arquivo> --cmed-version <mês> (rode DEPOIS de import_anvisa)",
    ),
    (
        "core.SIGTAPProcedure",
        "import_sigtap",
        "SIGTAP (faturamento SUS B6-B9)",
        "sigtap",
        "import_sigtap --source <arquivo> --sigtap-version <competência>",
    ),
    (
        "core.CBOCode",
        "import_cbo",
        "CBO (ocupações)",
        "cbo",
        "import_cbo --source <arquivo> --cbo-version <ano>",
    ),
    (
        "core.CIDOMorphology",
        "import_cido",
        "CID-O (morfologia oncológica)",
        "cido",
        "import_cido --source <arquivo> --cido-version <ano>",
    ),
    (
        "core.UcumUnit",
        "import_ucum",
        "UCUM (unidades de medida)",
        "ucum",
        "import_ucum --source <arquivo> --ucum-version <versão>",
    ),
)


class Command(BaseCommand):
    help = (
        "Verify the essential governed catalogs (TUSS/ANVISA/SIGTAP/CID-10/CNES/CBO/"
        "CID-O/UCUM) are non-empty. Exits 1 if any is empty. Read-only — see "
        "scripts/catalogs/README.md to actually load a catalog."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--json",
            action="store_true",
            default=False,
            help="Print a machine-readable JSON report instead of a table.",
        )
        parser.add_argument(
            "--quiet",
            action="store_true",
            default=False,
            help="Suppress the report when every catalog passes; still prints failures.",
        )
        parser.add_argument(
            "--allow-empty",
            action="append",
            default=[],
            metavar="CATALOG_KEY",
            help=(
                "Catalog key (e.g. 'ucum', 'cido') to skip the empty-check for. "
                "Repeatable. Use during partial rollout, never to silence a "
                "billing-critical catalog (tuss/anvisa/anvisa_cmed/sigtap) permanently."
            ),
        )

    def handle(self, *args, **options):
        as_json = options["json"]
        quiet = options["quiet"]
        allowed_empty = set(options["allow_empty"])

        report = []
        for label, command, description, key, example in ESSENTIAL_CATALOGS:
            model = django_apps.get_model(label)
            count = model.objects.count()
            skipped = count == 0 and key in allowed_empty
            report.append(
                {
                    "catalog": key,
                    "description": description,
                    "model": label,
                    "count": count,
                    "empty": count == 0,
                    "skipped": skipped,
                    "load_command": command,
                    "example": example,
                }
            )

        failing = [row for row in report if row["empty"] and not row["skipped"]]

        if as_json:
            self.stdout.write(json.dumps({"catalogs": report, "ok": not failing}, indent=2))
        elif not quiet or failing:
            self.stdout.write("Catálogos essenciais:")
            for row in report:
                if row["skipped"]:
                    mark = "SKIP"
                elif row["empty"]:
                    mark = "VAZIO"
                else:
                    mark = "ok"
                self.stdout.write(
                    f"  [{mark:>5}] {row['description']:50s} {row['count']:>10,d} linhas"
                )

        if failing:
            for row in failing:
                self.stderr.write(
                    self.style.ERROR(
                        f"Catálogo vazio: {row['description']} — carregue com "
                        f"`manage.py {row['example']}` (veja scripts/catalogs/README.md)."
                    )
                )
            catalogs = ", ".join(row["catalog"] for row in failing)
            raise CommandError(
                f"{len(failing)} catálogo(s) essencial(is) vazio(s) ({catalogs}). "
                "B6-B9 faturam em silêncio sem eles — não prossiga o deploy."
            )

        if not quiet:
            self.stdout.write(self.style.SUCCESS("Todos os catálogos essenciais estão carregados."))

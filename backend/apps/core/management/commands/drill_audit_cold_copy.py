"""Drill da cópia fria de uma partição de ``core_auditlog`` (ordens 020 e 032).

Baixa a cópia em *location* (o ``stored_location`` do recibo, impresso pelo
``purge_audit_logs`` e gravado na trilha como ``audit_partition_purged``),
decifra com ``BACKUP_ENCRYPTION_KEY`` e confere sha256 do cifrado, sha256 do
claro e contagem de linhas contra o manifesto — sem o banco de origem.

Saída: 0 = conferido; 75 (``EX_TEMPFAIL``) = restauração do Glacier pedida ou
em andamento, rode de novo depois; erro = a cópia reprovou, e a mensagem diz em
qual conferência.
"""

from __future__ import annotations

import sys

from django.core.management.base import BaseCommand, CommandError

from apps.core import cold_drill, cold_storage

EX_TEMPFAIL = 75


class Command(BaseCommand):
    help = "Baixa, decifra e confere uma cópia fria da trilha contra o manifesto."

    def add_arguments(self, parser):
        parser.add_argument("location", help="stored_location do recibo (caminho ou s3://...)")

    def handle(self, *args, location: str, **options):
        try:
            result = cold_drill.drill_cold_copy(location)
        except cold_storage.ColdExportError as exc:
            raise CommandError(f"drill REPROVADO: {exc}") from exc
        if result.status == "pending":
            self.stdout.write(f"PENDENTE: {result.detail}")
            sys.exit(EX_TEMPFAIL)
        self.stdout.write(self.style.SUCCESS(f"OK: {result.detail}"))

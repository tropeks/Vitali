"""Ordem 033 — o banco guarda só o SHA-256 do invite_token.

Ordem das operações, e por quê:

1. ``invite_token_hash`` entra anulável: as linhas existentes ainda não têm hash;
2. cada linha recebe o SHA-256 do próprio token. **Os convites já enviados
   continuam valendo**: o link que o paciente tem casa com o hash gravado;
3. o hash vira obrigatório e único (o token já era único, e o SHA-256 preserva);
4. só então a coluna em claro sai.

Reverter recusa: o token em claro não volta de um hash, e recriar a coluna com
tokens novos invalidaria calado todo convite aberto.

``sha256_hex`` é a mesma conta de ``apps.patient_portal.models.hash_invite_token``
(o teste ``test_o_hash_da_migration_e_o_do_model`` prende as duas); fica aqui
para a migration não depender de código de model que pode mudar depois.
"""

import hashlib

from django.db import migrations, models
from django.db.migrations.exceptions import IrreversibleError


def sha256_hex(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_existing_invite_tokens(apps, schema_editor):
    PatientPortalAccess = apps.get_model("patient_portal", "PatientPortalAccess")
    for access in PatientPortalAccess.objects.all().iterator():
        access.invite_token_hash = sha256_hex(access.invite_token)
        access.save(update_fields=["invite_token_hash"])


def refuse_to_restore_plaintext(apps, schema_editor):
    raise IrreversibleError(
        "patient_portal 0004: o invite_token em claro não volta de um hash, e recriar a "
        "coluna com tokens novos invalidaria calado todo convite aberto (ordem 033)"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("patient_portal", "0003_portalpixpayment_portalpreconsultform_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="patientportalaccess",
            name="invite_token_hash",
            field=models.CharField(max_length=64, null=True, editable=False),
        ),
        migrations.RunPython(hash_existing_invite_tokens, refuse_to_restore_plaintext),
        migrations.AlterField(
            model_name="patientportalaccess",
            name="invite_token_hash",
            field=models.CharField(max_length=64, unique=True, db_index=True, editable=False),
        ),
        migrations.RemoveField(
            model_name="patientportalaccess",
            name="invite_token",
        ),
    ]

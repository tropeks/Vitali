"""Ordem 033 — fase 1 de 2: o invite_token passa a ser guardado como hash.

A regra do projeto (docs/TENANT_MIGRATIONS.md): nenhuma migration de tenant
derruba coluna junto com a criação da nova. ``migrate_schemas`` roda tenant a
tenant, e a release anterior tem de continuar rodando contra o schema novo,
para que voltar o código não exija tocar em dado. Então esta migration só
EXPANDE:

1. ``invite_token_hash`` entra anulável e único (NULLs não colidem);
2. a coluna ``invite_token`` perde o NOT NULL: convite novo grava NULL nela. No
   estado do Django ela passa a se chamar ``invite_token_legado`` (mesma coluna,
   ``db_column``), para o nome ``invite_token`` ficar com o token em claro que
   só existe na instância que o cunhou;
3. cada linha existente recebe o SHA-256 do próprio token. **Os convites já
   enviados continuam valendo**: o link do paciente casa com o hash.

Reverter é seguro: a RunPython não tem o que desfazer (o claro nunca saiu), o
NOT NULL não volta (convite criado nesta fase tem a coluna em NULL, e a release
anterior sempre grava o token, então a coluna anulável não a atrapalha) e o
hash sai.

A ordem 034 (fase 2, depois de esta rodar em todos os tenants e de todo convite
anterior expirar, 7 dias) torna o hash obrigatório e derruba a coluna em claro.

``sha256_hex`` é a mesma conta de ``apps.patient_portal.models.hash_invite_token``
(o teste ``test_o_hash_da_migration_e_o_do_model`` prende as duas); fica aqui
para a migration não depender de código de model que pode mudar depois.
"""

import hashlib

from django.db import migrations, models


def sha256_hex(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_existing_invite_tokens(apps, schema_editor):
    PatientPortalAccess = apps.get_model("patient_portal", "PatientPortalAccess")
    for access in PatientPortalAccess.objects.all().iterator():
        if access.invite_token_legado and not access.invite_token_hash:
            access.invite_token_hash = sha256_hex(access.invite_token_legado)
            access.save(update_fields=["invite_token_hash"])


class Migration(migrations.Migration):
    dependencies = [
        ("patient_portal", "0003_portalpixpayment_portalpreconsultform_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="patientportalaccess",
            name="invite_token_hash",
            field=models.CharField(max_length=64, unique=True, null=True, editable=False),
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RenameField(
                    model_name="patientportalaccess",
                    old_name="invite_token",
                    new_name="invite_token_legado",
                ),
                migrations.AlterField(
                    model_name="patientportalaccess",
                    name="invite_token_legado",
                    field=models.CharField(
                        max_length=64,
                        db_column="invite_token",
                        unique=True,
                        null=True,
                        editable=False,
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    "ALTER TABLE patient_portal_patientportalaccess "
                    "ALTER COLUMN invite_token DROP NOT NULL",
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
        migrations.RunPython(hash_existing_invite_tokens, migrations.RunPython.noop),
    ]

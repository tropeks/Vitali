"""Prova da ordem 035 — dado de teste gravado pela release ANTERIOR.

Roda com ``manage.py shell`` num contêiner descartável da imagem anterior, depois
do ``bootstrap_beta``. Liga o portal na clínica de prova, cria um paciente com
acesso ao portal e o convite dele (o model anterior grava o token em claro) e
cunha os tokens de acesso da sonda: o do admin da clínica, que lista os
convites, e o do paciente, que ativa o convite depois do deploy.

Nada aqui é dado real: nome, CPF e e-mails são de teste, e o banco é o do
projeto efêmero da prova, derrubado com ``down -v`` no fim.
"""

import json
import secrets
import sys
from datetime import date

from django_tenants.utils import schema_context

from apps.core.models import Domain, FeatureFlag, Role, User, UserTenantMembership
from apps.core.tenant_auth import tokens_for_user

tenant = Domain.objects.get(domain="prova.local").tenant
SCHEMA = tenant.schema_name
FeatureFlag.objects.update_or_create(
    tenant=tenant, module_key="patient_portal", defaults={"is_enabled": True}
)
admin = User.objects.get(email="admin@prova.local")
papel, _ = Role.objects.get_or_create(
    name="prova035_portal", defaults={"permissions": ["portal.self_access"]}
)
paciente_user = User.objects.create_user(
    email="paciente@prova.local",
    password=secrets.token_urlsafe(24),
    role=papel,
    full_name="Paciente Prova",
)
UserTenantMembership.objects.get_or_create(user=paciente_user, tenant=tenant)

with schema_context(SCHEMA):
    from apps.emr.models import Patient
    from apps.patient_portal.models import PatientPortalAccess

    paciente = Patient.objects.create(
        full_name="Ana Prova", cpf="12345678909", birth_date=date(1985, 7, 14), gender="F"
    )
    convite = PatientPortalAccess.objects.create(user=paciente_user, patient=paciente)
    saida = {
        "admin_token": str(tokens_for_user(admin).access_token),
        "paciente_token": str(tokens_for_user(paciente_user).access_token),
        "convite_id": str(convite.pk),
        "convite_token": convite.invite_token,
        "schema": SCHEMA,
    }

# A saída é o contrato com o prova.sh: uma linha com o prefixo PROVA035.
sys.stdout.write("PROVA035 " + json.dumps(saida) + "\n")

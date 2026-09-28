"""Prova da ordem 035 — o convite da release anterior, lido pela release nova.

Roda com ``manage.py shell`` num contêiner descartável da imagem NOVA, depois
do deploy e da ativação pela sonda. Confere que a 0004 gravou o hash do
convite que a release anterior criou em claro, e que a ativação pela API
apagou o claro. Uma linha com o prefixo PROVA035 e o veredito.
"""

import json
import os
import sys

from django_tenants.utils import schema_context

from apps.patient_portal.models import PatientPortalAccess, hash_invite_token

with schema_context(os.environ["PROVA_SCHEMA"]):
    convite = PatientPortalAccess.objects.get(pk=os.environ["PROVA_CONVITE_ID"])
    veredito = {
        "hash_confere": convite.invite_token_hash
        == hash_invite_token(os.environ["PROVA_CONVITE_TOKEN"]),
        "claro_apagado": convite.invite_token_legado is None,
        "status": convite.status,
    }

sys.stdout.write("PROVA035 " + json.dumps(veredito) + "\n")

"""
Guarda: truststore vazio RECUSA a assinatura — não a grava como não-ICP em silêncio.

**O defeito, medido em staging em 16/09.** Com o trust store vazio o validador
devolvia ``"trust store not populated"`` e o signer **degradava de propósito**:
logava um warning e gravava a assinatura com ``is_icp_brasil=False``. O médico
assinava, a API respondia **201**, a linha entrava no ``DigitalSignature`` — e a
assinatura **não tinha valor legal**. Sem erro, sem alerta, sem vermelho em lugar
nenhum.

Foi o que aconteceu de verdade: as âncoras instaladas no contêiner às 15:27
morreram no ``up -d`` das 15:39, e staging voltou a esse estado sem que nada
acusasse.

É a forma mais cara do defeito que esta série vem perseguindo — **o caminho de
erro que reporta sucesso** — porque aqui o que se perde não é um contador, é a
validade jurídica de um prontuário. INTENT §Limites: "sinal verde tem que
significar verde".

**O contrato novo.** ``ICP_BRASIL_ENFORCE_CHAIN`` passa a valer também para o
store vazio:

* ``True`` (padrão, staging e produção) → a assinatura é **recusada**, com
  ``400`` e o motivo nomeado. Não há linha gravada.
* ``False`` (dev/CI) → comportamento anterior: assina e grava ``is_icp_brasil=False``.

Contra o código anterior à ordem 015 os testes de recusa falham: o signer devolve
um resultado em vez de levantar, e o endpoint responde 201.
"""

from __future__ import annotations

import base64

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.signatures.models import DigitalSignature
from apps.signatures.services.chain import ICPBrasilChainValidator
from apps.signatures.services.icp_brasil import ICPBrasilSigner, ICPBrasilSignerError
from apps.signatures.tests.test_icp_brasil_signer import _make_self_signed_pkcs12
from apps.test_utils import TenantTestCase


@pytest.mark.django_db
class TestStoreVazioRecusa:
    """Com enforcement ligado, store vazio é recusa — nunca assinatura silenciosa."""

    @override_settings(ICP_BRASIL_ENFORCE_CHAIN=True, ICP_BRASIL_TRUSTSTORE_DIR="/nao/existe")
    def test_store_vazio_com_enforcement_levanta(self):
        pfx, _, _ = _make_self_signed_pkcs12(password="pw")
        with pytest.raises(ICPBrasilSignerError) as exc:
            ICPBrasilSigner.sign(document=b"prontuario", pfx_bytes=pfx, password="pw")
        assert "trust store not populated" in str(exc.value), (
            "a recusa não diz o porquê — quem opera precisa saber que falta popular o "
            f"trust store, não que o certificado é ruim. veio: {exc.value!r}"
        )

    @override_settings(ICP_BRASIL_ENFORCE_CHAIN=False, ICP_BRASIL_TRUSTSTORE_DIR="/nao/existe")
    def test_store_vazio_sem_enforcement_ainda_degrada(self):
        """O regime antigo continua existindo — e continua testado.

        Dev e CI assinam sem âncoras; o que muda é que isso deixa de ser o PADRÃO.
        """
        pfx, _, _ = _make_self_signed_pkcs12(password="pw")
        r = ICPBrasilSigner.sign(document=b"prontuario", pfx_bytes=pfx, password="pw")
        assert r.is_icp_brasil is False
        assert r.chain_truststore_empty is True


class TestEndpointRecusa(TenantTestCase):
    """Pelo HTTP: 400 com o motivo, e NENHUMA linha gravada.

    `TenantTestCase` porque `signatures_digitalsignature` e tabela de TENANT —
    rodar no schema publico da o erro "relation does not exist", que nao diz nada
    sobre a recusa que se quer provar.
    """

    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="signatures",
            defaults={"is_enabled": True},
        )
        papel, _ = Role.objects.get_or_create(
            name="medico_vazio", defaults={"permissions": ["signatures.sign", "signatures.read"]}
        )
        papel.permissions = ["signatures.sign", "signatures.read"]
        papel.save()
        self.user = User.objects.create_user(email="assina@vazio.test", password="pw", role=papel)
        self.client.force_authenticate(user=self.user)

    @override_settings(ICP_BRASIL_ENFORCE_CHAIN=True, ICP_BRASIL_TRUSTSTORE_DIR="/nao/existe")
    def test_post_recusado_e_nada_e_gravado(self):
        ICPBrasilChainValidator.clear_cache()
        pfx, _, _ = _make_self_signed_pkcs12(password="pw")
        antes = DigitalSignature.objects.count()

        resp = self.client.post(
            "/api/v1/signatures/sign/",
            {
                "document_type": "encounter",
                "document_id": "enc-vazio-1",
                "document_b64": base64.b64encode(b"prontuario").decode("ascii"),
                "pkcs12_b64": base64.b64encode(pfx).decode("ascii"),
                "pkcs12_password": "pw",
            },
            format="json",
        )

        self.assertEqual(
            resp.status_code,
            400,
            f"esperava recusa explicita, veio {resp.status_code}. 201 aqui significa "
            f"assinatura sem valor legal gravada em silencio. corpo: {getattr(resp, 'data', None)}",
        )
        self.assertIn("trust store not populated", str(resp.data.get("detail", "")))
        self.assertEqual(
            DigitalSignature.objects.count(),
            antes,
            "a recusa gravou linha mesmo assim — assinatura recusada nao pode deixar "
            "rastro de assinatura feita",
        )

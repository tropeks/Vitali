"""
Guarda: cadeia de receita que REPROVA não pode deixar guia comitada (ordem 007).

**O defeito.** `verify_revenue_chain --create` monta guia e lote dentro de um
`with transaction.atomic()`, mas o `if falhas: self._reprovar(falhas)` final ficava
**fora** do bloco. Resultado: quando a validação contra o XSD acusava erro, a guia e
o lote já tinham comitado, e o comando só então reportava falha.

Foi assim que a guia `202609000001` sobrou em staging — carteirinha vazia, nenhum
CID-10 — depois de uma execução que reprovou. Eu havia afirmado ao Imediato que o
`atomic()` limpava o rastro de uma execução falha: vale para exceção levantada
*dentro* do bloco (o `guide_type` inválido foi assim), e não para falha coletada e
reportada no fim.

Por que importa mais do que parece: desde a ordem 007 a cunha de glosa julga as guias
do tenant, e guia suja deixada por uma execução reprovada vira alerta de glosa. O
rastro de um comando que falhou passa a poluir a interceptação.

Contra o código anterior à ordem 007 este teste falha (a guia persiste); depois, passa.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

from apps.billing.models import InsuranceProvider, PriceTable, PriceTableItem, TISSGuide
from apps.core.models import TUSSCode, User
from apps.emr.models import Encounter, Patient, Professional
from apps.test_utils import TenantTestCase


class VerifyRevenueChainAtomicTests(TenantTestCase):
    """Reprovar tem de reverter — não basta relatar."""

    def setUp(self) -> None:
        super().setUp()
        user = User.objects.create_user(
            email="chain-atomic@test.com", full_name="Dr. Atomic", password="Str0ng!Pass#2024"
        )
        profissional = Professional.objects.create(
            user=user, council_type="CRM", council_number="90007", council_state="SP"
        )
        paciente = Patient.objects.create(
            full_name="Paciente Atomic",
            cpf="000.000.000-07",
            birth_date=datetime.date(1990, 7, 1),
            gender="F",
        )
        Encounter.objects.create(patient=paciente, professional=profissional)
        provider = InsuranceProvider.objects.create(
            name="Operadora Atomic (FICTÍCIA — staging)", ans_code="000007"
        )
        tuss = TUSSCode.objects.create(
            code="10101012", description="Consulta (teste)", table_number="22", active=True
        )
        tabela = PriceTable.objects.create(
            provider=provider,
            name="Tabela Atomic (FICTÍCIA — staging)",
            valid_from=datetime.date.today(),
            is_active=True,
        )
        PriceTableItem.objects.create(
            table=tabela, tuss_code=tuss, negotiated_value=Decimal("100.00")
        )

    def test_reprovacao_nao_deixa_guia_comitada(self) -> None:
        """XSD acusando erro tem de reverter a guia, não só reportar.

        `validate_xml` é substituído para devolver erro de forma determinística —
        o ponto do teste é o comportamento transacional, não o conteúdo do XML.
        """
        alvo = "apps.billing.services.xml_engine.validate_xml"
        with patch(alvo, return_value=["erro forçado para exercitar a reprovação"]):
            with self.assertRaises(CommandError):
                call_command(
                    "verify_revenue_chain", "--tenant", self.tenant.schema_name, "--create"
                )

        self.assertEqual(
            TISSGuide.objects.count(),
            0,
            "cadeia reprovada deixou guia comitada — o `_reprovar` final está fora do atomic()",
        )

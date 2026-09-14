"""
Guarda de regressão para `seed_demo_data._create_guides` (ordem 006).

**Por que este teste existe.** A função é a única coisa no repositório que produz
guias TISS de demonstração, e ela nunca executou o próprio corpo. Ele é protegido
por

    if not provider or not tuss_codes or not encounters:
        return

e `seed_demo_data` **não cria** `InsuranceProvider` nenhuma, então a condição era
sempre verdadeira: o `return` disparava, em silêncio, em toda execução. Medido em
2026-09-12 no staging da lab — 4 pacientes, 4 atendimentos, 3 internações e
**zero** `billing_tissguide`.

O que o `return` escondia é o problema de verdade: o corpo chamava

    TISSGuide.objects.create(..., insurance_provider=provider, professional=...)

e o modelo não tem esses campos — os nomes reais são **`provider`** e
**`executor`**. No instante em que alguém fizesse a primeira coisa óbvia,
cadastrar uma operadora, o seed passaria a estourar `TypeError`. Um guard
silencioso mantinha código morto e quebrado fora de vista.

Este teste **fornece** a operadora que faltava, de modo que o `return` não dispare
e o corpo tenha de executar. Contra o código anterior à ordem 006 ele falha com
`TypeError`; depois, passa.
"""

from __future__ import annotations

import datetime

from apps.billing.models import InsuranceProvider, TISSGuide
from apps.core.models import TUSSCode, User
from apps.emr.models import Encounter, Patient, Professional
from apps.test_utils import TenantTestCase


class SeedDemoDataCreatesGuidesTests(TenantTestCase):
    """`_create_guides` tem de produzir guia quando o cadastro mínimo existe."""

    def setUp(self) -> None:
        super().setUp()
        user = User.objects.create_user(
            email="seed-guides@test.com",
            full_name="Dr. Seed",
            password="Str0ng!Pass#2024",
        )
        self.professional = Professional.objects.create(
            user=user, council_type="CRM", council_number="90006", council_state="SP"
        )
        self.patient = Patient.objects.create(
            full_name="Paciente Seed",
            cpf="000.000.000-06",
            birth_date=datetime.date(1990, 6, 1),
            gender="F",
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient, professional=self.professional
        )

    def _cadastro_minimo(self) -> InsuranceProvider:
        """O que o guard exige para não retornar: operadora + TUSS ativo."""
        provider = InsuranceProvider.objects.create(
            # Sufixo e registro seguem a fronteira de dado da ordem 006: fictício e
            # rotulado. `000000` casa st_registroANS ([0-9]{6}) sem ser um registro
            # que exista — os reais são atribuídos pela ANS e não são zero.
            name="Operadora Demonstração (FICTÍCIA — staging)",
            ans_code="000000",
        )
        TUSSCode.objects.create(
            code="10101012",
            description="Consulta em consultório (fictícia — staging)",
            table_number="22",
            active=True,
        )
        return provider

    def test_cria_guia_quando_ha_operadora_e_tuss(self) -> None:
        """Caminho feliz. Falhava com TypeError antes da ordem 006."""
        from apps.core.management.commands.seed_demo_data import Command

        provider = self._cadastro_minimo()

        Command()._create_guides(fake=None, encounters=[self.encounter], patients=[self.patient])

        guias = TISSGuide.objects.all()
        self.assertEqual(
            guias.count(), 1, "com operadora presente o guard não retorna e o corpo tem de criar"
        )
        guia = guias.first()
        assert guia is not None
        self.assertEqual(guia.provider_id, provider.id, "o campo do modelo é `provider`")
        self.assertEqual(guia.patient_id, self.patient.id)
        self.assertTrue(guia.items.exists(), "guia sem item não vira faturamento")

        # Nome de campo certo com valor de enum errado ainda é guia que não
        # vira XML. O seed gravava guide_type="consultation", que NÃO está entre
        # as choices do modelo (sadt/consulta/honorarios/internacao): a guia
        # nascia no banco e morria na geração do XML, com
        # "guide_type='consultation' has no TISS XML template". Django não
        # valida choices no `create()`, então só um teste pega isto.
        # `choices` é Optional nos django-stubs; `or []` mantém o mypy honesto
        # sem esconder um campo que por acaso venha sem choices.
        tipos_validos = {c[0] for c in (TISSGuide._meta.get_field("guide_type").choices or [])}
        self.assertIn(
            guia.guide_type,
            tipos_validos,
            f"guide_type={guia.guide_type!r} fora das choices do modelo {sorted(tipos_validos)}",
        )

    def test_sem_operadora_avisa_em_vez_de_sumir(self) -> None:
        """O `return` silencioso vira aviso — condição (1) do Imediato.

        Não basta não quebrar: quem roda o seed precisa descobrir POR QUE não
        houve guia sem ter de ler o código-fonte. Foi o silêncio, não o retorno,
        que manteve o defeito escondido por meses.
        """
        from apps.core.management.commands.seed_demo_data import Command

        with self.assertLogs("apps.core", level="WARNING") as captured:
            Command()._create_guides(
                fake=None, encounters=[self.encounter], patients=[self.patient]
            )

        self.assertEqual(TISSGuide.objects.count(), 0)
        mensagem = " ".join(captured.output)
        self.assertIn("InsuranceProvider", mensagem, "o aviso tem de nomear o que falta")

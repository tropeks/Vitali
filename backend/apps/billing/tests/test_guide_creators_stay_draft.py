"""
Guarda: os geradores de guia continuam entregando RASCUNHO (ordem 009).

**Por que isto é um teste, e não um comentário.** A ordem 009 tornou o fechamento de lote
estrito: guia que ninguém declarou pronta não vai no XML. A pergunta seguinte, do Imediato,
foi se os geradores automáticos passariam a declarar pronto sozinhos. A resposta é **não**,
e a razão é de produto, não de engenharia: uma guia gerada de um pedido de exame, de uma
internação ou de um caso cirúrgico é derivada de um evento clínico, mas **ninguém a
conferiu**. Marcá-la `pending` na criação afirmaria à operadora que ela está pronta para
faturar sem que um faturista tenha olhado — declaração desonesta, e o §Limites do INTENT
não admite sinal que não significa o que diz.

`draft` é escolha deliberada dos três services (`lab_order_billing.py:126`,
`inpatient_billing.py:393`, `surgery_billing.py:96`). Este arquivo **trava essa escolha**:
se alguém um dia mudar um deles para `pending` "para simplificar o fluxo", o teste cai e a
conversa acontece antes do merge, não depois de a guia sair.

Cada classe herda a fixtura do teste que já existe para aquele gerador, em vez de duplicar
duzentas linhas de montagem — e nenhum teste existente foi editado.
"""

from __future__ import annotations

from apps.billing.services.inpatient_billing import generate_internacao_guide_for_admission
from apps.billing.services.lab_order_billing import generate_sadt_guide_for_lab_order
from apps.billing.services.surgery_billing import generate_sadt_guide_for_surgical_case

from .test_inpatient_guide import InpatientGuideTestCase
from .test_lab_order_billing import LabOrderBillingTestCase
from .test_surgery_billing import SurgeryBillingTestCase

_MOTIVO = (
    "este gerador passou a declarar a guia pronta sozinho. Isso afirma que ela está "
    "conferida e pode ir à operadora sem ninguém ter olhado. Se a mudança for "
    "deliberada, é decisão de produto — ordem 009, condição (3) do Imediato."
)


class LabOrderGuideStaysDraftTests(LabOrderBillingTestCase):
    def test_guia_de_pedido_de_exame_nasce_rascunho(self) -> None:
        guide = generate_sadt_guide_for_lab_order(self._make_order())
        self.assertEqual(guide.status, "draft", _MOTIVO)


class AdmissionGuideStaysDraftTests(InpatientGuideTestCase):
    def test_guia_de_internacao_nasce_rascunho(self) -> None:
        adm = self._admission(admit=self._dt(2026, 3, 1), discharge=self._dt(2026, 3, 4))
        guide = generate_internacao_guide_for_admission(adm)
        self.assertEqual(guide.status, "draft", _MOTIVO)


class SurgicalCaseGuideStaysDraftTests(SurgeryBillingTestCase):
    def test_guia_de_caso_cirurgico_nasce_rascunho(self) -> None:
        guide = generate_sadt_guide_for_surgical_case(self._make_case())
        self.assertEqual(guide.status, "draft", _MOTIVO)

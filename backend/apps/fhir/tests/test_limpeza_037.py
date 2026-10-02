"""Ordem 037 — limpeza de três restos da ordem 030.

1. A rota ``imaging/viewer-auth/`` devolve 204 sem ler nada e o nginx não a usa
   (usa ``portal/me/imaging-viewer-auth/``). Rota morta atrás de autenticação é
   superfície sem dono: sai.
2. A docstring da ``ObservationReadView`` documenta ``<encounter-id>-<loinc>``,
   mas o código separa por ``_``.
3. O ``except`` da ``PatientReadView`` listava ``Exception`` e re-levantava tudo
   o que não era 404: o ``Exception`` não fazia nada.
"""

import ast
import inspect
import textwrap

from django.test import SimpleTestCase
from django.urls import NoReverseMatch, reverse

from apps.fhir.views import ObservationReadView, PatientReadView


class RotaMortaViewerAuthTest(SimpleTestCase):
    def test_rota_do_staff_nao_existe_mais(self):
        with self.assertRaises(NoReverseMatch):
            reverse("imaging-viewer-auth")

    def test_portao_do_nginx_do_portal_continua(self):
        self.assertEqual(
            reverse("portal-me-imaging-viewer-auth"),
            "/api/v1/portal/me/imaging-viewer-auth/",
        )


class DocstringObservationTest(SimpleTestCase):
    def test_docstring_diz_o_separador_que_o_codigo_usa(self):
        self.assertIn("<encounter-id>_<loinc>", ObservationReadView.__doc__)
        self.assertNotIn("<encounter-id>-<loinc>", ObservationReadView.__doc__)


class ExceptDaPatientReadViewTest(SimpleTestCase):
    def test_nenhum_except_captura_exception(self):
        fonte = textwrap.dedent(inspect.getsource(PatientReadView.get))
        handlers = [n for n in ast.walk(ast.parse(fonte)) if isinstance(n, ast.ExceptHandler)]
        tipos = [n for h in handlers if h.type is not None for n in ast.walk(h.type)]
        capturados = [t.id for t in tipos if isinstance(t, ast.Name)]
        self.assertNotIn("Exception", capturados)
        self.assertTrue(handlers)

"""CSP violation collector (#115).

The Next.js API proxy appends a trailing slash to every forwarded path, so the
browser's report-uri (``/api/v1/security/csp-report``) must resolve to the Django
route at the *trailing-slash* path. These tests pin that contract plus the view's
204/405 behaviour so a future urlconf edit cannot silently break report collection.
"""

from django.test import RequestFactory, SimpleTestCase
from django.urls import resolve, reverse

from vitali.urls_public import csp_report

PUBLIC_URLCONF = "vitali.urls_public"


class CspReportRouteTests(SimpleTestCase):
    def test_route_resolves_at_trailing_slash_path(self):
        # The proxy forwards `.../csp-report` as `.../csp-report/`; that must resolve.
        path = reverse("csp-report", urlconf=PUBLIC_URLCONF)
        self.assertEqual(path, "/api/v1/security/csp-report/")
        match = resolve(path, urlconf=PUBLIC_URLCONF)
        self.assertEqual(match.func, csp_report)


class CspReportViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_post_returns_204(self):
        body = b'{"csp-report":{"violated-directive":"script-src"}}'
        request = self.factory.post(
            "/api/v1/security/csp-report/",
            data=body,
            content_type="application/csp-report",
        )
        response = csp_report(request)
        self.assertEqual(response.status_code, 204)

    def test_empty_body_still_204(self):
        request = self.factory.post("/api/v1/security/csp-report/")
        response = csp_report(request)
        self.assertEqual(response.status_code, 204)

    def test_get_is_rejected(self):
        # @require_POST: browsers only ever POST reports.
        request = self.factory.get("/api/v1/security/csp-report/")
        response = csp_report(request)
        self.assertEqual(response.status_code, 405)

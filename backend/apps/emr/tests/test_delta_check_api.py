"""A3 — Delta check laboratorial em produção + API.

Covers three concerns beyond the pure-service test_delta_check.py:

  * A3-T1 — WIRING: resulting a LabOrderItem through the production result
    action fires run_delta_check, so a variation beyond the test threshold
    persists a LabDeltaAlert (and within-threshold / inert tests persist none).
  * A3-T2 — LabTestSerializer round-trips ``delta_threshold_pct`` via PATCH.
  * A3-T3 — the LabDeltaAlert read API (list/retrieve, filters) and the nested
    ``delta_alert`` field carried on each resulted LabOrderItem.
"""

from decimal import Decimal

from rest_framework.test import APIClient

from apps.core.models import Role, User
from apps.emr.models import (
    Encounter,
    LabDeltaAlert,
    LabOrder,
    LabTest,
    Patient,
    Professional,
)
from apps.test_utils import TenantTestCase


class DeltaCheckApiTestCase(TenantTestCase):
    def setUp(self):
        self.writer_role = Role.objects.create(
            name="delta_api_writer", permissions=["emr.read", "emr.write"]
        )
        self.reader_role = Role.objects.create(name="delta_api_reader", permissions=["emr.read"])
        self.writer = User.objects.create_user(
            email="delta-api-writer@example.com", password="pw", role=self.writer_role
        )
        self.reader = User.objects.create_user(
            email="delta-api-reader@example.com", password="pw", role=self.reader_role
        )
        self.professional = Professional.objects.create(
            user=self.writer, council_type="CRM", council_number="DLT-1", council_state="SP"
        )
        self.patient = Patient.objects.create(
            full_name="Delta API Paciente",
            birth_date="1980-02-02",
            gender="F",
            cpf="54444444444",
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient, professional=self.professional
        )
        self.test = LabTest.objects.create(
            code="GLUC-API", name="Glicose", unit="mg/dL", delta_threshold_pct=Decimal("20")
        )
        self.inert_test = LabTest.objects.create(
            code="NA-API", name="Sódio", unit="mEq/L", delta_threshold_pct=None
        )

    # ── helpers ───────────────────────────────────────────────────────────────
    def client_for(self, user):
        client = APIClient()
        client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        client.force_authenticate(user=user)
        return client

    def _create_and_result(self, value, *, test=None):
        """Full production path: create order → collect → result an item."""
        test = test or self.test
        client = self.client_for(self.writer)
        create = client.post(
            "/api/v1/lab-orders/",
            {"patient": str(self.patient.id), "test_ids": [str(test.id)]},
            format="json",
        )
        self.assertEqual(create.status_code, 201, create.content)
        order = LabOrder.objects.get(pk=create.data["id"])
        item = order.items.get()
        collect = client.post(f"/api/v1/lab-orders/{order.id}/collect/", {}, format="json")
        self.assertEqual(collect.status_code, 200, collect.content)
        result = client.post(
            f"/api/v1/lab-orders/{order.id}/items/{item.id}/result/",
            {"result_value": str(value), "abnormal_flag": "normal"},
            format="json",
        )
        self.assertEqual(result.status_code, 200, result.content)
        item.refresh_from_db()
        return order, item

    # ── A3-T1: wiring ──────────────────────────────────────────────────────────
    def test_resulting_beyond_threshold_creates_alert(self):
        self._create_and_result(100)  # prior
        _order, current = self._create_and_result(150)  # +50% > 20%
        alert = LabDeltaAlert.objects.get(order_item=current)
        self.assertEqual(alert.previous_value, Decimal("100"))
        self.assertEqual(alert.current_value, Decimal("150"))
        self.assertEqual(alert.delta_pct, Decimal("50"))
        self.assertEqual(alert.threshold_pct, Decimal("20"))

    def test_resulting_within_threshold_creates_no_alert(self):
        self._create_and_result(100)  # prior
        _order, current = self._create_and_result(110)  # +10% ≤ 20%
        self.assertEqual(LabDeltaAlert.objects.filter(order_item=current).count(), 0)

    def test_resulting_inert_test_creates_no_alert(self):
        self._create_and_result(100, test=self.inert_test)  # prior
        _order, current = self._create_and_result(200, test=self.inert_test)  # +100%
        self.assertEqual(LabDeltaAlert.objects.filter(order_item=current).count(), 0)

    # ── A3-T2: LabTest threshold round-trips ────────────────────────────────────
    def test_delta_threshold_round_trips_via_patch(self):
        client = self.client_for(self.writer)
        patch = client.patch(
            f"/api/v1/lab-tests/{self.inert_test.id}/",
            {"delta_threshold_pct": "15.50"},
            format="json",
        )
        self.assertEqual(patch.status_code, 200, patch.content)
        self.assertEqual(Decimal(patch.data["delta_threshold_pct"]), Decimal("15.50"))
        self.inert_test.refresh_from_db()
        self.assertEqual(self.inert_test.delta_threshold_pct, Decimal("15.50"))
        get = client.get(f"/api/v1/lab-tests/{self.inert_test.id}/")
        self.assertEqual(Decimal(get.data["delta_threshold_pct"]), Decimal("15.50"))

    # ── A3-T3: alert read API + nested field ────────────────────────────────────
    def test_delta_alerts_list_and_filters(self):
        self._create_and_result(100)
        _order, current = self._create_and_result(150)
        client = self.client_for(self.reader)

        listing = client.get("/api/v1/lab-delta-alerts/")
        self.assertEqual(listing.status_code, 200, listing.content)
        results = listing.data.get("results", listing.data)
        self.assertEqual(len(results), 1)
        row = results[0]
        for field in (
            "order_item",
            "previous_item",
            "test",
            "previous_value",
            "current_value",
            "delta_absolute",
            "delta_pct",
            "threshold_pct",
            "created_at",
        ):
            self.assertIn(field, row)
        self.assertEqual(str(row["order_item"]), str(current.id))

        by_patient = client.get(f"/api/v1/lab-delta-alerts/?patient={self.patient.id}")
        self.assertEqual(len(by_patient.data.get("results", by_patient.data)), 1)
        by_item = client.get(f"/api/v1/lab-delta-alerts/?order_item={current.id}")
        self.assertEqual(len(by_item.data.get("results", by_item.data)), 1)

    def test_resulted_item_carries_nested_delta_alert(self):
        self._create_and_result(100)
        order, current = self._create_and_result(150)
        client = self.client_for(self.reader)
        detail = client.get(f"/api/v1/lab-orders/{order.id}/")
        self.assertEqual(detail.status_code, 200, detail.content)
        item_payload = next(i for i in detail.data["items"] if str(i["id"]) == str(current.id))
        self.assertIsNotNone(item_payload.get("delta_alert"))
        self.assertEqual(Decimal(item_payload["delta_alert"]["delta_pct"]), Decimal("50"))

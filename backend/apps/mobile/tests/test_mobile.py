"""Tests for the mobile backend primitive."""

from __future__ import annotations

from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.mobile.models import MobileDevice, PushDelivery
from apps.mobile.services.push import MobilePushService, PushAdapter
from apps.test_utils import TenantTestCase

ME_URL = "/api/v1/mobile/devices/me/"
ADMIN_DEVICES_URL = "/api/v1/mobile/devices/"
PUSH_URL = "/api/v1/mobile/push/"
PUSH_AUDIT_URL = "/api/v1/mobile/push/audit/"


def _me_device_detail(pk):
    return f"/api/v1/mobile/devices/me/{pk}/"


def _make_user(*, role_name: str, perms: list[str], email: str | None = None) -> User:
    role, _ = Role.objects.get_or_create(name=role_name, defaults={"permissions": perms})
    role.permissions = perms
    role.save()
    return User.objects.create_user(
        email=email or f"{role_name}@test.com",
        password="pw",
        role=role,
        full_name="Test",
    )


# ─── Self surface ─────────────────────────────────────────────────────────────


class MobileSelfDeviceTest(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="mobile",
            defaults={"is_enabled": True},
        )
        self.user = _make_user(role_name="mobile_user", perms=[])
        self.client.force_authenticate(user=self.user)

    def _register(self, **overrides):
        payload = {
            "platform": "android",
            "device_id": "device-abc",
            "push_token": "fcm-token-xyz",
            "app_version": "1.0.0",
            "os_version": "Android 14",
        }
        payload.update(overrides)
        return self.client.post(ME_URL, payload, format="json")

    def test_register_creates_device(self):
        resp = self._register()
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data["platform"], "android")
        self.assertEqual(resp.data["user"], self.user.pk)
        self.assertTrue(resp.data["is_active"])

    def test_register_is_idempotent_per_device_id(self):
        self._register(push_token="old-token")
        self._register(push_token="new-token")
        devices = MobileDevice.objects.filter(user=self.user)
        self.assertEqual(devices.count(), 1)
        self.assertEqual(devices.first().push_token, "new-token")

    def test_list_only_returns_own_devices(self):
        other_user = _make_user(role_name="other_mobile_user", perms=[], email="other_m@test.com")
        MobileDevice.objects.create(
            user=other_user,
            platform="ios",
            device_id="other-device",
            push_token="t",
        )
        self._register()
        resp = self.client.get(ME_URL)
        ids = {entry["device_id"] for entry in resp.data}
        self.assertIn("device-abc", ids)
        self.assertNotIn("other-device", ids)

    def test_delete_marks_inactive(self):
        self._register()
        device = MobileDevice.objects.get(user=self.user, device_id="device-abc")
        resp = self.client.delete(_me_device_detail(device.pk))
        self.assertEqual(resp.status_code, 204)
        device.refresh_from_db()
        self.assertFalse(device.is_active)

    def test_delete_other_users_device_returns_404(self):
        other_user = _make_user(role_name="other_m2", perms=[], email="o2@test.com")
        other_device = MobileDevice.objects.create(
            user=other_user, platform="ios", device_id="x", push_token="t"
        )
        resp = self.client.delete(_me_device_detail(other_device.pk))
        self.assertEqual(resp.status_code, 404)

    def test_register_blocked_when_module_disabled(self):
        FeatureFlag.objects.filter(tenant=self.__class__.tenant, module_key="mobile").update(
            is_enabled=False
        )
        resp = self._register()
        self.assertEqual(resp.status_code, 403)

    def test_register_unauthenticated_returns_401(self):
        self.client.logout()
        resp = self._register()
        self.assertIn(resp.status_code, [401, 403])

    def test_invalid_platform_returns_400(self):
        resp = self._register(platform="palmpilot")
        self.assertEqual(resp.status_code, 400)


# ─── Admin surface + push dispatcher ─────────────────────────────────────────


class _CapturingAdapter:
    """In-test PushAdapter that records calls and lets the test pick success/failure."""

    def __init__(self, *, succeed: bool = True):
        self.calls: list[dict] = []
        self.succeed = succeed

    def send(self, *, device, title, body, data):
        self.calls.append(
            {
                "device": device.pk,
                "title": title,
                "body": body,
                "data": data,
            }
        )
        if self.succeed:
            return True, f"msg-{len(self.calls)}", ""
        return False, "", "provider rejected"


class MobileAdminAndPushTest(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="mobile",
            defaults={"is_enabled": True},
        )
        self.admin = _make_user(role_name="mobile_admin", perms=["mobile.admin"])
        self.client.force_authenticate(user=self.admin)
        self.target_user = _make_user(
            role_name="mobile_target", perms=[], email="target_m@test.com"
        )
        self.device = MobileDevice.objects.create(
            user=self.target_user,
            platform="ios",
            device_id="device-1",
            push_token="apns-1",
        )

    def tearDown(self):
        MobilePushService.reset_adapter()

    # Admin list

    def test_admin_list_returns_all_devices(self):
        resp = self.client.get(ADMIN_DEVICES_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(len(resp.data), 1)
        ids = {entry["id"] for entry in resp.data}
        self.assertIn(str(self.device.pk), ids)

    def test_admin_list_filters_by_user_and_platform(self):
        # other platform device for the same user
        MobileDevice.objects.create(
            user=self.target_user,
            platform="android",
            device_id="device-2",
            push_token="fcm-2",
        )
        resp = self.client.get(
            ADMIN_DEVICES_URL,
            {"user": str(self.target_user.pk), "platform": "ios"},
        )
        platforms = {entry["platform"] for entry in resp.data}
        self.assertEqual(platforms, {"ios"})

    def test_admin_list_blocked_without_mobile_admin(self):
        non_admin = _make_user(role_name="no_madmin", perms=[], email="na_m@test.com")
        self.client.force_authenticate(user=non_admin)
        resp = self.client.get(ADMIN_DEVICES_URL)
        self.assertEqual(resp.status_code, 403)

    # Push send + audit

    def test_send_no_provider_marks_delivery_as_no_provider(self):
        resp = self.client.post(
            PUSH_URL,
            {"user": str(self.target_user.pk), "title": "Hello", "body": "World"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["no_provider"], 1)
        self.assertEqual(resp.data["delivered"], 0)
        delivery = PushDelivery.objects.get(pk=resp.data["delivery_ids"][0])
        self.assertEqual(delivery.status, "no_provider")

    def test_send_with_provider_marks_delivery_as_sent(self):
        adapter: PushAdapter = _CapturingAdapter(succeed=True)
        MobilePushService.set_adapter(adapter)
        resp = self.client.post(
            PUSH_URL,
            {"user": str(self.target_user.pk), "title": "Hello", "data": {"k": "v"}},
            format="json",
        )
        self.assertEqual(resp.data["delivered"], 1)
        self.assertEqual(resp.data["no_provider"], 0)
        # Adapter actually called with the right payload
        self.assertEqual(adapter.calls[0]["title"], "Hello")
        self.assertEqual(adapter.calls[0]["data"], {"k": "v"})

    def test_send_with_failing_provider_marks_failed(self):
        MobilePushService.set_adapter(_CapturingAdapter(succeed=False))
        resp = self.client.post(
            PUSH_URL,
            {"user": str(self.target_user.pk), "title": "Hello"},
            format="json",
        )
        self.assertEqual(resp.data["failed"], 1)
        delivery = PushDelivery.objects.get(pk=resp.data["delivery_ids"][0])
        self.assertEqual(delivery.status, "failed")
        self.assertEqual(delivery.provider_error, "provider rejected")

    def test_send_to_inactive_devices_skipped(self):
        self.device.is_active = False
        self.device.save(update_fields=["is_active"])
        resp = self.client.post(
            PUSH_URL,
            {"user": str(self.target_user.pk), "title": "Hello"},
            format="json",
        )
        # No active devices → 0 deliveries, but the request still 200 OK.
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["delivered"] + resp.data["failed"] + resp.data["no_provider"], 0)

    def test_send_unknown_user_returns_404(self):
        resp = self.client.post(
            PUSH_URL,
            {"user": "00000000-0000-4000-8000-000000000000", "title": "x"},
            format="json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_push_audit_returns_recorded_deliveries(self):
        self.client.post(
            PUSH_URL,
            {"user": str(self.target_user.pk), "title": "AuditMe"},
            format="json",
        )
        resp = self.client.get(PUSH_AUDIT_URL)
        titles = {entry["title"] for entry in resp.data}
        self.assertIn("AuditMe", titles)

    def test_push_send_blocked_without_mobile_admin(self):
        non_admin = _make_user(role_name="np_madmin", perms=[], email="np_m@test.com")
        self.client.force_authenticate(user=non_admin)
        resp = self.client.post(
            PUSH_URL, {"user": str(self.target_user.pk), "title": "x"}, format="json"
        )
        self.assertEqual(resp.status_code, 403)

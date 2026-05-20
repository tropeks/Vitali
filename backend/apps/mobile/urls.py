from django.urls import path

from .views import (
    AdminDeviceListView,
    AdminPushAuditView,
    AdminPushSendView,
    MyDeviceDetailView,
    MyDevicesView,
)

urlpatterns = [
    path("mobile/devices/me/", MyDevicesView.as_view(), name="mobile-me-devices"),
    path(
        "mobile/devices/me/<uuid:device_pk>/",
        MyDeviceDetailView.as_view(),
        name="mobile-me-device-detail",
    ),
    path("mobile/devices/", AdminDeviceListView.as_view(), name="mobile-admin-devices"),
    path("mobile/push/", AdminPushSendView.as_view(), name="mobile-push-send"),
    path("mobile/push/audit/", AdminPushAuditView.as_view(), name="mobile-push-audit"),
]

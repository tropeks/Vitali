"""
Public-schema URL config for the imaging module.

Only the Orthanc webhook is exposed here. Orthanc's ``/changes`` feed is
PACS-wide (one PACS shared across all tenants), so the webhook must run from the
**public schema** for ``for_each_tenant_schema`` to fan out across every tenant
and find the one that pre-registered the study — exactly like the Celery poller,
which also starts in the public schema. Deploy Orthanc to POST at the
public-schema host for full cross-tenant matching.

The same view is also mounted on the tenant urlconf (``apps.imaging.urls``); on
a tenant host it simply scopes the match to that tenant.
"""

from django.urls import path

from .views import OrthancWebhookView

urlpatterns = [
    path(
        "imaging/orthanc/webhook/",
        OrthancWebhookView.as_view(),
        name="imaging-orthanc-webhook-public",
    ),
]

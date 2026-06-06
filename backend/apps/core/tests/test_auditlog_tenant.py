"""AuditLog tenant-discriminator tests (SYS-1).

AuditLog is a shared/public-schema table; ``schema_name`` is the tenant
discriminator, stamped automatically on write and used by ``for_current_tenant``
to avoid cross-tenant disclosure on any future read path.
"""

from django.db import connection

from apps.core.models import AuditLog
from apps.test_utils import TenantTestCase


class AuditLogTenantColumnTests(TenantTestCase):
    def setUp(self):
        self.schema = connection.schema_name

    def test_save_stamps_current_schema(self):
        log = AuditLog.objects.create(action="login", resource_type="user", resource_id="1")
        self.assertEqual(log.schema_name, self.schema)

    def test_explicit_schema_name_is_preserved(self):
        log = AuditLog.objects.create(
            action="login", resource_type="user", resource_id="2", schema_name="explicit_clinic"
        )
        self.assertEqual(log.schema_name, "explicit_clinic")

    def test_for_current_tenant_excludes_other_schemas(self):
        mine = AuditLog.objects.create(action="create", resource_type="patient", resource_id="a")
        # A row attributed to a different tenant must NOT surface here.
        AuditLog.objects.create(
            action="create", resource_type="patient", resource_id="b", schema_name="other_clinic"
        )
        scoped_ids = set(AuditLog.for_current_tenant().values_list("id", flat=True))
        self.assertIn(mine.id, scoped_ids)
        self.assertNotIn(
            AuditLog.objects.get(resource_id="b", schema_name="other_clinic").id, scoped_ids
        )

    def test_remains_append_only(self):
        log = AuditLog.objects.create(action="login", resource_type="user", resource_id="3")
        with self.assertRaises(ValueError):
            log.save()
        with self.assertRaises(ValueError):
            log.delete()

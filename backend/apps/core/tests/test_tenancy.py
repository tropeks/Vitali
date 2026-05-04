"""Tests for tenant-aware background task helpers."""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from apps.core.tenancy import for_each_tenant_schema


class ForEachTenantSchemaTests(SimpleTestCase):
    def test_runs_only_current_schema_when_already_in_tenant(self):
        callback = Mock(return_value=7)
        logger = Mock()

        with patch(
            "apps.core.tenancy.connection",
            SimpleNamespace(schema_name="tenant_a"),
        ):
            result = for_each_tenant_schema(
                callback,
                logger=logger,
                operation="test_operation",
            )

        self.assertEqual(result, [7])
        callback.assert_called_once_with("tenant_a")
        logger.exception.assert_not_called()

    def test_public_schema_iterates_tenants_and_continues_after_failure(self):
        callback = Mock(side_effect=[3, RuntimeError("boom")])
        logger = Mock()
        tenant_model = Mock()
        tenant_model.objects.exclude.return_value = [
            SimpleNamespace(schema_name="tenant_a"),
            SimpleNamespace(schema_name="tenant_b"),
        ]

        with (
            patch("apps.core.tenancy.connection", SimpleNamespace(schema_name="public")),
            patch("apps.core.tenancy.get_tenant_model", return_value=tenant_model),
            patch("apps.core.tenancy.schema_context", side_effect=lambda schema: nullcontext()),
        ):
            result = for_each_tenant_schema(
                callback,
                logger=logger,
                operation="test_operation",
            )

        self.assertEqual(result, [3])
        self.assertEqual(callback.call_count, 2)
        logger.exception.assert_called_once()

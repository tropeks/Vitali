"""Helpers for code paths that may run inside or outside a tenant schema."""

import logging
from collections.abc import Callable
from typing import Any

from django.db import connection
from django_tenants.utils import get_tenant_model, schema_context


def for_each_tenant_schema(
    callback: Callable[[str], Any],
    *,
    logger: logging.Logger,
    operation: str,
) -> list[Any]:
    """
    Run callback in the current tenant schema, or across all tenants from public.

    Celery beat starts in the public schema. Tenant model queries made from that
    context fail because tenant app tables live in each tenant schema. Interactive
    tests and request-triggered code often already have an active tenant schema;
    in that case, running only the current schema preserves existing semantics.
    """
    current_schema = getattr(connection, "schema_name", "public")
    if current_schema != "public":
        return [callback(current_schema)]

    Tenant = get_tenant_model()
    results = []
    for tenant in Tenant.objects.exclude(schema_name="public"):
        try:
            with schema_context(tenant.schema_name):
                results.append(callback(tenant.schema_name))
        except Exception:
            logger.exception("%s failed for tenant %s", operation, tenant.schema_name)
    return results

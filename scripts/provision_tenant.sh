#!/usr/bin/env bash
# scripts/provision_tenant.sh
# Idempotent script to provision a new tenant
# Usage: ./scripts/provision_tenant.sh <schema_name> <domain_name> <tenant_name>

set -euo pipefail

if [ "$#" -lt 3 ]; then
    echo "Usage: $0 <schema_name> <domain_name> <tenant_name>"
    exit 1
fi

SCHEMA_NAME="$1"
DOMAIN_NAME="$2"
TENANT_NAME="$3"

echo "Provisioning tenant: $TENANT_NAME ($SCHEMA_NAME at $DOMAIN_NAME)..."

compose_cmd=(docker compose -f docker-compose.yml)
if [ -f "docker-compose.override.yml" ]; then
    compose_cmd=(docker compose -f docker-compose.yml -f docker-compose.override.yml)
elif [ -f "docker-compose.prod.yml" ]; then
    compose_cmd=(docker compose -f docker-compose.yml -f docker-compose.prod.yml)
fi

echo "Ensuring public schema is migrated..."
"${compose_cmd[@]}" exec -T django python manage.py migrate_schemas --schema=public

echo "Creating tenant and domain..."
"${compose_cmd[@]}" exec -T django python manage.py shell -c "
from django.db import transaction
from apps.core.models import Tenant, Domain

with transaction.atomic():
    tenant, created = Tenant.objects.get_or_create(
        schema_name='$SCHEMA_NAME',
        defaults={'name': '$TENANT_NAME', 'slug': '$SCHEMA_NAME'}
    )
    if created:
        print(f'Tenant {tenant.name} created.')
    else:
        print(f'Tenant {tenant.name} already exists.')
    
    domain, d_created = Domain.objects.get_or_create(
        domain='$DOMAIN_NAME',
        defaults={'tenant': tenant, 'is_primary': True}
    )
    if d_created:
        print(f'Domain {domain.domain} created.')
    else:
        print(f'Domain {domain.domain} already exists.')
"

echo "Migrating tenant schema..."
"${compose_cmd[@]}" exec -T django python manage.py migrate_schemas --schema="$SCHEMA_NAME"

echo "Tenant provisioned successfully!"

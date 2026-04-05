# Vitali — Multi-Tenant Migration Strategy

> Safe procedure for running `migrate_schemas` in production across N tenants, with rollback.

---

## Rule: All Tenant Migrations Must Be Additive-Only

**Never drop a column, rename a column, or change a column type in a single migration.**

Always use a two-phase approach:

1. **Phase 1** — Add the new column (nullable, with a default). Deploy. Verify.
2. **Phase 2** — Drop the old column or add the NOT NULL constraint. Deploy in the next release.

This ensures that if a migration fails halfway through N tenants, the application keeps running on the tenants that have not yet migrated (they still see the old schema). Rolling back does not require touching any data.

**Why this matters:** `migrate_schemas` runs migrations tenant-by-tenant. If tenant #47 of 200 fails, tenants 1–46 have the new schema and tenants 47–200 still have the old one. The app must work against both until the issue is resolved.

---

## Pre-Migration: Per-Tenant Snapshot

Before running any migration, take a logical backup of each tenant's schema. For staging with a small number of tenants, snapshot all at once. In production, snapshot each tenant immediately before its migration.

```bash
# Snapshot all tenant schemas (run on the DB host or via docker exec)
TENANTS=$(docker compose -f docker-compose.staging.yml exec -T django \
  python manage.py shell -c "
from apps.tenants.models import Tenant
print(' '.join(t.schema_name for t in Tenant.objects.exclude(schema_name='public')))
" 2>/dev/null)

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
mkdir -p /opt/vitali/backups/${TIMESTAMP}

for SCHEMA in $TENANTS; do
  docker compose -f docker-compose.staging.yml exec -T postgres \
    pg_dump \
      -U ${POSTGRES_USER:-vitali} \
      -d ${POSTGRES_DB:-vitali} \
      --schema=${SCHEMA} \
      --no-owner \
      --no-acl \
    > /opt/vitali/backups/${TIMESTAMP}/${SCHEMA}.sql
  echo "Snapshotted: ${SCHEMA}"
done

echo "Backup complete: /opt/vitali/backups/${TIMESTAMP}/"
```

Verify backup size is non-zero before proceeding:

```bash
ls -lh /opt/vitali/backups/${TIMESTAMP}/
```

---

## Running Migrations Safely

### Step 1: Run shared (public schema) migrations first

The `public` schema holds tenant registry data (`tenants_tenant`, `tenants_domain`). Always migrate shared first.

```bash
docker compose -f docker-compose.staging.yml exec -T django \
  python manage.py migrate_schemas --shared --noinput
```

Check output for errors before proceeding. Any failure here is blocking — do not migrate tenant schemas if shared migration fails.

### Step 2: Run all tenant migrations

```bash
docker compose -f docker-compose.staging.yml exec -T django \
  python manage.py migrate_schemas --noinput
```

This iterates every tenant schema in sequence. Output looks like:

```
=== Running migrate for schema: clinica_alfa
  Applying billing.0004_add_invoice_notes... OK
=== Running migrate for schema: clinica_beta
  Applying billing.0004_add_invoice_notes... OK
...
```

### Step 3: Verify no unapplied migrations remain

```bash
docker compose -f docker-compose.staging.yml exec -T django \
  python manage.py showmigrations | grep "\[ \]"
# Should be empty
```

---

## Retrying a Single Failed Tenant

If one tenant's migration fails (network hiccup, schema corruption, lock timeout), retry it individually without touching the others:

```bash
# Replace "clinica_beta" with the failed tenant's schema_name
docker compose -f docker-compose.staging.yml exec -T django \
  python manage.py migrate_schemas --schema=clinica_beta --noinput
```

If this also fails, examine the migration manually:

```bash
# Connect to the tenant schema
docker compose -f docker-compose.staging.yml exec -T postgres \
  psql -U ${POSTGRES_USER:-vitali} -d ${POSTGRES_DB:-vitali} \
  -c "SET search_path TO clinica_beta; \SELECT * FROM django_migrations ORDER BY id DESC LIMIT 10;"
```

Common causes:
- **Lock timeout**: Another process has a long-running transaction. Check `pg_stat_activity`.
- **Schema corruption**: A previous partial migration left an inconsistent state. Restore from snapshot (see Rollback section).
- **Data constraint violation**: The additive-only rule was violated. The migration must be rewritten.

---

## Rollback Procedure

**Disclosure: Rolling back tenant schema migrations requires downtime for the affected tenant(s).**

There is no automated down-migration for tenant schemas. The procedure is:

1. Put the affected tenant into maintenance mode (or restrict access)
2. Restore the tenant schema from the pre-migration snapshot
3. Remove the migration record from `django_migrations` for that schema
4. Deploy the previous application version (or revert the migration file)
5. Verify the tenant is healthy
6. Re-enable access

### Step-by-step rollback for a single tenant

```bash
# 1. Restore the schema from backup (DESTRUCTIVE — replaces all data with snapshot)
SCHEMA=clinica_beta
BACKUP_FILE=/opt/vitali/backups/${TIMESTAMP}/${SCHEMA}.sql

docker compose -f docker-compose.staging.yml exec -T postgres \
  psql -U ${POSTGRES_USER:-vitali} -d ${POSTGRES_DB:-vitali} \
  -c "DROP SCHEMA IF EXISTS ${SCHEMA} CASCADE; CREATE SCHEMA ${SCHEMA};"

docker compose -f docker-compose.staging.yml exec -T postgres \
  psql -U ${POSTGRES_USER:-vitali} -d ${POSTGRES_DB:-vitali} \
  < ${BACKUP_FILE}

echo "Schema restored from ${BACKUP_FILE}"

# 2. Remove the failed migration record from django_migrations
# (so Django does not think the migration is applied)
docker compose -f docker-compose.staging.yml exec -T postgres \
  psql -U ${POSTGRES_USER:-vitali} -d ${POSTGRES_DB:-vitali} \
  -c "SET search_path TO ${SCHEMA}; DELETE FROM django_migrations WHERE name='0004_add_invoice_notes';"

# 3. Verify the tenant schema is clean
docker compose -f docker-compose.staging.yml exec -T django \
  python manage.py migrate_schemas --schema=${SCHEMA} --run-syncdb --noinput
```

### Full rollback (all tenants)

If the migration was catastrophic and affects all tenants, restore from the full pre-migration backup and redeploy the previous image tag:

```bash
# See docs/DEPLOY.md — "Rollback to a specific image tag"
# Then restore each tenant schema from /opt/vitali/backups/${TIMESTAMP}/
```

---

## Production Checklist Before Any Migration

- [ ] Pre-migration snapshot taken and verified (non-zero size)
- [ ] Migration is additive-only (no drops, no renames, no type changes)
- [ ] Migration tested on a staging tenant first
- [ ] Peak traffic window avoided (prefer early morning or scheduled maintenance)
- [ ] At least one engineer monitoring logs during `migrate_schemas` run
- [ ] Rollback procedure reviewed and backup path confirmed accessible

---

*Vitali — docs/TENANT_MIGRATIONS.md*

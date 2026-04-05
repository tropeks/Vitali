# Vitali — Performance Indexes (S-058)

Added in Sprint 14 for pilot readiness. All indexes added with `CONCURRENTLY` where possible (zero-downtime on live tables).

## Index inventory

| Table | Index | Type | Migration | Purpose |
|-------|-------|------|-----------|---------|
| `emr_appointment` | `emr_appointment_start_date_saopaulo_idx` | Expression | emr/0008 | `DATE(start_time AT TIME ZONE 'America/Sao_Paulo')` — speeds `__date` lookups on the agenda view |
| `emr_patient` | `emr_patient_insurance_data_gin_idx` | GIN (`jsonb_path_ops`) | emr/0008 | JSONB containment queries on `insurance_data` (e.g. filter by operator code) |
| `core_auditlog` | `core_auditlog_action_created_idx` | B-tree composite | core/0006 | `(action, created_at)` — security monitoring queries by action type |
| `billing_pixcharge` | `billing_pix_status_expires_idx` | B-tree composite | billing/0002 | `(status, expires_at)` — periodic expiry sweep (`expire_pix_charges` task) |
| `billing_tissguide` | `billing_tis_status_cdef3d_idx` | B-tree composite | billing/0001 | `(status, created_at)` — existing, covers billing dashboard |

## How to verify

```bash
# Connect to DB
docker compose exec db psql -U vitali vitali

# List indexes on appointment table
\d+ emr_appointment

# Check index usage after a week of prod traffic
SELECT indexrelname, idx_scan, idx_tup_read
FROM pg_stat_user_indexes
WHERE relname = 'emr_appointment'
ORDER BY idx_scan DESC;
```

## Query patterns these indexes support

### Agenda view (most frequent query)
```python
# Before: sequential scan on start_time, couldn't use existing btree for date extract
Appointment.objects.filter(start_time__date=today, professional=prof)
# After: uses emr_appointment_start_date_saopaulo_idx (function index)
```

### Insurance data filtering
```python
# Before: sequential scan on JSONB column
Patient.objects.filter(insurance_data__operator_code="001")
# After: uses GIN index with jsonb_path_ops
```

### Audit log security queries
```python
# Before: filtered on created_at index, then rechecked action
AuditLog.objects.filter(action="login", created_at__gte=last_week)
# After: composite index eliminates recheck
```

## Adding new indexes

Use `RunSQL` with `CONCURRENTLY` for expression/GIN indexes — Django's `models.Index`
only creates standard B-tree indexes and cannot express function indexes.

Always include the reverse SQL (`DROP INDEX IF EXISTS`) so migrations can be rolled back.

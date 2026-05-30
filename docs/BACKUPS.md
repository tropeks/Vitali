# Vitali — Backup & Restore

PostgreSQL backups use `pg_dump` in custom format (`-Fc`), which produces
compressed, splittable dumps that `pg_restore` can restore selectively.

---

## Automated backups (staging)

The `db-backup` service in `docker-compose.staging.yml` runs `scripts/backup.sh`
**daily at 02:00 UTC** via busybox `crond` (built into the alpine image — no
extra packages needed).

### Enabling the service

The service is gated behind the `backup` Docker Compose profile so it does not
start unless you explicitly opt in:

```bash
# Start everything including the backup service
docker compose -f docker-compose.staging.yml --profile backup \
  --env-file .env.staging up -d
```

Or start/restart only the backup service on a running stack:

```bash
docker compose -f docker-compose.staging.yml --profile backup \
  --env-file .env.staging up -d db-backup
```

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `BACKUP_KEEP_LAST` | `7` | Number of most-recent dumps to retain |
| `POSTGRES_DB` | `vitali` | Database name |
| `POSTGRES_USER` | `vitali` | Database user |
| `POSTGRES_PASSWORD` | *(required)* | Database password |

Add `BACKUP_KEEP_LAST=14` to `.env.staging` to keep two weeks of backups.

### Where backups land

Dumps are written to the `backups` Docker named volume, mounted at `/backups`
inside the container. File names follow the pattern:

```
vitali_20260115T020001Z.dump
```

Inspect the volume on the host:

```bash
docker run --rm \
  -v vitali_backups:/backups \
  alpine ls -lh /backups
```

---

## Manual backup

### Development (docker compose)

```bash
make backup
# Writes to ./backups/vitali_TIMESTAMP.dump
```

### Staging (on the server)

```bash
# Trigger a one-off backup inside the running db-backup container:
docker compose -f docker-compose.staging.yml exec db-backup /usr/local/bin/backup.sh

# Or dump directly from the postgres container:
docker compose -f docker-compose.staging.yml exec -T postgres \
  sh -c 'PGPASSWORD=$POSTGRES_PASSWORD pg_dump -U $POSTGRES_USER -Fc $POSTGRES_DB' \
  > vitali_manual_$(date -u +%Y%m%dT%H%M%SZ).dump
```

---

## Restore procedure

> **Warning:** Restoration is destructive — existing data is dropped and
> replaced. Stop application traffic (or take django offline) before restoring
> to avoid partial-write conflicts.

### Development

```bash
make restore file=backups/vitali_20260115T020001Z.dump
```

### Staging (on the server)

```bash
# 1. Scale django to 0 so no writes happen during restore
docker compose -f docker-compose.staging.yml stop django celery-worker celery-beat

# 2. Copy the dump file into the postgres container and restore
docker compose -f docker-compose.staging.yml exec -T postgres \
  sh -c 'PGPASSWORD=$POSTGRES_PASSWORD pg_restore -Fc -U $POSTGRES_USER -d $POSTGRES_DB --clean --if-exists' \
  < vitali_20260115T020001Z.dump

# 3. Restart services
docker compose -f docker-compose.staging.yml start django celery-worker celery-beat
```

### Partial restore (single schema / table)

```bash
# List what is inside a dump:
pg_restore --list vitali_20260115T020001Z.dump | grep -i <table_or_schema>

# Restore only a specific schema:
docker compose exec -T postgres \
  sh -c 'PGPASSWORD=$POSTGRES_PASSWORD pg_restore -Fc -U $POSTGRES_USER -d $POSTGRES_DB \
         --schema=<schema_name> --clean --if-exists' \
  < vitali_20260115T020001Z.dump
```

---

## Verifying a backup

```bash
# Check the dump is readable without actually restoring it:
pg_restore --list vitali_20260115T020001Z.dump > /dev/null && echo "OK"
```

---

## Offsite backup — S3 recommendation

Keeping backups only on the same host as the database is a single point of
failure. For production-grade durability, ship each dump to an S3-compatible
bucket immediately after it is written.

### Minimal addition to scripts/backup.sh

```bash
# After the pg_dump line, add:
if [ -n "${S3_BUCKET:-}" ]; then
  echo "[backup] Uploading to s3://${S3_BUCKET}/vitali/${BACKUP_FILE##*/}"
  aws s3 cp "${BACKUP_FILE}" "s3://${S3_BUCKET}/vitali/${BACKUP_FILE##*/}" \
    --storage-class STANDARD_IA
fi
```

Set `S3_BUCKET=my-vitali-backups` and ensure the host/container has AWS
credentials (IAM role, instance profile, or `AWS_ACCESS_KEY_ID` /
`AWS_SECRET_ACCESS_KEY` env vars).

### Recommended S3 lifecycle policy

Apply these rules to the bucket prefix `vitali/`:

| Rule | Value |
|---|---|
| Transition to Glacier IR | After 30 days |
| Expire objects | After 365 days |
| Enable versioning | Yes (protection against accidental delete) |

### Alternative tools

| Tool | Use case |
|---|---|
| [Restic](https://restic.net) | Encrypted, deduplicated backups to S3, B2, or SFTP |
| [pgBackRest](https://pgbackrest.org) | Full/incremental WAL-based backups; point-in-time recovery |
| AWS RDS automated backups | If migrating to RDS — zero-ops, 35-day retention, PITR included |

For a clinic handling patient data under LGPD, S3 server-side encryption
(SSE-S3 or SSE-KMS) and a separate AWS account for the backup bucket are
strongly recommended to satisfy data isolation requirements.

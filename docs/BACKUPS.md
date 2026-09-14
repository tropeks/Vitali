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

---

## At-rest encryption (required) + offsite upload (optional)

`scripts/backup.sh` **refuses to run** unless `BACKUP_ENCRYPTION_KEY` is set —
pg_dump output contains LGPD-regulated clinical data (EMR), so an unencrypted
dump is never written to disk. This is enforced twice, on purpose:

1. **`scripts/backup.sh` itself** — the primary guard. It exits non-zero
   *before* running `pg_dump` if the key is missing (`[backup] ERROR: BACKUP_ENCRYPTION_KEY
   is not set …`), because `db-backup` is a bare `postgres:16-alpine` container
   that never loads Django — nothing else can stop a misconfigured nightly cron
   run.
2. **`vitali/settings/production.py`** — a redundant, deploy-time guard. It
   refuses to boot `django`/`celery-worker`/`celery-beat` (which share the same
   secrets file) when the key is missing, turning a failure that would
   otherwise surface silently at 02:00 UTC in a container nobody tails the logs
   of into a loud failure at deploy time instead.

To explicitly run without encryption (e.g. a throwaway pilot with **no real
patient data**), set `BACKUP_ALLOW_PLAINTEXT=1` for both the `db-backup`
service and the Django processes. Never set it against a deployment holding
real clinical data.

| Env | Purpose |
|-----|---------|
| `BACKUP_ENCRYPTION_KEY` | GPG symmetric (AES256) passphrase. **Required.** Dump is encrypted to `.dump.gpg` before leaving the box. |
| `BACKUP_ALLOW_PLAINTEXT` | Explicit opt-out of the requirement above (`1`). Only for environments with no real patient data. |
| `BACKUP_S3_BUCKET` | Destination bucket. Optional — triggers upload of the (encrypted) artifact. |
| `BACKUP_S3_ENDPOINT` | Custom endpoint for non-AWS (e.g. Backblaze B2 `https://s3.<region>.backblazeb2.com`). Omit for AWS. |
| `BACKUP_S3_PREFIX` | Key prefix inside the bucket (default `vitali`). |
| `BACKUP_S3_ACCESS_KEY` / `BACKUP_S3_SECRET_KEY` | S3 credentials. |

The `db-backup` service in `docker-compose.prod.yml` installs `gpg` + `aws-cli`
at startup and snapshots these envs into `/etc/backup.env` for the cron job. Upload
failures exit non-zero and log `[backup] ERROR …` — they are never silent.

> **`docker-compose.staging.yml` gaps (two, stacked):** unlike
> `docker-compose.prod.yml`, the staging `db-backup` service (1) does not
> forward `BACKUP_ENCRYPTION_KEY` / `BACKUP_ALLOW_PLAINTEXT` into its container
> — its `environment:` block and `printenv` snapshot pattern only list
> `POSTGRES_*`, `BACKUP_DIR`, `KEEP_LAST` — and (2) never installs `gpg` at
> startup (prod's `command:` runs `apk add --no-cache gnupg aws-cli`; staging's
> does not). Fixing only the first still leaves backups failing with `'gpg' is
> not installed`. Both must be fixed in the compose file before this change
> ships to staging, or the nightly backup breaks every night.

**Generate the encryption key** with `scripts/gen_secrets.sh` and store it in an
offline vault. Losing `BACKUP_ENCRYPTION_KEY` makes every encrypted dump
unrecoverable — guard it like `FIELD_ENCRYPTION_KEY`.

### Bucket lifecycle (configure on the provider)

- Retain 30 daily + 12 monthly. Default local `BACKUP_KEEP_LAST=30` in prod.
- AWS S3: transition to Glacier IR after 30 days, expire after 365.
- Enable bucket versioning + SSE; use a separate account/project for backups (LGPD isolation).

## Restore drill (proves backups are restorable)

`scripts/restore_test.sh` pulls the most recent backup (local dir or S3), decrypts
it if needed, restores into a throwaway ephemeral Postgres container, runs sanity
checks, and tears down. Never touches prod/staging DBs — the ephemeral container
publishes no port and is only reachable via `docker exec`.

Sanity checks, in order:

1. `django_migrations` has rows (public schema restored and migrated).
2. `core_tenant` is queryable (public schema, `apps.core` — `SHARED_APPS`).
3. **Clinical data**: for every tenant found in `core_tenant`, its per-tenant
   Postgres schema (named after `Tenant.schema_name`, dynamic — not a fixed
   name) must contain at least one `emr_patient` row (`apps.emr` —
   `TENANT_APPS`) for at least one tenant. A restore that recreates the public
   schema and the tenant list but loses every patient's clinical record fails
   here — this is the check that actually proves an EMR restore, not just a
   schema restore. Skipped only when there are zero tenants (nothing to
   validate yet).
4. Total restored schema count (informational only).

```bash
# Local volume:
BACKUP_DIR=/var/lib/docker/volumes/vitali_backups/_data bash scripts/restore_test.sh
# From S3 (encrypted):
BACKUP_S3_BUCKET=my-bucket BACKUP_S3_ACCESS_KEY=… BACKUP_S3_SECRET_KEY=… \
  BACKUP_ENCRYPTION_KEY=… bash scripts/restore_test.sh
```

Schedule it **weekly** on the host (cron or a systemd timer). A backup you have
never restored is not a backup.

### Recovery objectives

- **RPO (max data loss): 24h** — backups run daily at 02:00 UTC.
- **RTO (max downtime): 4h** — provision host, restore latest dump, smoke test.

Tighter RPO requires WAL archiving / PITR (pgBackRest or RDS) — out of scope here.

## Imaging archive (Vitali Imagem)

PostgreSQL dumps do **not** contain DICOM instances. Production stores the image
archive in the persistent `orthanc_data` volume. Back it up independently with a
short, controlled ingest interruption so its embedded index and object files are
captured at the same point in time:

```bash
sudo install -d -m 0700 /var/backups/vitali/imaging
COMPOSE_FILE=docker-compose.prod.yml \
IMAGING_BACKUP_DIR=/var/backups/vitali/imaging \
IMAGING_BACKUP_KEEP_LAST=7 \
BACKUP_ENCRYPTION_KEY='from-the-offline-vault' \
bash scripts/backup_imaging.sh
```

The script stops only `orthanc`, creates a snapshot containing `orthanc-data/`
and the versioned runtime configuration, restarts it immediately, validates the
tar stream, and writes a SHA-256 sidecar. If the existing `BACKUP_S3_*` variables
are present, it uploads the encrypted artifact under `<prefix>/imaging/`.

Schedule the database and image jobs in the same maintenance window. Do not run
the image snapshot while a modality is actively sending a study. A typical host
cron entry is:

```cron
30 2 * * * cd /opt/vitali && set -a && . /etc/vitali/secrets.env && set +a && IMAGING_BACKUP_DIR=/var/backups/vitali/imaging bash scripts/backup_imaging.sh >> /var/log/vitali-imaging-backup.log 2>&1
```

### Non-destructive image restore drill

The drill never mounts or changes the production volume. It restores the newest
snapshot into a disposable Docker volume, starts the exact pinned archive image,
checks its authenticated `/system` endpoint, then removes the container and
volume:

```bash
IMAGING_BACKUP_DIR=/var/backups/vitali/imaging \
BACKUP_ENCRYPTION_KEY='from-the-offline-vault' \
bash scripts/restore_test_imaging.sh
```

Run this weekly after the PostgreSQL restore drill. For a real disaster restore,
provision a fresh stack, keep Django/Celery/Nginx stopped, restore PostgreSQL,
extract `orthanc-data/` into the new `orthanc_data` volume, start `orthanc`, run
the drill/smoke checks, and only then reopen application traffic. Never extract a
snapshot over a live archive.

## PostgreSQL point-in-time recovery (PITR)

The daily logical dump has an RPO of up to 24 hours. The opt-in
`docker-compose.pitr.yml` overlay adds continuous WAL archiving with a default
five-minute archive timeout. Combined with off-host WAL synchronization, the
operational target becomes:

- WAL generated by transactions archived locally within 5 minutes;
- completed segments synchronized off-host every minute;
- effective off-host RPO no greater than 10 minutes, verified by a forced WAL
  switch check every 5 minutes;
- weekly physical base backup and weekly non-destructive recovery drill;
- daily logical dump retained as an independent recovery path.

WAL synchronization requests S3 server-side encryption (`AES256` by default;
set `PITR_S3_SSE` to the value required by the provider/bucket policy). Transport
must use HTTPS. Bucket versioning, object lock and a separate backup account are
recommended controls against operator error and ransomware.

### Controlled enablement

Enabling `archive_mode` requires a PostgreSQL restart. It does not rewrite the
database, but Compose recreates the database container to add the WAL volume.
Do this in a maintenance window, after a successful logical backup and restore
drill:

```bash
COMPOSE=(docker compose -f docker-compose.prod.yml -f docker-compose.pitr.yml --env-file /etc/vitali/secrets.env)
"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" up -d postgres
COMPOSE_FILE=docker-compose.prod.yml PITR_COMPOSE_FILE=docker-compose.pitr.yml \
  PITR_FORCE_SWITCH=1 bash scripts/pitr_check.sh
"${COMPOSE[@]}" up -d
```

Keep both Compose files in every later `up`, `pull`, `ps`, backup and migration
command. Omitting the overlay on a subsequent deployment disables archiving and
removes the mount from the new container (the named volume itself is retained).

### Base backup

The physical base backup streams from the running database into a host-only
directory and runs `pg_verifybackup`; it does not stop or replace PostgreSQL:

```bash
sudo install -d -m 0700 /var/backups/vitali/pitr/base
PITR_BASEBACKUP_DIR=/var/backups/vitali/pitr/base \
PITR_BASEBACKUP_KEEP_LAST=5 \
COMPOSE_FILE=docker-compose.prod.yml \
bash scripts/pitr_basebackup.sh
```

When `BACKUP_S3_*` is present, the verified base is encrypted with the existing
`BACKUP_ENCRYPTION_KEY` and uploaded under `<prefix>/pitr/base/`. An unencrypted
upload is rejected unless the operator explicitly sets
`PITR_ALLOW_UNENCRYPTED_OFFSITE=1` for an object store whose mandatory KMS policy
has been independently verified. The script obtains the database password from
the running container and never writes it to the repository or backup directory.

### WAL offsite synchronization and monitoring

Run these from a root-owned cron/systemd unit so the sync process can read the
Docker volume. Credentials come from `/etc/vitali/secrets.env` (mode `0600`):

```cron
* * * * * cd /opt/vitali && set -a && . /etc/vitali/secrets.env && set +a && bash scripts/pitr_sync_wal.sh >> /var/log/vitali-pitr-wal.log 2>&1
*/5 * * * * cd /opt/vitali && set -a && . /etc/vitali/secrets.env && set +a && PITR_FORCE_SWITCH=1 bash scripts/pitr_check.sh >> /var/log/vitali-pitr-check.log 2>&1
```

Configure the object-store lifecycle to retain WAL for at least 35 days and base
backups for at least five weekly generations. Do not delete local WAL merely by
age: a recovery chain is usable only when all segments after its selected base
backup are available. Alert on sync/check failure and on WAL volume usage above
70%; prune only after confirming the corresponding objects off-host and the
oldest retained base-backup boundary.

### Non-destructive PITR drill

The drill verifies the newest base backup, copies it and the local WAL archive
to disposable volumes, creates `recovery.signal`, boots the pinned PostgreSQL 16
image, replays available WAL and validates `django_migrations`. Production data
and volumes are mounted read-only or not mounted at all:

```bash
PITR_BASEBACKUP_DIR=/var/backups/vitali/pitr/base \
COMPOSE_FILE=docker-compose.prod.yml \
PITR_COMPOSE_FILE=docker-compose.pitr.yml \
bash scripts/pitr_restore_test.sh
```

Passing this proves local recovery to the newest available WAL. Quarterly, run a
full isolated disaster exercise using only objects downloaded from offsite
storage, record achieved RPO/RTO, row counts and the recovered WAL endpoint, and
retain the signed drill report. PITR is not accepted as production-ready until
one such offsite-only exercise passes.

---

## Offsite — preparo guardado para a produção (ordem 004, encerrada como NÃO AGORA)

> **DECISÃO DO CAPITÃO, 2026-09-12 — isto NÃO é pendência esquecida.**
>
> A lab é ambiente de teste: perda de dado ali não é catástrofe, e proteger contra ela
> custa mais atenção do que vale hoje. **Backup fora do host só a partir do momento em que
> o Vitali virar produto — e aí vai para a nuvem, não para outro nó da Vulcan.**
>
> Dentro da Vulcan não existe offsite de verdade: a **R640 e o host VMware estão no mesmo
> rack** (confirmado). Copiar entre nós protege contra perda de VM, nunca contra perda de
> sítio — e chamar isso de offsite seria o tipo de verde mentiroso que o
> `.maestro/INTENT.md` §Limites proíbe.
>
> **O que staging tem, e é o que deve ter:** backup cifrado diário local (AES256, rodando
> sozinho às 02:00 UTC desde 12/09) e **drill de restore provado** (ordem 003).
>
> **O código abaixo está pronto e desligado.** `BACKUP_S3_BUCKET` vazio faz o `backup.sh`
> pular o bloco de upload inteiro. Ligar, no dia da produção, é preencher cinco variáveis —
> não há trabalho de código pela frente. Leia esta seção como runbook do futuro, não como
> tarefa aberta.
>
> **Recomendação, não bloqueio:** guardar a `BACKUP_ENCRYPTION_KEY` fora da máquina que ela
> protege. Enquanto for staging, perder as duas juntas custa dado de teste. No dia em que
> houver dado real, isso deixa de ser recomendação e vira pré-requisito de ligar o upload —
> um dump cifrado cuja chave morreu junto não é recuperação.

### O par que ninguém deve separar: chave e destino

Um dump cifrado num bucket, com a `BACKUP_ENCRYPTION_KEY` vivendo **apenas** na máquina
que o backup protege, **não é recuperação**. Se a máquina some, some o que abre o backup, e
o offsite vira volume pago de ruído. O `backup.sh` já avisa no cabeçalho: *"store it in an
offline vault — losing it makes every encrypted dump unrecoverable"*.

**Custódia da chave fora do host é pré-requisito de ligar o upload, não item posterior.**
Cifrar com chave que morre junto é pior que não cifrar: parece proteção.

### As variáveis, e os três lugares onde elas têm de aparecer

| Variável | Para quê |
|---|---|
| `BACKUP_S3_BUCKET` | vazio = offsite desligado |
| `BACKUP_S3_ENDPOINT` | omita para AWS; obrigatório em B2 e R2 |
| `BACKUP_S3_PREFIX` | raiz das chaves (default `vitali`) |
| `BACKUP_S3_ACCESS_KEY` / `_SECRET_KEY` | credencial **com escopo só neste prefixo** |
| `BACKUP_S3_COMPAT` | vazio para B2/AWS; `r2` para Cloudflare R2 |

**Variável nova precisa entrar em três lugares, e esquecer o terceiro é silencioso:**

1. `.env.staging` (o valor),
2. o bloco `environment:` do serviço `db-backup` no compose (para existir no container),
3. **o filtro `printenv | grep -E` do `command:` do mesmo serviço.**

O `crond` do busybox zera o ambiente, então o job noturno lê `/etc/backup.env`, montado por
aquele filtro. Variável que não casa o filtro **não existe para o backup automático** —
ainda que esteja nos outros dois lugares. Até 12/09 as `BACKUP_S3_*` estavam fora dele: quem
ligasse o offsite veria o upload funcionar num `docker compose exec` (ambiente completo) e o
cron pular o bloco em silêncio toda noite, escrevendo métrica de sucesso e saindo 0.

### Cloudflare R2: a pega do checksum

As CLIs e SDKs recentes da AWS mandam checksum **CRC32** por padrão em `PutObject`, e o R2
recusa:

```
Header 'x-amz-checksum-algorithm' with value 'CRC32' not implemented
```

`BACKUP_S3_COMPAT=r2` exporta `AWS_REQUEST_CHECKSUM_CALCULATION=when_required` e
`AWS_RESPONSE_CHECKSUM_VALIDATION=when_required`. Sem isso o upload falha com uma mensagem
que não se parece com "faltou configurar". **B2 e AWS não precisam de nada.**

### Retenção GFS — 30 diários + 12 mensais

Todo artefato se chama `vitali_<timestamp>.dump.gpg`; o nome não distingue diário de mensal.
E regra de lifecycle opera por **idade e prefixo**, nunca por *"guarde o primeiro de cada
mês"*. Então quem separa é o uploader:

```
s3://<bucket>/<prefix>/daily/vitali_*.dump.gpg      → expira em  30 dias
s3://<bucket>/<prefix>/monthly/vitali_*.dump.gpg    → expira em 365 dias
```

O mensal é uma **cópia** do mesmo artefato (mesma chave, idêntico byte a byte), promovida
quando ainda não existe mensal para a competência corrente. Deliberadamente **não** é *"se
hoje é dia 1"*: uma única noite falha no dia 1 custaria o mês inteiro, em silêncio, e só se
descobriria um ano depois.

**Volume em regime:** 25 MB/dia ⇒ ~750 MB em diários + ~300 MB em mensais ≈ **1,05 GB**.
Cabe no nível gratuito de 10 GB de B2 e R2 **permanentemente**.

Regra de lifecycle, do lado do bucket (não é código; é configuração do fornecedor):

```json
{"Rules": [
  {"ID": "vitali-daily-30d",    "Status": "Enabled",
   "Filter": {"Prefix": "vitali/daily/"},   "Expiration": {"Days": 30}},
  {"ID": "vitali-monthly-365d", "Status": "Enabled",
   "Filter": {"Prefix": "vitali/monthly/"}, "Expiration": {"Days": 365}}
]}
```

No B2 o equivalente é *Lifecycle Settings* por prefixo no painel do bucket; no R2, *Object
lifecycle rules*. **O `backup.sh` não poda o bucket** — a retenção dele (`KEEP_LAST`) é
explicitamente local.

### Drill de restore a partir do offsite — roteiro

O `restore_test.sh` já sabe puxar do bucket: com `BACKUP_S3_BUCKET` setado ele lista o
prefixo, pega o objeto mais recente e ignora o `BACKUP_DIR`. O que muda no roteiro é **de
onde vem o artefato** — e é a única prova que vale num incêndio, porque exercita a
credencial, a rede e o bucket, não só o `gpg` e o `pg_restore`.

```bash
# Na lab, sem tocar no staging. As credenciais entram pela mesma via da chave:
# lidas do .env por substituicao de comando, nunca ecoadas, nunca em argv.
cd /srv/vulcan/apps/vitali
bash scripts/run_restore_drill.sh \
  --env-file /srv/vulcan/apps/vitali/.env.staging \
  --from-s3 \
  --workdir /srv/vulcan/apps/vitali/drill \
  --reference /srv/vulcan/apps/vitali/migracao/inventario-LAB.txt \
  --inventory-sql /srv/vulcan/apps/vitali/migracao/inventario.sql
```

O que o drill tem de provar, e em que ordem:

1. **A credencial lê o bucket** — falha aqui é escopo de credencial, não backup.
2. **O artefato baixado decifra** com a chave em custódia — se a chave testada for a cópia
   do cofre, e não a do host, esta é a prova de que a custódia funciona.
3. **Restaura num banco descartável** com `emr_patient > 0` em algum tenant.
4. **Inventário conferido tabela a tabela** contra a referência.
5. **Limpeza verificada** — nenhum `.dump` em claro sobrando, nenhum container órfão.

Só depois dos cinco o RTO de 4h deste documento passa a ter base. Hoje ele é uma intenção.

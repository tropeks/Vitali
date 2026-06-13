# Sprint 27: Production Ops Foundation

> **STATUS: IMPLEMENTED (2026-06-12) — pending docker-host verification.**
> Código/scripts/compose/docs entregues e validados por sintaxe (bash -n, ast,
> yaml). Falta rodar num host com Docker: `docker compose -f docker-compose.prod.yml
> config`, `scripts/smoke_test.sh` contra o stack prod, `restore_test.sh` contra um
> backup real, e `pytest` do backend (boot checks). Issuance inicial de TLS é passo
> manual one-time (ver docs/TLS.md).

## Context (ler antes de começar)

- `docs/DEPLOY.md`, `docs/BACKUPS.md`, `docs/RUNBOOK.md`, `docs/TLS.md`, `docs/SECRETS.md`
- `docker-compose.staging.yml`, `scripts/backup.sh`, `scripts/smoke_test.sh`, `docker/nginx/`
- Estado: staging roda em VPS com deploy automático; produção NÃO existe ainda. Backup é só local (`pg_dump -Fc` diário, retenção 7). TLS configurado mas certs não provisionados. Secrets via `.env`.

## Goal

Deixar a infraestrutura pronta para receber uma clínica piloto em produção: backups duráveis e testados, TLS real, secrets fora de arquivos versionáveis, monitoring com alertas, e DR documentado com RPO/RTO.

## Planned Scope

### S27-01: Offsite Backups (S3-compatible)

- Estender `scripts/backup.sh` para enviar o dump para bucket S3-compatible (suportar AWS S3 e Backblaze B2 via env: `BACKUP_S3_ENDPOINT`, `BACKUP_S3_BUCKET`, `BACKUP_S3_ACCESS_KEY`, `BACKUP_S3_SECRET_KEY`).
- Criptografar o dump antes do upload (`age` ou GPG simétrico com `BACKUP_ENCRYPTION_KEY`; documentar a escolha).
- Lifecycle documentado: reter 30 diários + 12 mensais; instruções de configuração de lifecycle no bucket em `docs/BACKUPS.md`.
- Falha de upload deve ser reportada (exit code ≠ 0 + log estruturado), nunca silenciosa.

### S27-02: Restore Drill Automatizado

- Novo script `scripts/restore_test.sh`: baixa o último backup, restaura num Postgres efêmero (container), roda sanity checks (conta tenants, conta migrations aplicadas, um SELECT por app core).
- Agendar semanal (documentar cron/systemd timer no host; o script é o entregável).
- Documentar em `docs/BACKUPS.md`: RPO alvo = 24h, RTO alvo = 4h, procedimento completo de restore.

### S27-03: Production Compose + TLS

- Criar `docker-compose.prod.yml` a partir do staging: sem portas de debug, resource limits revisados, `restart: always`, healthchecks.
- TLS via Let's Encrypt (certbot) OU Cloudflare Tunnel — implementar certbot como default no nginx (renovação automática), documentar a alternativa Cloudflare em `docs/TLS.md`.
- HSTS já existe na config; validar que CSP report-only continua (enforcement de CSP é fora de escopo).

### S27-04: Secrets Hygiene

- Documentar em `docs/SECRETS.md` o fluxo de produção: secrets vivem só no host (`/etc/vitali/secrets.env`, root-only 0600), nunca no repo; staging continua como está.
- Adicionar ao boot check existente (fail-fast de placeholders) validação de TODOS os secrets críticos de produção: `FIELD_ENCRYPTION_KEY`, `MP/ASAAS keys` se configurados, `SENTRY_DSN` opcional mas warn.
- Script `scripts/gen_secrets.sh` que gera valores fortes para todos os secrets obrigatórios (template de `secrets.env`).

### S27-05: Monitoring & Alerting

- Habilitar Flower (Celery monitor) no compose de prod/staging atrás de auth básica.
- Sentry: garantir alert rules documentadas (error rate, novas issues) em `docs/RUNBOOK.md`; adicionar release tracking no deploy workflow se ainda não houver.
- Uptime: adicionar Uptime Kuma ao compose de prod (ou documentar serviço externo) monitorando `/health` backend + frontend.
- `docs/RUNBOOK.md`: adicionar seção de alertas (o que dispara, onde chega, o que fazer) e referência ao Flower.

### S27-06: DR Runbook

- Nova seção em `docs/RUNBOOK.md`: cenários (perda do VPS, corrupção de DB, vazamento de secret), passo a passo de recuperação usando S27-01/02, donos e tempos esperados (RPO 24h / RTO 4h).

## Acceptance Criteria

- `scripts/backup.sh` com envs S3 setadas envia dump criptografado para bucket; sem envs, comporta-se como hoje (local only) sem quebrar.
- `scripts/restore_test.sh` roda end-to-end contra um backup real de staging e termina com exit 0 + relatório.
- `docker compose -f docker-compose.prod.yml config` válido; smoke test (`scripts/smoke_test.sh`) passa contra o stack prod local.
- Boot de produção falha com mensagem clara se qualquer secret crítico estiver vazio/placeholder.
- Flower acessível com auth básica; Uptime Kuma (ou alternativa documentada) monitorando os healthchecks.
- `docs/BACKUPS.md`, `docs/TLS.md`, `docs/SECRETS.md`, `docs/RUNBOOK.md` atualizados.

## Verification Commands

```bash
bash -n scripts/backup.sh scripts/restore_test.sh scripts/gen_secrets.sh
docker compose -f docker-compose.prod.yml --env-file .env.staging.example config
COMPOSE_FILE=docker-compose.prod.yml scripts/smoke_test.sh
cd backend && pytest --reuse-db -q
```

## Out of Scope

- Provisionar o VPS de produção real (decisão de hosting é do Romulo)
- Migração para AWS ECS/RDS
- CSP enforcement

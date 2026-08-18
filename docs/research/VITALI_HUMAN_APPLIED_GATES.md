# Lote de gates que exigem aplicação humana (Ondas 0 e 1)

**Status:** pendente · **Motivo:** o hook do Maestro (ADR-003 v1.1) mantém `.github/workflows/` em
denylist — agentes não reescrevem workflow, nem com decision record. O item 1.3 depende de systemd,
que exige `sudo` (bloqueado pelo guard S-502). Este documento é a especificação; a aplicação é sua.

| # | Item | Onde | Efeito se não aplicado |
|---|---|---|---|
| 0.3 | `manage.py check --deploy` bloqueante | `.github/workflows/ci.yml` | O gate `core.E002` continua decorativo: nada impede desligar o isolamento multi-tenant de novo |
| 1.8 | Job de teste unitário do frontend | `.github/workflows/ci.yml` | 165 arquivos / ~700 testes de frontend podem quebrar sem bloquear merge |
| 1.3 | Drill de restore semanal | systemd timer no host | O drill continua sendo "recomendado semanalmente" e nunca executado |

---

## Item 0.3 — gate de deploy bloqueante

### Contexto

`backend/apps/core/checks.py:55-82` registra o system-check `core.E002`, que **falha se
`ENFORCE_TENANT_MEMBERSHIP` estiver `False` em produção**. Ele é registrado com `deploy=True`, e
`manage.py check --deploy` **não é executado por nenhum workflow** (`grep` em `.github/workflows/`
retorna vazio). O gate nunca dispara.

### Onde

`.github/workflows/ci.yml`, job `backend-lint`, como **último step** — depois de
`"Verify translation catalogs are compiled"`, antes da linha em branco que precede o comentário
`# ─── Backend: Tests ───`.

Escolhido `backend-lint` e não `backend-test` porque `settings/production.py` não abre conexão de DB
nem de cache no carregamento nem em `AppConfig.ready()` — só no atendimento real de request. O check
não precisa dos services Postgres/Redis, e o sinal chega no job mais rápido.

### Aplicar

```yaml
      # Onda 0 / item 0.3: core.E002 (apps/core/checks.py) só roda sob --deploy.
      # Sem este step o gate de ENFORCE_TENANT_MEMBERSHIP é decorativo e um deploy
      # futuro pode desligar o isolamento multi-tenant sem detecção.
      # Valores abaixo são placeholders de CI, não segredos reais.
      - name: Django deploy checks (multi-tenant isolation gate)
        env:
          DJANGO_SETTINGS_MODULE: vitali.settings.production
          ENVIRONMENT: production
          DEPLOYMENT_PROFILE: pool
          ENFORCE_TENANT_MEMBERSHIP: "true"
          SECRET_KEY: ci-placeholder-not-a-real-secret-key-000000000000
          ALLOWED_HOSTS: example.com
          DATABASE_URL: postgres://vitali:vitali@127.0.0.1:5432/vitali
          POSTGRES_PASSWORD: ci-placeholder
          REDIS_PASSWORD: ci-placeholder
          WHATSAPP_EVOLUTION_API_KEY: ci-placeholder
          FIELD_ENCRYPTION_KEY: ${{ secrets.CI_FIELD_ENCRYPTION_KEY }}
        run: python manage.py check --deploy
```

### Notas

1. `FIELD_ENCRYPTION_KEY` precisa ser uma chave Fernet **válida** (44 chars base64url) —
   `assert_field_encryption_key` em `vitali/settings/_security_checks.py` rejeita o placeholder zero.
   Gere uma descartável e guarde como secret do repositório:
   ```
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
   Ela não cifra nada em CI (nenhum dado é gravado), mas não deve ficar literal no YAML.
2. **Não** adicionar `|| true` nem `continue-on-error`. O `ci.yml` hoje está limpo desses
   anti-padrões (verificado: zero ocorrências) e o valor do gate depende disso.
3. Se falhar por warnings de segurança do Django (W004/W008/W012/W016/W018/W019): não deveria
   acontecer, porque `production.py` já hardcoda `SECURE_HSTS_*`, `SECURE_SSL_REDIRECT`,
   `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `DEBUG=False` e `X_FRAME_OPTIONS`. Se acontecer,
   investigue o warning específico — **não enfraqueça o gate** com `--fail-level` nem skip genérico.

### Prova de que o gate funciona

Rode uma vez com `ENFORCE_TENANT_MEMBERSHIP: "false"` no env do step. O job **deve ficar vermelho**
com `core.E002`. Se ficar verde, o gate não está pegando e o step precisa ser revisto. Volte para
`"true"` depois do teste.

---

## Item 1.8 — teste unitário do frontend no CI

### Contexto

`frontend/package.json` define `"test": "vitest run"`, e existem **165 arquivos** de teste com ~700
casos. O `ci.yml` tem 5 jobs (`backend-lint`, `backend-test`, `frontend-lint`, `frontend-e2e`,
`docker-validate`) e **nenhuma ocorrência de `vitest` ou `npm run test`**. A suíte existe, dá a
sensação de cobertura, e não é gate.

### Onde

`.github/workflows/ci.yml`, job `frontend-lint`, como último step (depois de `"TypeScript check"`).
Vai como step e não como job novo porque o `frontend-lint` já pagou `npm ci` — e o CI já leva ~41 min.

### Aplicar

```yaml
      # Onda 1 / item 1.8: 165 arquivos de teste de frontend não eram executados
      # por nenhum job. O wrapper existe porque o vitest pode encerrar com exit 0
      # mesmo quando workers morrem por timeout (observado: 15 de 165 arquivos
      # falharam por "Timeout waiting for worker" e o processo saiu 0) — isso
      # produziria verde falso, que é pior que não ter o gate.
      - name: Unit tests (vitest)
        run: |
          set -o pipefail
          npm run test 2>&1 | tee /tmp/vitest.log
          if grep -q "Timeout waiting for worker" /tmp/vitest.log; then
            echo "::error::vitest workers timed out — resultado não é confiável"
            exit 1
          fi
          if ! grep -qE "Test Files +[0-9]+ passed" /tmp/vitest.log; then
            echo "::error::vitest não reportou arquivos executados"
            exit 1
          fi
```

### Notas

1. O `grep` de timeout **não é paranoia**: foi observado empiricamente nesta máquina. Sem ele,
   arquivos inteiros podem sumir de uma run e o job fica verde.
2. Se o timeout se reproduzir no runner do GitHub (recurso menor que o desta box), a correção certa é
   ajustar o pool do vitest (`--pool=forks`, `--maxWorkers`), **não** remover a checagem.
3. Espere que os 165 arquivos passem — eles nunca rodaram em CI, então a primeira execução pode
   revelar quebras acumuladas. Se revelar, isso **é** o valor do item, não um obstáculo a ele.

---

## Item 1.3 — drill de restore semanal

### Por que não é um workflow

O drill (`scripts/restore_test.sh`) precisa dos dumps, que vivem no **host**
(`/var/lib/docker/volumes/vitali_backups/_data`), e do daemon do Docker para subir o Postgres
efêmero (`restore_test.sh:40` aborta sem docker). Um runner do GitHub não alcança nenhum dos dois.
O lugar certo é um **systemd timer no host** — o que também evita a denylist de workflows, mas exige
`sudo` (bloqueado pelo guard S-502 nesta sessão).

### Pré-requisito

O item 1.1 corrige um bug que faz o drill **falhar por construção** (`restore_test.sh:113` consulta
`tenants_tenant`, tabela inexistente — a real é `core_tenant`). **Não agende antes de rodar o drill
manualmente uma vez e vê-lo verde**, senão você agenda uma falha semanal.

### Aplicar

`/etc/systemd/system/vitali-restore-drill.service`:

```ini
[Unit]
Description=Vitali — drill semanal de restore de backup
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
User=root
WorkingDirectory=/home/rcosta00/dev/vitali
Environment=BACKUP_DIR=/var/lib/docker/volumes/vitali_backups/_data
ExecStart=/bin/bash scripts/restore_test.sh
StandardOutput=journal
StandardError=journal
```

`/etc/systemd/system/vitali-restore-drill.timer`:

```ini
[Unit]
Description=Dispara o drill de restore do Vitali toda segunda às 04:00

[Timer]
OnCalendar=Mon *-*-* 04:00:00
Persistent=true
RandomizedDelaySec=600

[Install]
WantedBy=timers.target
```

```
sudo systemctl daemon-reload
sudo systemctl enable --now vitali-restore-drill.timer
systemctl list-timers vitali-restore-drill.timer
```

### Fechando o laço com o item 1.4

Um drill agendado que falha em silêncio é tão inútil quanto nenhum drill. Depois que o Alertmanager
estiver de pé, faça o `restore_test.sh` escrever o resultado num arquivo `.prom` para o textfile
collector do node_exporter, e adicione a regra correspondente — mesmo mecanismo do
`VitaliBackupStale`. Assim "o drill parou de rodar" e "o drill rodou e falhou" viram alertas, em vez
de linhas no journal que ninguém lê.

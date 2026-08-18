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

### Addendum (Onda 2 / item 2.6, 2026-08-18)

`backend/apps/core/checks.py` ganhou um novo check `core.E008`
(`check_catalogs_loaded_in_production`, mesmo padrão `Tags.security, deploy=True` de E002/E003/E004):
falha se TUSS/ANVISA/SIGTAP/CID-10/CNES/CBO/CID-O/UCUM estiverem vazios em produção. **Não precisa de
step de CI separado** — ele roda automaticamente assim que o step acima (`check --deploy`) for aplicado,
porque `--deploy` executa todo check registrado com `deploy=True`, não um por vez. Só o CI env do step
precisa continuar apontando para um banco de dados real acessível (hoje `backend-lint` não abre conexão
de banco — ver nota original abaixo sobre por que `backend-lint` foi escolhido). Se E008 disparar em CI
com um banco vazio de propósito (ex.: banco de teste limpo), isso é esperado e correto: em CI/dev o
`ENVIRONMENT` não é `"production"`, então o check retorna vazio (silencioso) a menos que alguém force
`ENVIRONMENT=production` no step — o que o step de 0.3 já faz. Ou seja: **depois de aplicar 0.3, o
próprio CI job vai falhar com core.E008** até que os catálogos estejam carregados no banco que o step usa
— o que não é o caso hoje (o step usa um Postgres efêmero do runner, sempre vazio). Duas opções para quem
for aplicar isto: (a) usar `--allow-empty`-equivalente para E008 (não existe hoje — o check não tem essa
opção, só o management command `verify_catalogs` tem) enquanto o gate de CI não tiver um banco com
catálogos; ou (b) restringir 0.3 a rodar só no deploy real (fora do CI de PR), não no `backend-lint` de
todo PR. Ver `docs/DEPLOY.md` ("Reference Catalogs") para o gate real (`verify_catalogs`), que roda no
host de deploy, não no CI, e não tem esse problema porque o banco ali é o de produção/staging de verdade.

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

---

## Item 1.4b — webhook na bridge Hermes `[BLOQUEADO — aguarda autorização]`

**Status:** não executado. Nenhum `POST`, nenhuma alteração, nenhum recurso criado.
**Motivo:** é configuração de infraestrutura **externa ao repositório Vitali**. Alterá-la exige
autorização explícita do operador, que não foi dada.

### O que foi feito (escopo exato)

Somente descoberta read-only, para levantar os dados desta decisão:

| Ação | Resultado |
|---|---|
| `GET 127.0.0.1:9119/` · `/health` · `/healthz` | 200, SPA HTML |
| `GET /docs` | 200, UI de documentação |
| `GET /openapi.json` | 200, spec salvo em arquivo local de scratchpad |

Nada além disso. Nenhum webhook criado, habilitado, listado ou modificado.

### O que a integração exigiria

O Alertmanager (item 1.4) já está pronto e parametrizado: ele lê o destino de
`ALERTMANAGER_WEBHOOK_URL` via `url_file`. Ligar na bridge significa (a) criar um webhook no Hermes e
(b) apontar essa variável para a URL resultante. Nada no repositório Vitali precisa mudar.

**Contrato do endpoint** (`POST /api/webhooks`, Hermes Agent 0.20.1) — campos declarados no spec:

```
name           (obrigatório)   events        deliver        secret
description                    prompt        deliver_only
script                         skills        deliver_chat_id
```

### O ponto que exige decisão consciente

O webhook aceita **`prompt`, `script` e `skills`**. Um webhook do Hermes não é apenas um canal de
entrega: ele pode **executar um prompt de agente ou um script** quando acionado.

Se o webhook for criado com `prompt` ou `script`, o corpo do alerta do Alertmanager passa a ser
**entrada de um agente com capacidade de execução**. Os rótulos de um alerta são majoritariamente
controlados pela configuração, mas `instance`, `mountpoint` e anotações derivadas de séries podem
carregar texto vindo do ambiente monitorado. É uma superfície de injeção que não existe hoje.

**Recomendação:** criar com `deliver_only: true` e **sem** `prompt`/`script`/`skills` — entrega pura,
sem execução. Isso resolve o item 1.4 (alerta chega num humano) sem abrir superfície nova.

### Dados que sairiam do stack Vitali

As 6 regras hoje em `alerts.yml` são todas de infraestrutura:

`VitaliTelemetryTargetDown` · `VitaliHighServerErrorRatio` · `VitaliHostDiskLow` ·
`VitaliRedisMemoryHigh` · `VitaliPostgresConnectionsHigh` · `VitaliBackupStale`

**Nenhuma contém dado de paciente.** O payload leva `alertname`, `severity`, rótulos de instância/job,
e o texto de `summary` definido no próprio YAML. Não há PHI, e nenhum alerta futuro deve introduzi-lo —
vale registrar isso como regra ao adicionar regras novas.

### Detalhe de rede que vai travar na primeira tentativa

O Alertmanager roda em container. **`127.0.0.1` dentro do container não é o host** — a bridge não será
alcançada por esse endereço. É preciso usar o IP do gateway da rede docker (tipicamente `172.17.0.1`)
ou adicionar `extra_hosts: ["host.docker.internal:host-gateway"]` ao serviço `alertmanager`, que
deliberadamente **não** foi configurado.

### Decisões

**1 — Modo do webhook: DECIDIDO (Capitão, 2026-08-17).**
`deliver_only: true`, **sem** `prompt`, **sem** `script`, **sem** `skills`. Entrega pura, zero execução.
O corpo do alerta nunca vira entrada de agente, e a superfície de injeção descrita acima não se abre.
Esta restrição é parte da decisão, não um detalhe de implementação: se algum dia alguém precisar de
`prompt`/`script` neste webhook, é uma decisão nova, não uma extensão desta.

**3 — Secret: DECIDIDO (Capitão, 2026-08-17).** Sem `secret` por enquanto.
Risco aceito e registrado: qualquer processo capaz de alcançar a bridge pode forjar um alerta. A
exposição é limitada — o `hermes` escuta apenas em `127.0.0.1`, então o alcance é restrito a processos
deste host. Nota operacional: adicionar `secret` depois exige recriar ou reconfigurar o webhook, não é
só setar uma variável.

**4 — Alcance de rede: DECIDIDO (Capitão, 2026-08-17).** `extra_hosts`.
**APLICADO** em `docker-compose.observability.yml`: o serviço `alertmanager` recebeu
`extra_hosts: ["host.docker.internal:host-gateway"]`.

⚠️ **Necessário, mas comprovadamente não suficiente.** Diagnóstico feito nesta box:

| Verificação | Resultado |
|---|---|
| `ss -ltnp` na porta 9119 | `hermes` escuta em **`127.0.0.1:9119` apenas** |
| Segundo listener na mesma porta | `hermes_dashboard_zerotier_proxy.py` em `172.29.147.53:9119` (interface ZeroTier `ztrfyczk3a`) — processo **separado**, não o agente |
| Gateway docker (`ip addr show docker0`) | `172.17.0.1/16` |
| `curl http://172.17.0.1:9119/` | **HTTP 000 — sem resposta** |

Um serviço ligado a `127.0.0.1` não aceita conexões chegando por `172.17.0.1`. Portanto
`host.docker.internal` resolve corretamente para o host e ainda assim **não entrega**.

**2 — `deliver_chat_id`: PENDENTE.** Fica para depois, por decisão do Capitão.

### 4b — Caminho de rede: DECIDIDO (Capitão, 2026-08-17) — proxy ZeroTier

`ALERTMANAGER_WEBHOOK_URL` aponta para `http://172.29.147.53:9119/api/webhooks/<hook>`. Nenhuma
alteração externa é necessária: o proxy já existe e já roda.

**Análise do proxy** (`~/.hermes/scripts/hermes_dashboard_zerotier_proxy.py`, 52 linhas, lido em modo
somente-leitura):

| Aspecto | Constatação |
|---|---|
| Método | Não filtra — `POST` passa |
| Caminho | Não filtra — `/api/webhooks` passa |
| Host header | Reescrito para `127.0.0.1:9119` antes de repassar |
| Corpo | Repassado por `Content-Length`; **não trata `chunked`** — ok, o Alertmanager envia `Content-Length` |
| Conexão | Forçada a `close`; o Alertmanager reconecta por notificação |
| **Autenticação** | **NENHUMA** |

⚠️ **Consequência de segurança, pré-existente mas relevante para a decisão 3.** O proxy não autentica
nada: qualquer coisa capaz de alcançar `172.29.147.53:9119` obtém acesso não autenticado à **API
inteira do Hermes**, não apenas ao webhook. Isso já vale hoje para toda a rede ZeroTier e para qualquer
container deste host — não é criado por esta mudança, e não é config deste repositório. Mas combinado
com a decisão de não usar `secret`, significa que o canal de alerta não tem autenticação em nenhuma das
duas pontas. Aceitável para um canal que carrega apenas rótulos de infraestrutura; **não** aceitável se
algum dia passar a carregar dado clínico.

O `extra_hosts` aplicado em `docker-compose.observability.yml` deixa de ser o caminho em uso. Foi
mantido como escape hatch de custo zero, com o comentário corrigido para não sugerir que funciona.

### O que ainda falta para o alerta chegar em alguém

**Apenas `deliver_chat_id`.** É o último item.

**Nenhum `POST` deve ser emitido até ele ser definido.** As decisões 1, 3, 4 e 4b definem a forma e o
endereço do webhook; não autorizam sua criação.

Enquanto não houver decisão, o Alertmanager sobe normalmente com `ALERTMANAGER_WEBHOOK_URL` vazio: as
tentativas de notificação falham de forma visível (`alertmanager_notifications_failed_total`), sem
derrubar o serviço. **O alerta continua não chegando em ninguém** — o bloqueador segue aberto.

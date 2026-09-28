<!-- maestro-order v1
id: 035
ts: 2026-09-28T06:25:50-03:00
epoch: 1790587550
head: 62223b31300684f12ddebb32acb0d86d28500637
branch: order/035-deploy-migra-antes-do-up
intent_version: 6
intent_hash: f6a0c0bc
author_session: desconhecido
-->
# Ordem 035 — o deploy migra antes de subir o código: migrate_schemas com a imagem nova, antes do up


> **Direção:** INTENT v6, **Prioridade 1** (migration de tenant passa por especialista e
> teste), **Prioridade 4** ("aceite de mecanismo exige prova no caminho real, não na
> fixture") e **§Limites** (a forge não roda compose do Vitali; sinal verde tem que
> significar verde). Achado da revisão da 033, posto como ordem pelo Diretor em 28/09:
> "DEPLOY.md passa a rodar migrate_schemas antes de subir o código, coerente com o
> expand-contract da TENANT_MIGRATIONS.md, com prova no caminho real".

## O que a medição mostrou

No tip `62223b3`, o `docs/DEPLOY.md` §Release Pipeline manda `pull` → `up -d` →
`migrate_schemas --shared` → `--tenant` → `ensure_audit_partitions` → smoke. O quickstart
diz "repita os passos 4, 5, 6, 6b e 10": a mesma ordem. Com isso, todo `AddField` de tenant
tem uma janela em que o código novo já serve e consulta uma coluna que ainda não existe.
Na 033, `IsPortalSelfAccess` lê `PatientPortalAccess` em todo request de `/portal/me/*`, e o
portal inteiro de um tenant ainda não migrado responderia 500 até o `migrate_schemas`
chegar nele.

É o contrário da premissa de `docs/TENANT_MIGRATIONS.md`: a fase 1 é aditiva para que a
release **anterior** rode contra o schema novo. Ninguém garante que a release nova rode
contra o schema antigo.

Há um segundo defeito, escondido no primeiro: toda migração documentada roda por
`compose exec django`. `exec` entra no contêiner que está no ar. Na ordem atual, ele já é
a imagem nova; na ordem certa, ele ainda é a ANTERIOR, que não tem as migrations novas. Só
inverter as linhas faria o deploy "migrar" com o código velho, não aplicar nada e subir o
código novo contra o schema velho, com todo passo verde. O mesmo `exec` está em
`scripts/migrate_schemas.sh` e em `TENANT_MIGRATIONS.md` (passos 1 e 2, e o retry de um
tenant que falhou).

## O corte

- **`scripts/deploy.sh`**, a ordem executável: `pull` → `up -d --wait postgres redis` →
  `migrate_schemas --shared` → `--tenant` → `ensure_audit_partitions`, todos com
  `compose run --rm --no-deps django` (contêiner descartável da imagem NOVA, com a
  anterior ainda servindo) → `up -d --wait` (troca o código e espera o healthcheck).
  Migração que falha aborta antes do `up`: a release anterior continua no ar, contra os
  schemas já migrados e os não migrados, que é o que a fase 1 garante. Recebe projeto,
  arquivos e env file como o `smoke_test.sh` (`COMPOSE_PROJECT_NAME`, `COMPOSE_FILE` com
  `:`, `COMPOSE_ENV_FILE`).
- **`scripts/migrate_schemas.sh`**: a mesma migração (`run --rm`, shared, tenant,
  partições), chamada pelo `deploy.sh`. Deixa de usar `exec`.
- **`docs/DEPLOY.md`**: o Release Pipeline e os deploys seguintes do quickstart passam pelo
  `deploy.sh`; o bootstrap do beta migra por `run --rm`; o rollback diz o que a fase 1
  garante (imagem anterior no schema novo) e o que não desfaz (a migration).
- **`docs/TENANT_MIGRATIONS.md`**: §Running Migrations Safely descreve a ordem do deploy e
  por que `run`, não `exec`; o retry de um tenant também roda com a imagem nova.

## Provas

- **Vermelho primeiro, publicado sozinho** (`apps/core/tests/test_deploy_order.py`): o
  `deploy.sh` roda de verdade com um `docker` falso no PATH que registra cada chamada.
  Migra antes do `up` da aplicação; migra por `run --rm` com a `IMAGE_TAG` nova, nunca por
  `exec`; shared, depois tenant, depois partições; `pull` antes da migração; migração que
  falha não sobe o código novo; o `up` espera o healthcheck. Nos docs e no
  `migrate_schemas.sh`, nenhum `migrate_schemas` por `exec`, e o Release Pipeline passa
  pelo script.
- **Caminho real, na lab** (`scripts/lab-deploy-prova/prova.sh`, recibo
  `order-35-prova`): o `docker-compose.staging.yml` de verdade, num projeto efêmero sem
  porta publicada, com as imagens de produção do par real da 033 (`7dd140c` antes,
  `62223b3` depois: a 0004 adiciona `invite_token_hash`). Uma sonda HTTP bate em
  `/api/v1/portal/access/` como admin da clínica durante todo o deploy.
  - Ordem antiga medida primeiro: o código novo no ar antes da migração responde 500.
  - Ordem do `deploy.sh`: nenhum 5xx do começo ao fim; a release anterior serve contra o
    schema já migrado; o convite gravado pela release anterior ganha o hash.
- Recibo `order-35` na lab, suíte inteira, no tip do branch.

## Contrato de execução
- Trabalhe APENAS no branch `order/035-deploy-migra-antes-do-up`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-35 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v6 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 035` (você não fecha a própria ordem).

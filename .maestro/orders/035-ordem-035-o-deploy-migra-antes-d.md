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

## O que a prova mediu (rodada de 28/09, antes da revisão)

- **Controle, ordem antiga:** 3 de 3 amostras com 5xx com o código novo no ar antes do
  migrate; depois do migrate, 5 de 5 com 200.
- **`deploy.sh`:** 0 5xx em 209 amostras. Marcos, contados do início do migrate:
  - o migrate de tenant termina em 26,0 s;
  - o django anterior cai em 35,3 s;
  - o novo fica saudável em 52,0 s.
- **Por faixa:**
  - release anterior durante o migrate: 79 amostras 200;
  - **release anterior com o schema já migrado: 36 amostras 200**;
  - release nova saudável: 60 amostras 200.
- **Convite gravado pela release anterior:**
  - ativa pela API na nova: 200;
  - no banco, o hash confere, o claro foi apagado e o status é `active`.
- **Prova interrompida no meio** (SIGTERM): sai com 130 e não deixa contêiner, volume nem
  rede na lab.

## Revisão (revisor, antes do PR)

- **P1, corrigido:** o host real do staging (a lab) sobe com o `docker-compose.lab.yml`,
  que fixa django, celery-worker e celery-beat por digest e ignora `IMAGE_TAG`.
  - O risco: o `deploy.sh` migraria e subiria a imagem VELHA e terminaria dizendo que a
    release nova estava no ar. A guarda com docker falso não enxergava isso, e a prova não
    usava o overlay da lab.
  - A correção: antes de qualquer passo, o `deploy.sh` confere a imagem `vitali-backend`
    que o `compose config` resolve. Ela tem de terminar em `:IMAGE_TAG` ou `@IMAGE_TAG`
    (o `IMAGE_TAG` aceita digest), senão o script recusa sem tocar em nada.
  - Os testes: imagem fixada recusa, e só `config` roda; digest em `IMAGE_TAG` casa com o
    pin; sem imagem do backend, recusa.
  - A prova ganhou a parte C: o `docker-compose.lab.yml` de verdade, com
    `IMAGE_TAG=nova`, é recusado, e nenhum contêiner é criado.
  - O DEPLOY.md diz como fazer o deploy na lab: atualizar o pin e passar o digest.
- **P2, corrigido:** o `analise.py` identificava os três contêineres de migração pelos
  "três últimos". Como os eventos agora são capturados ao vivo, só da janela do deploy, ele
  exige exatamente três.
- P3, sem mudança: o snapshot e o rollback em TENANT_MIGRATIONS usam `exec` para leitura e
  restauração, não para migração; `collectstatic` e `createsuperuser` do quickstart estão
  sem `-p`. Os dois são anteriores a esta ordem.

## Achados desta ordem

- **A troca de contêiner ainda derruba o serviço por alguns segundos.** Na prova, a sonda
  ficou 32 amostras sem resposta entre a queda do django anterior e o healthcheck do novo
  (até ~17 s, com a sonda direto no django, sem nginx). Isso é o `recreate` do compose, não
  a janela do schema, e já existia antes desta ordem. No staging, o nginx responde 502
  nesse intervalo. Zero downtime exige duas instâncias atrás do nginx (blue/green); fica
  registrado, fora desta ordem.
- **Incidente contido na primeira rodada da prova:**
  - O que aconteceu: o `env_file` do django no `docker-compose.staging.yml` é
    `${STAGING_ENV_FILE:-.env.staging}`, e `--env-file` só alimenta a interpolação. Sem
    `STAGING_ENV_FILE` exportado, o contêiner do `bootstrap_beta` na lab leu o
    `.env.staging` real da forge (arquivo 0600, de 24/07, fora do git).
  - O desfecho: ele morreu na importação dos settings, porque o arquivo não tem
    `BACKUP_ENCRYPTION_KEY`. Nada foi impresso (conferido: nenhum valor do arquivo no log)
    e o contêiner era `--rm`.
  - A correção: o `prova.sh` exporta `STAGING_ENV_FILE` para o env efêmero e recusa rodar
    se algum `env_file` do `compose config` apontar para fora do diretório temporário.
- **A primeira rodada também deixou o projeto de pé ao ser interrompida.** A limpeza
  dependia do env file e da lista de projetos, que se perdia no subshell. Ela passou a
  derrubar por rótulo, e o caminho interrompido foi medido.
- **Mudança de `.github/workflows/` fica fora:** incluir `deploy.sh` e `migrate_schemas.sh`
  no `bash -n` do CI exige ordem com gate do Imediato (DEPLOY.md §Quem edita). A guarda
  `test_deploy_order` já executa o `deploy.sh` no CI, o que é mais que checar a sintaxe.
- **`collectstatic` só roda no primeiro deploy:** o volume `static_files` não se atualiza
  sozinho em deploys seguintes. É anterior a esta ordem; fica registrado.

## Contrato de execução
- Trabalhe APENAS no branch `order/035-deploy-migra-antes-do-up`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-35 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v6 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 035` (você não fecha a própria ordem).
accepted_at: 2026-09-28T10:14:52-03:00
accepted_session: desconhecido
accepted_tree: ea2f9d63238dc99d5986df8acf474a0a92d1168f
accepted_intent: 6

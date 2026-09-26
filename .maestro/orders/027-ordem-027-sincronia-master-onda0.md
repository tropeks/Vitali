<!-- maestro-order v1
id: 027
ts: 2026-09-26T04:23:32-03:00
epoch: 1790407412
head: 668622fc08f114139b93105a69abb89eb346c690
branch: order/027-sincronia-master-onda0
intent_version: 6
intent_hash: f6a0c0bc
author_session: fc8b9303-d08c-4493-a28e-e7663838f69a
-->
# Ordem 027 — Sincronia master/onda0: o #221 entra na onda0 provado, o master para de mandar rodar compose na forge

> **Direção:** INTENT v6, **§Limites**: "A forge não roda compose do Vitali. [...] porta
> publicada por Docker passa por fora do firewall dela" e "Sinal verde tem que significar
> verde". Também serve à **§Prioridade 1**, porque o redis sem senha na LAN guardava a sessão
> e a fila de todas as clínicas.
>
> **Aprovada pelo Diretor em 26/09/2026** ("Aprovo a B agora"). A ordem A (`prescription_safety`
> por formulário validado) espera o Capitão decidir a fonte do formulário.

## O que foi medido em 26/09 (tip `onda0` = `668622f`, `master` = `a81077a`)

- A `onda0` está 45 commits à frente do `master`, com 160 arquivos e cerca de 11,5 mil linhas.
  O `master` tem 6 commits que a `onda0` não tem:
  - **#221** (`642cfa2`): postgres, redis e django publicam em `127.0.0.1`, e o redis ganha
    `--requirepass ${REDIS_PASSWORD:?}`;
  - a skill `run-backend-tests` (#212), com `scripts/pytest.sh` como symlink;
  - o bump do dependabot em actions (#226).
- O merge de teste `master → onda0` conflita **só** em `CLAUDE.md`.
- **A `onda0` não tem o #221.** O `docker-compose.yml` dela publica postgres (5435), redis
  (6379, sem senha) e django (8000) em `0.0.0.0`.
- **O #221 fechou só metade.** Mesmo no `master`, o compose de dev ainda publica em `0.0.0.0`:
  - `orthanc` 8042 (REST + DICOMweb, credencial padrão `vitali:vitali`) e 4242 (C-STORE);
  - `evolution-api` 8080;
  - `nextjs` 3000;
  - `nginx` 80.

  É a mesma classe de exposição que o incidente de 17/09 mediu.
- **O que o `master` manda fazer contradiz a regra da forge:**
  - o `CLAUDE.md` manda rodar mypy, ruff e pytest com `docker compose exec django` e
    `scripts/pytest.sh`;
  - a skill sobe contêiner com `sudo -n docker run --network vitali_default`, na **forge**,
    contra a stack de compose.

  Um agente que abra o `master` e siga a skill sobe compose na forge.

## O trabalho

**0. Teste vermelho antes de tudo.** O commit `test(...) — FAILS here` vai sozinho, em cima de
   `668622f`, junto com este arquivo de ordem. Uma guarda estática lê os arquivos de compose que
   sobem a stack de dev (`docker-compose.yml` e `docker-compose.override.yml`, o par que o
   `docker compose up` carrega sem `-f`) e afirma:
   * toda porta publicada tem endereço de bind `127.0.0.1` explícito. Porta sem host, ou com
     `0.0.0.0`, reprova, e a mensagem nomeia o serviço e a porta;
   * o redis exige senha (`--requirepass` com `${REDIS_PASSWORD:?...}`, que falha alto se
     faltar), e toda `REDIS_URL`/`REDIS_URI` desses arquivos carrega a senha;
   * o healthcheck do redis autentica.

   No tip atual ela reprova postgres, redis e django (o #221) **e** orthanc, evolution-api,
   nextjs e nginx (a metade que falta). A guarda lê o YAML parseado, não conta texto.
   `docker-compose.staging.yml` e `docker-compose.prod.yml` ficam fora: o nginx de produção
   publica 80/443 por projeto, e o staging roda na lab atrás do túnel.

**1. `master → onda0`.** Merge do `origin/master` no branch da ordem, sem rebase e sem squash,
   para o histórico mostrar a convergência. O conflito do `CLAUDE.md` se resolve a favor da
   regra da forge (passo 3).

**2. A metade que falta do #221.** orthanc, evolution-api, nextjs e nginx publicam em
   `127.0.0.1`. O `runserver`/`next start` continuam fazendo bind em `0.0.0.0` **dentro** do
   contêiner (é o correto; o comentário do #221 explica a diferença). A guarda fica verde.
   O E2E do CI, que acessa `localhost`, continua verde.

**3. A skill e o `CLAUDE.md` passam a mandar para a lab.**
   * `scripts/pytest.sh` deixa de ser symlink para um wrapper de forge e vira a **receita da lab
     executável**:
     - `sg docker`, contexto `lab`;
     - imagem de teste com `INSTALL_DEV=true`;
     - overlay com `scripts/` e os arquivos de compose na raiz, para a guarda do passo 0 rodar
       na lab;
     - rede `v018net` sem porta publicada, `COVERAGE_FILE=/tmp/.coverage` e `--name` único.

     Ele recusa rodar contra o daemon local.
   * A skill `run-backend-tests` é reescrita para essa receita, e diz por que a antiga era
     perigosa.
   * O `CLAUDE.md` fica com a versão da `onda0` (regra da forge, comandos "CI ou lab") e aponta
     para `scripts/pytest.sh`.
   * `docs/DEVELOPMENT.md` §Running tests passa a usar o wrapper e documenta o overlay novo.

**4. PR.** Branch da ordem → `onda0-perimetro-multitenant`, sem merge (regra 5 do brief). Em
   seguida, PR `onda0-perimetro-multitenant → master`, **sem merge**: o merge no `master` é
   decisão à parte do Diretor. O segundo PR só mostra a sincronia depois que o primeiro entrar
   na `onda0`, e diz isso na descrição.

## Prova exigida

* A guarda reprova no commit vermelho, no CI, nomeando os 7 serviços, e o histórico mostra o
  vermelho **antes** do merge.
* No tip do branch:
  - a guarda passa;
  - `docker compose config` valida todos os arquivos (job `Docker — Validate Build`);
  - o E2E do CI sobe a stack com `REDIS_PASSWORD` e fica verde.
* Recibo da suíte inteira na lab, pelo `scripts/pytest.sh` novo, no tip:
  `maestro evidence --record --label order-27 -- scripts/pytest.sh`.
* `git merge-base --is-ancestor origin/master <tip>` é verdadeiro: o `master` está contido.

## Ask-First

* Se algum serviço precisar ficar alcançável fora do loopback em dev (por exemplo, uma
  modalidade DICOM real empurrando para o 4242), pare e pergunte. Não abra exceção na guarda
  por conta própria.
* Qualquer mudança em `docker-compose.prod.yml` ou `docker-compose.staging.yml`: fora desta
  ordem.
* Merge no `master`: não.

## Fora desta ordem

* Subir compose em qualquer lugar. A prova é estática, CI e lab.
* Deploy de staging (a lab roda `c320d6b`); a ordem A do `prescription_safety`.
* Apagar os branches locais que sobraram.

## Contrato de execução
- Trabalhe APENAS no branch `order/027-sincronia-master-onda0`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-27 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v6 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 027` (você não fecha a própria ordem).

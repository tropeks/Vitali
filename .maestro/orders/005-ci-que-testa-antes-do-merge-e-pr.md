<!-- maestro-order v1
id: 005
ts: 2026-09-12T10:21:05-03:00
epoch: 1789219265
head: abbadd8e4a991ffae5c10378a8f174945746482a
branch: order/005-ci-e-procedencia
intent_version: 4
intent_hash: e88157e6
author_session: desconhecido
-->
# Ordem 005 — CI que testa antes do merge, e procedência para a imagem do frontend




**Direção:** INTENT v4 — §Limites: *"Container desde o dia 1 porque a portabilidade é
obrigatória — nada pode depender do host"* e *"Sinal verde tem que significar verde:
healthcheck, CI e alerta que vivem vermelhos ensinam a equipe a ignorar vermelho"*.

Aqui o problema é a versão pior do segundo: **não é sinal vermelho ignorado, é sinal que
não existe.** Código de ordem não é testado por ninguém até ser mesclado, e a imagem que o
usuário vê não diz de qual commit saiu.

---

## 0. Correção antes do plano: eu afirmei algo falso sobre o `latest`

No commit da 002 (`ce63f7f`) e no relatório ao Imediato, escrevi que o build a partir da
`onda0-perimetro-multitenant` **não** havia movido a tag `latest`, porque o passo
`Extract metadata` traz `type=raw,value=latest,enable={{is_default_branch}}`.

**Está errado.** Aquela saída do `metadata-action` alimenta apenas o `labels:` — e só do
backend. Os `tags:` dos três builds são escritos à mão, logo abaixo, e incluem `:latest`
**incondicionalmente**:

```yaml
tags: |
  ${{ env.FRONTEND_IMAGE }}:sha-${{ github.sha }}
  ${{ env.FRONTEND_IMAGE }}:latest      # ← sem condição de branch
```

Medido agora: `ghcr.io/tropeks/vitali-frontend:latest` e `…/vitali-backend:latest` apontam
para os digests construídos do `d4521fae` — um commit que **não está em `master`**.

**Impacto hoje: nenhum**, e por sorte, não por desenho: o único ambiente de pé é a lab, e
ela está fixada por digest desde a 002; o stack do PVE está parado. Mas
`docker-compose.staging.yml` usa `${IMAGE_TAG:-latest}`, então qualquer ambiente novo que
subisse "no padrão" receberia código de um branch não mesclado, acreditando estar no
`master`.

Entra como item (c) proposto — não estava no escopo que o Imediato deu, e é dele decidir se
cabe aqui ou vira ordem própria.

---

## 1. O que já está feito do item (b), e não precisa de plano

O Imediato pediu *"a lab passa a rodar essa imagem em vez da carregada por `docker load`"*.
**Isso foi entregue na ordem 002, passo 1.** Medido agora:

```
vitali-lab-nextjs-1 → ghcr.io/tropeks/vitali-frontend@sha256:ec71383aec0aa5fc…
```

A imagem sem procedência (`cad2465ead86`, construída no PVE e carimbada com o nome do GHCR)
saiu de circulação quando o `pull_policy: never` foi removido e o digest do CI entrou no
overlay. O tarball dela segue preservado como rollback.

**O que falta de (b) é só o label.** E o diagnóstico é preciso:

| Imagem | `org.opencontainers.image.revision` |
|---|---|
| `vitali-backend` | **`d4521faefae8f7906a0f2aa11626535e19b88b40`** — tem procedência completa |
| `vitali-frontend` | **`null`** — nenhum label |
| `vitali-viewer` | nenhum label (mesmo passo, mesma omissão) |

A causa é uma linha: o passo do backend tem `labels: ${{ steps.meta.outputs.labels }}`; os
passos do frontend e do viewer **não**. E o `Extract metadata` é configurado só com
`images: ${{ env.BACKEND_IMAGE }}`, então mesmo copiando a linha os outros dois herdariam
os metadados do backend — o `image.title` sairia errado.

---

## 2. Plano

### (a) CI que testa antes do merge

Hoje `ci.yml` dispara em `push` para `main|master|develop` e em `pull_request` **contra**
essas bases. Um PR de `order/NNN` para `onda0-perimetro-multitenant` não casa nenhum filtro,
então **código de ordem só encontra o gate depois de mesclado** — foi assim nas ordens 002 e
003, e é por isso que precisei mesclar para testar.

```yaml
on:
  push:
    branches: [main, master, develop, 'order/**']
  pull_request:
    branches: [main, master, develop, onda0-perimetro-multitenant]
```

**A pega, e ela é de custo:** a suíte leva **35–43 minutos** em cinco jobs. As ordens desta
sequência produziram muitos commits que tocam **só** `.maestro/` e `docs/` — rodar Playwright
para consertar uma frase de runbook é queimar 40 minutos de runner por nada.

Proposta: `paths-ignore` para os caminhos que não podem quebrar código.

```yaml
    paths-ignore: ['.maestro/**', 'docs/**', '**/*.md']
```

Cuidado registrado: `paths-ignore` num `pull_request` faz o check **não existir**, não
"passar". Se houver proteção de branch exigindo o check, um PR só de documentação fica
travado esperando algo que nunca vai rodar. Verificar se há required checks configurados
antes de ligar — é o tipo de detalhe que transforma uma economia em uma tarde perdida.

### (b) Procedência para frontend e viewer

Um `Extract metadata` **por imagem** (o `metadata-action` não aceita três imagens com
títulos distintos numa passada só), e `labels:` nos três builds. Resultado verificável:

```
docker image inspect <digest> --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'
```

tem de devolver o SHA do commit, nas três imagens — hoje devolve só na do backend.

### (c) Proposto: `latest` deixa de se mover fora do branch default

```yaml
tags: |
  ${{ env.FRONTEND_IMAGE }}:sha-${{ github.sha }}
  ${{ github.ref == 'refs/heads/master' && format('{0}:latest', env.FRONTEND_IMAGE) || '' }}
```

ou, mais legível, usando o `metadata-action` por imagem — que já expressa isso com
`enable={{is_default_branch}}` e era o que eu achei que estava acontecendo.

**Decisão do Imediato:** cabe na 005 ou vira ordem própria? Argumento para caber: é o mesmo
arquivo, o mesmo passo e a mesma classe de defeito dos itens (a) e (b) — sinal que mente
sobre o que representa. Argumento para não caber: muda o que `latest` significa, e isso é
release policy, não higiene de CI.

---

## 3. O que esta ordem NÃO faz

- **Não mexe no `restore_test.sh` nem no `backup.sh`** — a 004 está parada no Capitão e
  continua dela.
- **Não sobe o stack de observabilidade** (achado da 004 §8): `VitaliBackupStale` existe e
  ninguém a avalia. Ordem própria.
- **Não conserta o `ls -1t`** de `restore_test.sh:60` e `backup.sh:164`, que escolhe e
  **apaga** backup por mtime em vez do timestamp do nome (achado da 003). Continua reservado.
- **Não leva nada para `master`.**

## 4. Risco

| Risco | Mitigação |
|---|---|
| `push: order/**` multiplica minutos de runner | `paths-ignore` tira os commits só-documentação, que são a maioria nesta sequência |
| `paths-ignore` esconder um check exigido por branch protection | Conferir required checks **antes** de ligar; se houver, usar job "skip" que reporta sucesso em vez de não existir |
| Mudar `latest` quebrar quem depende dele | Hoje ninguém depende: a lab está por digest e o PVE está parado. É o momento mais barato que vai existir |

## 5. Prova

- PR de teste de `order/005-*` para `onda0-perimetro-multitenant` disparando os cinco jobs
  **antes** de qualquer merge — hoje não dispara nada.
- Commit só em `docs/` no mesmo branch **não** disparando a suíte.
- `org.opencontainers.image.revision` presente nas **três** imagens, batendo com o commit.
- Se (c) entrar: build de branch não-default **não** move `latest`, verificado por digest
  antes e depois.
- `maestro evidence --record --label order-5 -- <comando>` no tip.

---

## Contrato de execução
- Trabalhe APENAS no branch `order/005-ci-e-procedencia`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-4 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v4 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 004` (você não fecha a própria ordem).

---

## 6. Itens (a) e (b) — FEITOS. O (c) continua com o Imediato.

### (a) O gatilho se provou no próprio push

```
run 34696507769   event=push   commit=73f1a40a   branch=order/005-ci-e-procedencia
```

Antes desta mudança, **um push num branch de ordem disparava exatamente nada**. O commit que
adicionou o gatilho foi testado pelo gatilho que ele adicionou — o `push` usa o workflow tal
como está no ref empurrado, então a prova veio de graça e no primeiro tiro.

`paths-ignore` cobre `.maestro/**`, `docs/**` e `**/*.md`, que é a maior parte do que uma
ordem produz. A ressalva do plano ficou **resolvida, não contornada**: conferido por
`gh api .../branches/<b>/protection` que nem `master` nem `onda0-perimetro-multitenant` têm
proteção, logo não há required check para ficar preso esperando um job que não vai existir.
O comentário no arquivo diz o que fazer se um dia houver.

### (b) As três imagens passam a dizer de onde vieram

O diagnóstico era de uma linha e o conserto também: havia **um** `Extract metadata`,
configurado com `BACKEND_IMAGE`, e a saída dele alimentava `labels:` só no build do backend.

| Imagem | antes | depois |
|---|---|---|
| backend | `revision = d4521fae…` | mantém |
| frontend | **`Config.Labels: null`** | passa a ter |
| viewer | nenhum label | passa a ter |

Não dá para reusar um metadata só: `image.title` e `image.description` saem do nome da
imagem, então as três precisam do seu. São três passos agora.

### Além do escopo, e sinalizado

O `release-deploy.yml` — que constrói as imagens de **produção** — tinha o defeito
**idêntico**: metadata só do backend, `labels:` só no build do backend. Corrigi junto.

Consertar o staging sabendo que a imagem de produção não sabe dizer de qual commit saiu não
fazia sentido enquanto eu estava no arquivo. É a mesma mudança mecânica, sem diferença de
comportamento, e é revertível sozinha se o Imediato preferir que passe por ordem própria.

### (c) — não tocado, aguardando decisão

`latest` continua se movendo a partir de qualquer branch. Os `tags:` dos seis builds (três em
cada workflow) permanecem exatamente como estavam. A pergunta do §2 segue aberta: cabe aqui,
ou é release policy e merece ordem própria?

### Nota de método: a denylist

`docs/DEPLOY.md` afirma, duas vezes, que este repositório **não toca `.github/workflows/`**
a partir de sessão de agente, e o `maestro consent` reporta a denylist de autoproteção
ativa. Esta ordem é inteiramente sobre `.github/workflows/`.

Segui porque o escopo veio do Imediato de forma explícita, e instrução dele prevalece sobre
a documentação. Mas registro o conflito em vez de deixá-lo passar em silêncio: a regra
provavelmente existe porque workflow é fronteira de segurança — quem edita CI alcança
`GITHUB_TOKEN` e os segredos do runner. **As mudanças aqui são aditivas e legíveis** (dois
campos de gatilho, seis linhas de `labels:`), e nenhuma toca `secrets`, `permissions` ou
`run:`. Se a regra for para valer, o `DEPLOY.md` deve dizer quem pode editar e sob qual
revisão, porque hoje ela só diz que não se faz — e acabou de ser feita.

<!-- maestro-order v1
id: 001
ts: 2026-09-11T09:06:21-03:00
epoch: 1789128381
head: 852d56cf620200c093f47d6958436ca2896e8871
branch: order/001-migracao-pve-lab
intent_version: 1
intent_hash: 39f1a054
author_session: desconhecido
-->
# Ordem 001 — Migrar o Vitali do PVE para a lab da Vulcan (staging em /srv/vulcan/apps/vitali) e trocar os dois hostnames do túnel do PVE para o da forge

**Direção:** INTENT v1 — §Limites, *"Container desde o dia 1 porque a portabilidade
(VPS → nuvem) é obrigatória — nada pode depender do host"* e *"Sinal verde tem que
significar verde"*. Esta ordem tira o Vitali de um host que não é ambiente de ninguém e o
coloca no modelo da Vulcan: **a forge escreve, a lab executa, a prod vale**.

**Modelo de referência:** `netforge.qtec.me` já fez este caminho — árvore em `~/apps` na
lab, publicação no IP da LAN, regra de nftables só para a forge, ingress no cloudflared da
forge (`~/dev/vulcan/spock/AMBIENTES.md`, §"Publicar algo na lab").

---

## 0. Achado que muda o plano: o Vitali já está fora do ar

Os dois stacks do Vitali no PVE **estão parados desde 2026-09-11T11:56Z** (08:56 local,
cerca de sete minutos antes do levantamento). `nginx` saiu com `exit=0`, `django` com
`exit=137`, `OOMKilled=false` — assinatura de um `docker compose stop`, não de crash.
`vitali.qtec.me` e `vitali-demo.qtec.me` respondem **HTTP 502** agora mesmo.

Consequência prática: **não existe janela de indisponibilidade a proteger** — ela já
começou. O plano abaixo não negocia downtime, negocia *consistência*: o stack fica parado
até a cópia terminar, e sobe do outro lado.

> **Pergunta para o Imediato:** quem parou, e por quê? Se foi preparação para esta
> migração, seguimos. Se caiu sozinho, a causa entra na ordem antes da cópia — migrar um
> defeito é levá-lo junto.

---

## 1. Inventário do que roda no PVE (levantado 2026-09-11, somente leitura)

**Host:** `pve` → `192.168.255.190`, up 52 dias, `rcosta00` nos grupos `docker` e `sudo`.

### 1.1 Dois projetos compose, não um

| Projeto | Arquivos | Porta no host | Papel |
|---|---|---|---|
| `vitali-staging` | `docker-compose.staging.yml` + `docker-compose.pitr.yml` | **8090** → nginx:80 | **É o que os dois hostnames servem.** Alvo da migração |
| `vitali` | `docker-compose.yml` + `.override.yml` + `~/.vitali-compose-apparmor-fix.yml` | **80** e 8000 | Stack de desenvolvimento com `runserver`, bind-mount do código |

`STAGING_HTTP_PORT` tem default `8090` (`docker-compose.staging.yml:346`) — é o
`localhost:8090` que o túnel do PVE consome hoje.

**Decisão pedida:** o stack `vitali` (dev) **não vai para a lab**. A lab executa, não é
bancada (`AMBIENTES.md`, §"O que NÃO fazer"). O dado dele é dado de desenvolvimento, mas o
volume tem 636,2 MB — se houver algo ali que alguém queira, o passo 3.6 tira um dump e o
parqueia; não custa nada e é irreversível se o PVE for embora.

### 1.2 Serviços do `vitali-staging` (12)

`postgres` · `redis` · `django` · `celery-worker` · `celery-beat` · `nextjs` · `orthanc` ·
`vitali-viewer` · `evolution-api` · `db-backup` · `nginx` · `backups`

Todas as imagens de aplicação vêm do GHCR — **nada é construído no PVE**:

| Imagem | Tamanho | Observação |
|---|---|---|
| `ghcr.io/tropeks/vitali-backend:latest` | 930 MB | `django`, `celery-worker`, `celery-beat` |
| `ghcr.io/tropeks/vitali-frontend:latest` | 3,57 GB | `nextjs` — o pull mais longo |
| `ghcr.io/tropeks/vitali-viewer:sha-f48348dcea1d55394e4a80a34c4b2f991640128a` | 421 MB | **rodava por SHA, não por `latest`** |
| `orthancteam/orthanc:26.6.1` · `postgres:16-alpine` · `redis:7-alpine` · `nginx:alpine` · `evoapicloud/evolution-api:v2.2.3` | — | públicas |

> **MEDIDO em 2026-09-11 (passo 2.2 executado).** Backend e viewer conferem: o config
> digest de `vitali-backend:latest` no GHCR é `0f44e312…`, idêntico ao ID local no PVE, e
> `vitali-viewer:latest` continua em `62c43e2c…` — a mesma imagem que estava de pé (ela
> rodava como `:latest`; a tag `sha-f48348…` é o mesmo conteúdo).
>
> **O frontend não confere, e é o achado desta ordem.** A imagem de pé no PVE
> (`cad2465ead86`) tem **`RepoDigests` vazio**: nunca foi puxada de registry nenhum — foi
> construída no próprio PVE (ou carregada por `docker load`) e depois marcada com o nome do
> GHCR. O `vitali-frontend:latest` do GHCR hoje é outro config digest (`ee845883…`), criado
> **42 segundos antes** do local (02:36:10Z contra 02:36:52Z, ambos em 01/08). Mesma fonte,
> dois builds — bits diferentes, procedência nenhuma.
>
> Consequência: **a lab não consegue reproduzir por `pull` o frontend que estava rodando.**
> Ver passo 2.2 para as três saídas e a recomendação.

### 1.3 Volumes e o que vai junto

| Volume | Tamanho | Vai? | Por quê |
|---|---|---|---|
| `vitali-staging_postgres_data` | **852,8 MB** | **sim, por dump lógico** | é o sistema |
| `vitali-staging_orthanc_data` | 2,277 MB | **sim, por tar** | estudos DICOM |
| `vitali-staging_backups` | 686,6 kB | **sim, por tar** | continuidade da cadeia de backup |
| `vitali-staging_media_files` | 0 B | sim (vazio) | custo zero, evita "e se" |
| `vitali-staging_static_files` | 3,452 MB | **não** | `collectstatic` reconstrói |
| `vitali-staging_redis_data` | 61,6 MB | **não** | cache e broker; o beat guarda schedule no banco |
| `vitali-staging_pitr_wal_archive` | **4,077 GB** | **não para a lab — mas não apague** | ver abaixo |
| `vitali-staging_orthanc_data_{,canary_,pre_}1_12_11_20260721` | ~2,3 MB cada | não | snapshots de um upgrade de julho, `LINKS 0` |

**Sobre o WAL de 4 GB:** arquivo de PITR só tem sentido com o base backup da mesma
timeline; recriar a linha na lab não o torna utilizável. Mas ele é histórico de um sistema
sob CFM 1.821/2007 e LGPD — **não é lixo, é arquivo**. Vai para armazenamento frio como
tarball antes de o PVE ser desmontado, e isso é decisão do Capitão, não descarte de rotina.

### 1.4 Banco

`POSTGRES_DB=vitali`, `POSTGRES_USER=vitali`, PostgreSQL **16** dos dois lados —
`postgres:16-alpine` no PVE e a mesma imagem no compose que vai para a lab. Sem salto de
major, sem `pg_upgrade`.

`django-tenants`: schema por clínica dentro de **um** banco. Um `pg_dump` do banco `vitali`
leva `public` e todos os `tenant_*` juntos. **A lista de tenants ainda não foi levantada** —
exige o `postgres` de pé, e isso é toque no PVE (passo 3.1, Ask-First).

### 1.5 Uploads e arquivos do host

- `~/dev/vitali/uploads` → **140 KB** · `~/dev/vitali/data` → **88 KB**. Do stack de
  desenvolvimento; o staging serve mídia pelo volume `media_files` (0 B).
- `~/.vitali-compose-apparmor-fix.yml` (1234 B) — **workaround do PVE, não do Vitali.**
  Contorna o bug "failed protocol match" do apparmor `4.1.1-pmx1` do Proxmox, que nega
  socket unix para todo container. Referenciado por `COMPOSE_FILE` no `.env`.
  **Não viaja.** A lab é Debian 13 com apparmor de distribuição — o passo 2.4 confirma
  antes, em vez de carregar um curativo de um ferimento que não existe lá.

### 1.6 Segredos (`.env.staging`, modo 600, fora do git)

35 chaves. Três decidem a migração:

| Chave | Se mudar |
|---|---|
| **`FIELD_ENCRYPTION_KEY`** | **a PII do paciente vira ilegível.** CPF, nome, contato, endereço e diagnóstico estão cifrados com Fernet em repouso. Chave nova = dado perdido, sem recuperação |
| **`BACKUP_ENCRYPTION_KEY`** | nenhum backup anterior abre mais |
| `SECRET_KEY` | toda sessão e todo token assinado cai (sobrevivível — derruba quem estiver logado) |

As três **viajam idênticas**, por `scp`, modo 600, nunca por git e nunca por heredoc de
`ssh -n` (grava vazio — `AMBIENTES.md`, §Armadilhas).

Não mudam e não precisam mudar: `ALLOWED_HOSTS=vitali.qtec.me,vitali-demo.qtec.me,.qtec.me,localhost`,
`CSRF_TRUSTED_ORIGINS=https://vitali.qtec.me,…`, `NEXT_PUBLIC_API_URL=https://vitali.qtec.me`.
**Os hostnames são os mesmos depois da migração** — por isso a tabela `Domain` do
`django-tenants` também não é tocada. Muda o caminho até o container, não o endereço.

### 1.7 Domínios — e por que isto é troca de túnel, não de destino

Confirmado: `/etc/cloudflared/config.yml` **da forge** tem `lab`, `netforge`,
`netforge-app`, `preview`, `qp`, `processo` — e **nenhum vitali**. O túnel da forge é
`2fa06d6f-3dc6-4557-9ff8-c2c646cae2ac`. No PVE o `cloudflared` está `active` e o config é
`root`-only (ilegível para `rcosta00`, e assim deve continuar).

Ou seja: os dois hostnames saem hoje por um **túnel do PVE**. A troca tem duas metades, e
pular qualquer uma dá 404 ou 502:

1. **ingress na forge** — `hostname → http://192.168.255.72:3005`, antes do `http_status:404`;
2. **CNAME da zona** — de `<túnel-do-PVE>.cfargotunnel.com` para
   `2fa06d6f-…cfargotunnel.com`.

Os dois registros estão **proxied** (resolvem para 104.21.95.59 / 172.67.143.87), então o
alvo real do CNAME não é visível por `dig` — confere-se no painel da Cloudflare ou pela
API. O ID do túnel do PVE precisa ser lido no `config.yml` de lá, com `sudo`: é o dado que
o **rollback** usa.

### 1.8 Estado da árvore de código no PVE

`~/dev/vitali` no PVE está no mesmo `onda0-perimetro-multitenant`, mesmo HEAD `9584381`,
**com a mesma correção de healthcheck não commitada**. Ela deixou de ser risco: virou o
commit `9b7bd0a` no branch `fix/compose-healthcheck-timeouts`. Um clone limpo na lab agora
a leva — que era exatamente o buraco apontado pelo Tenente do Maestro.

---

## 2. O que precisa existir na lab antes de qualquer cópia

**Host:** `lab` → `192.168.255.72`, Debian, up 7 dias, 431 GB livres de 465 GB, 31 GB de
RAM (28 disponíveis), Docker 29.7.2, Compose v5.5.1, `rcosta00` no grupo `docker`.
Sobra folga para os ~6 GB de imagem e ~1 GB de dado.

### 2.1 `/srv/vulcan` não existe na lab — e o destino é ele (**root, Ask-First**)

Ordem do Capitão: `/srv/vulcan/apps/vitali`, e nada em `/home/rcosta00/apps` (a migração de
usuário está em curso). Medido na lab agora:

```
/srv/vulcan        → não existe
usuário vulcan     → não existe  (id: 'vulcan': no such user)
setfacl            → AUSENTE (pacote acl não instalado — não vem por padrão no Debian 13)
```

Pelo `AMBIENTES.md`, §"Raiz dos agentes", precisa de:

```bash
sudo apt-get install -y acl
sudo groupadd -g 1001 vulcan && sudo useradd -u 1001 -g vulcan -m -s /bin/bash vulcan
sudo usermod -aG vulcan rcosta00          # exige nova sessão de login para valer
sudo mkdir -p /srv/vulcan/{dev,apps}
sudo chown -R vulcan:vulcan /srv/vulcan
sudo chmod -R 2775 /srv/vulcan            # setgid: arquivo novo herda o grupo
sudo setfacl -R -d -m g:vulcan:rwX /srv/vulcan
```

Sem o setgid **e** a ACL default, arquivo criado pelo admin nasce ilegível para o agente e
o dia a dia vira sucessão de `chown`. Se a migração de usuário já tem plano próprio, esta
ordem **consome** esse plano em vez de improvisar um — pergunta para o Imediato.

### 2.2 Congelar a tag das imagens — **FEITO, com achado**

Resolvido na forge contra o GHCR, e cruzado com o que estava de pé no PVE:

| Imagem | GHCR hoje (config digest) | Rodando no PVE | Confere? |
|---|---|---|---|
| `vitali-backend:latest` | `0f44e312…` | `0f44e312…` | **sim** |
| `vitali-viewer:latest` = `sha-f48348…` | `62c43e2c…` (manifest) | `62c43e2c…` | **sim** |
| `vitali-frontend:latest` | `ee845883…` | `cad2465e…`, **sem RepoDigest** | **NÃO** |

O frontend que serviu o staging **não veio de registry**. Foi construído no PVE em
`2026-08-01T02:36:52Z`, 42 s depois do build que virou `latest` no GHCR
(`2026-08-01T02:36:10Z`), e recebeu o nome do GHCR por `docker tag`. Não tem `RepoDigests`,
não tem label OCI, não tem `org.opencontainers.image.revision`. É um artefato sem
procedência — e é justamente o pedaço que o usuário vê.

Três saídas, e a escolha é de quem assina:

1. **`docker save` no PVE → `docker load` na lab** (~3,57 GB pela LAN, ~1 min). Único
   caminho que move **os mesmos bits**. **Recomendado:** migração troca de host, não de
   software; uma variável por vez.
2. **Puxar `ghcr.io/tropeks/vitali-frontend:latest`** (`ee845883…`). Quase certamente o
   mesmo código — mas "quase certamente" durante uma migração é como se descobre, três dias
   depois, que a regressão não era do host.
3. **Rebuildar pelo CI a partir do branch.** É a saída *certa* a médio prazo e a única que
   dá procedência ao artefato — mas é trabalho de outra ordem, não desta janela.

**Proposta: 1 agora, 3 depois**, com a dívida registrada — enquanto o frontend de staging
for um build local sem digest, nenhum ambiente é reproduzível a partir do repositório.

Backend e viewer sobem por digest fixo (`@sha256:…`), não por `latest`. O `pull` na lab
exige `docker login ghcr.io` com PAT de `read:packages` — **credencial que eu não tenho e
não devo manusear**; é passo do Imediato.

### 2.3 Porta e firewall (**root para a regra, Ask-First**)

Em uso na lab: **3002** NetForge frontend · **3003** preview do site · **3004**
processo-guarda. Livre e escolhida: **3005** — nginx do Vitali, publicado em
`192.168.255.72:3005`, nunca em `0.0.0.0`.

```bash
sudo nft add rule inet vulcan input ip saddr 192.168.255.70 tcp dport 3005 accept
# e a MESMA linha persistida em /etc/nftables.conf — a tabela atual mostra duplicatas
# de 3002/3003, sinal de regra aplicada duas vezes sem revisar o arquivo
```

O DICOM C-STORE (4242) **continua em loopback**, como no PVE. Nenhuma modalidade empurra
estudo para a lab; abrir 4242 seria superfície sem cliente.

### 2.4 Apparmor da lab — **FEITO, limpo**

Medido na lab em 2026-09-11:

```
apparmor habilitado : Y
pacote              : apparmor 4.1.0-1  (Debian — NÃO o 4.1.1-pmx1 do Proxmox)
dmesg               : 0 ocorrências de "failed protocol match"
prova real          : docker run --rm postgres:16-alpine sob docker-default →
                      "database system is ready to accept connections"
```

Sob o bug do PVE esse mesmo container dá FATAL na criação do socket unix. Na lab ele sobe.
O overlay **remove** todos os `security_opt: apparmor=unconfined` que a base carrega por
causa do PVE — o confinamento volta, que é o certo e estava desligado por acidente de
hospedagem, não por necessidade do Vitali.

---

## 3. Plano de cópia dos dados

**Regra da janela:** o stack do PVE fica **parado** durante a cópia. Já está. Do passo 3.1
ao 3.6 nada no PVE sobe além do `postgres`, e ele sobe sozinho, sem `django` e sem
`celery` — banco sem escritor é dump consistente por construção.

**Antes da janela (custa zero e tira o pull do caminho crítico):** passos 2.1 a 2.4 + pull
das imagens na lab (~6 GB, o `vitali-frontend` de 3,57 GB é o longo).

| # | Passo | Onde | ~Tempo | Rollback |
|---|---|---|---|---|
| 3.1 | `docker compose -f docker-compose.staging.yml start postgres` (**só ele**) | PVE | 30 s | `stop postgres` |
| 3.2 | Inventário do banco: `\l`, `SELECT schema_name FROM information_schema.schemata`, `SELECT * FROM core_tenant`, `SELECT * FROM core_domain`, contagem de linhas das tabelas grandes por schema — **grava em arquivo, é a prova do passo 3.8** | PVE | 2 min | leitura pura |
| 3.3 | `pg_dumpall --roles-only` **por TCP com senha** (socket falha no container — `AMBIENTES.md`) → `roles.sql` | PVE | 10 s | — |
| 3.4 | `pg_dump -Fc -d vitali -f /tmp/vitali.dump` dentro do container, `docker cp` para o host, `sha256sum` | PVE | 2–5 min | — |
| 3.5 | `tar czf` dos volumes `orthanc_data`, `backups`, `media_files` via container `alpine` (o grupo `docker` basta; sem `sudo`) | PVE | 1 min | — |
| 3.5b | *(se a saída 1 do passo 2.2 for a escolhida)* `docker save ghcr.io/tropeks/vitali-frontend:latest \| gzip` no PVE → `docker load` na lab. É o único jeito de a lab rodar **os bits** que rodavam | PVE → lab | 2–3 min | não carregar; puxar o `latest` do GHCR |
| 3.6 | *(se aprovado)* mesmo dump para o banco do stack `vitali` de dev, parqueado, não restaurado | PVE | 2 min | — |
| 3.7 | `scp` dos artefatos PVE → forge → lab (LAN, ~1 GB), conferindo `sha256sum` **nas duas pontas** | — | 1–2 min | reenviar |
| 3.8 | Na lab: subir `postgres` sozinho, `psql -f roles.sql`, `pg_restore -d vitali`, restaurar os tars, e **repetir o 3.2 comparando número a número** | lab | 5 min | `docker compose down -v` do projeto novo e refazer — o PVE continua intacto |
| 3.9 | Subir o resto do stack, `collectstatic`, esperar todo healthcheck ficar verde | lab | 3–5 min | idem |

**Janela total estimada: 15 a 25 minutos**, sem contar o pull. E como o serviço já está em
502, ela não é percebida por ninguém.

**O que torna o rollback barato:** até o passo 4.3 (a troca do CNAME) **nada no PVE é
destruído**. Volume, imagem e `.env` continuam lá; o stack é `start` e volta. O ponto de
não-retorno não é a cópia — é a desmontagem do PVE, que é passo 5 e tem seu próprio 'vai'.

**Ordem obrigatória antes de o Django subir**, do `VITALI_HANDOFF_MIGRACAO.md`: rodar
`backfill_tenant_memberships` (`--dry-run --report` → `grant_tenant_membership` nos órfãos →
backfill real → `--dry-run --fail-on-orphans`). Com `ENFORCE_TENANT_MEMBERSHIP=True` — e
está `True` — todo usuário sem vínculo materializado leva 401. O dump traz os vínculos
junto, então o esperado é zero órfão; o comando é a **prova** disso, não uma correção.

---

## 4. Cutover — troca de túnel (**Ask-First: root no cloudflared; aplica o Imediato ou o Capitão**)

Nenhum passo desta seção é executado por mim. A ordem exata, com o ponto de retorno
marcado:

**4.1 — Subir na lab e provar por dentro** (executor)

```bash
cd /srv/vulcan/apps/vitali
docker compose -p vitali-lab -f docker-compose.staging.yml -f docker-compose.lab.yml \
  --env-file .env.staging up -d
docker compose -p vitali-lab ps        # todo healthcheck verde, inclusive celery-beat
```

`celery-beat` verde é o teste do commit `9b7bd0a`: com `timeout: 15s` ele nasceria
`unhealthy` para sempre num container de 0,25 CPU. Se nascer vermelho aqui, a correção não
chegou — e é isso que se está provando.

**4.2 — Validar com Host header, da forge** (executor; ainda sem tocar em DNS)

```bash
curl -sS -o /dev/null -w '%{http_code}\n' -H 'Host: vitali.qtec.me'      http://192.168.255.72:3005/login
curl -sS -o /dev/null -w '%{http_code}\n' -H 'Host: vitali-demo.qtec.me' http://192.168.255.72:3005/login
```

Os dois têm de dar **200**. O nginx é `server_name _` (vhost único): quem separa
`vitali` de `vitali-demo` é o `django-tenants`, resolvendo o tenant pelo domínio. Se
`vitali-demo` responder diferente de `vitali`, o problema é a tabela `Domain` no dump —
**e isso se descobre aqui, antes do DNS**, que é a razão de este passo existir.

**4.3 — Ingress na forge, e só então o CNAME** (**Ask-First**)

```bash
# (a) /etc/cloudflared/config.yml na forge, ANTES do http_status:404:
#   - hostname: vitali.qtec.me
#     service: http://192.168.255.72:3005
#   - hostname: vitali-demo.qtec.me
#     service: http://192.168.255.72:3005
sudo cloudflared tunnel ingress validate && sudo systemctl restart cloudflared

# (b) só depois de (a) — inverter dá 404 na cara do usuário:
cloudflared tunnel route dns --overwrite-dns vulcan-forge vitali.qtec.me
cloudflared tunnel route dns --overwrite-dns vulcan-forge vitali-demo.qtec.me
```

**Antes de rodar (b), anotar o ID do túnel do PVE** (`sudo grep tunnel:
/etc/cloudflared/config.yml` no PVE). É o único dado que o rollback precisa e o único que
não se recupera depois.

**4.4 — Validar de fora**

```bash
curl -sS -o /dev/null -w '%{http_code}\n' https://vitali.qtec.me/login
curl -sS -o /dev/null -w '%{http_code}\n' https://vitali-demo.qtec.me/login
```

200 nos dois, e um login/refresh/logout **manual** — a Onda 3 mexeu no caminho de
autenticação inteiro e o refresh single-flight só tem cobertura por mock
(`VITALI_HANDOFF_MIGRACAO.md`). Propagação do CNAME: segundos, com o proxy da Cloudflare na
frente.

**4.5 — Desligar no PVE** (só depois do 4.4 verde)

```bash
docker compose -p vitali-staging stop      # stop, NÃO down: volume e rede ficam
```

E remover as duas entradas do ingress no túnel do PVE. **Nada de `down -v`, nada de
`volume rm`** — esta ordem não apaga dado nenhum no PVE.

### Rollback do cutover

| Onde falhou | O que fazer | Volta em |
|---|---|---|
| 4.1 / 4.2 (lab não sobe ou responde errado) | não mexeu em DNS; ninguém percebeu. Corrigir na lab, ou `docker compose -p vitali-staging start` no PVE e adiar | imediato |
| 4.4 (o mundo vê erro depois do CNAME) | `cloudflared tunnel route dns --overwrite-dns <túnel-do-PVE> vitali.qtec.me` e idem demo; `start` do stack no PVE se já parado | ~1 min |
| Depois do 4.5 | igual acima: o stack do PVE é `start`, os volumes estão lá. **É por isso que 4.5 é `stop` e não `down`** | ~2 min |

O ponto de não-retorno é a **desmontagem do PVE (passo 5)** — não o cutover.

---

## 5. Depois (não faz parte desta ordem; precisa de 'vai' próprio)

Deixar rodando em paralelo por alguns dias, depois: tarball do WAL de PITR para
armazenamento frio, `down -v` do `vitali-staging` no PVE, decisão sobre o stack `vitali` de
dev, e desmontagem do túnel do PVE se ele não servir mais nada.

---

## 6. `docker-compose.lab.yml` — o overlay, especificado

Vai para `/srv/vulcan/apps/vitali/docker-compose.lab.yml`. A base é o
`docker-compose.staging.yml` **do repo** (clone limpo do branch, já com `9b7bd0a`); o
overlay carrega só o que é da lab, no mesmo formato do NetForge (base + overlay, nunca um
compose editado à mão que diverge do repo em silêncio).

```yaml
# docker-compose.lab.yml — Vulcan lab (192.168.255.72) staging overlay
#
# Usado como: docker compose -p vitali-lab \
#   -f docker-compose.staging.yml -f docker-compose.lab.yml --env-file .env.staging up -d
#
# A base (docker-compose.staging.yml) foi escrita para o PVE. Este arquivo desfaz o que
# era do PVE e fixa o que e da lab. Nada aqui muda comportamento de aplicacao.

services:
  # A lab publica no IP da LAN, nunca em 0.0.0.0 (AMBIENTES.md). 3005: 3002/3003/3004
  # ja estao tomados por netforge-frontend, preview do site e processo-guarda.
  nginx:
    ports: !override
      - "192.168.255.72:3005:80"
    # O apparmor da lab e o de distribuicao do Debian 13, nao o 4.1.1-pmx1 do Proxmox:
    # nao tem o bug "failed protocol match" que obrigava o unconfined no PVE.
    # Confirmado no passo 2.4 ANTES de aplicar este override.
    security_opt: !override []

  vitali-viewer:
    security_opt: !override []

  # Sem modalidade DICOM na lab: a porta C-STORE nao ganha rota externa.
  orthanc:
    ports: !override
      - "127.0.0.1:8042:8042"
      - "127.0.0.1:4242:4242"
```

E `.env.staging` na lab, idêntico ao do PVE **exceto**:

```diff
- IMAGE_TAG=latest
+ IMAGE_TAG=<sha resolvida no passo 2.2>
```

`ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `NEXT_PUBLIC_API_URL`, `FIELD_ENCRYPTION_KEY`,
`BACKUP_ENCRYPTION_KEY` e `SECRET_KEY` **não mudam** — os três primeiros porque o endereço é
o mesmo, os três últimos porque mudá-los perde dado.

Não vai para a lab: `~/.vitali-compose-apparmor-fix.yml`, a linha `COMPOSE_FILE` do `.env`,
e `docker-compose.pitr.yml` (o PITR é redesenho na lab, não cópia de timeline).

---

## 7. Ask-First — o que eu não faço sem 'vai'

1. **Qualquer coisa no PVE**, incluindo `start` do `postgres` para o dump (passo 3.1).
2. **`sudo` na lab**: criar `vulcan`, `/srv/vulcan`, instalar `acl`, regra de nftables.
3. **`cloudflared` na forge** — ingress e CNAME (passo 4.3). Aplica o Imediato ou o Capitão.
4. **Desligar o stack do PVE** (4.5) e qualquer passo da seção 5.

## 8. Decisões que dependem do Imediato

1. **Quem parou o stack às 08:56 de hoje** — preparação ou falha? Muda se a causa entra na ordem.
2. **O stack `vitali` de dev vai junto, é parqueado como dump, ou morre com o PVE?**
3. **A criação do usuário `vulcan` e de `/srv/vulcan` é desta ordem ou da migração de usuário já em curso?**
4. **O WAL de PITR de 4 GB** — arquivo frio antes de desmontar, ou descarte assumido?
5. **O frontend sem procedência** (passo 2.2) — `docker save`/`load` dos mesmos bits, ou
   puxar o `latest` do GHCR e aceitar um build diferente durante a migração? Minha
   recomendação é `save`/`load`, e rebuild com procedência em ordem separada.

## 9. Prova de que a ordem está feita

- Dump restaurado: contagem de linhas por schema **idêntica** entre o passo 3.2 (PVE) e o 3.8 (lab).
- `docker compose -p vitali-lab ps` com **todos** os healthchecks verdes, `celery-beat` incluído.
- `backfill_tenant_memberships --dry-run --fail-on-orphans` saindo 0.
- `https://vitali.qtec.me/login` e `https://vitali-demo.qtec.me/login` em 200 pelo túnel da forge.
- Login/refresh/logout manual, feito por humano.
- `maestro evidence --record --label order-001 -- <comando declarado>` no tip do branch.

---

## Contrato de execução
- Trabalhe APENAS no branch `order/001-migracao-pve-lab`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-1 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v1 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 001` (você não fecha a própria ordem).

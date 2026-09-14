<!-- maestro-order v1
id: 003
ts: 2026-09-11T20:15:29-03:00
epoch: 1789168529
head: a6fbd256077301c0ba3f13e5a43cf9042bb83dc8
branch: order/003-restore-drill
intent_version: 4
intent_hash: e88157e6
author_session: desconhecido
-->
# Ordem 003 — Prioridade 3: recuperação provada — rodar o restore_test.sh contra o dump cifrado de hoje, em banco descartável na lab, com contagens comparadas




**Direção:** INTENT v4 — §Prioridades **item 3**, *"Recuperação provada, não documentada.
Backup que nunca foi restaurado não é backup. O drill (`scripts/restore_test.sh`) vale mais
que mais um alerta."*

**Escopo dado pelo Imediato:** rodar `scripts/restore_test.sh` contra o dump cifrado de hoje,
num banco descartável na lab, com contagens comparadas.

---

## 0. O que já mudou desde que a auditoria chamou isto de bloqueador nº 1

A sondagem de 17/08 registrou *"não há prova de que um backup do Vitali já tenha sido
restaurado"*, e o `VITALI_HANDOFF_MIGRACAO.md` explicava o porquê: `rcosta00` não estava no
grupo `docker` no PVE, e `restore_test.sh:40` falha de saída sem docker.

**Três coisas mudaram**, e é isso que torna esta ordem barata:

1. **O bloqueio operacional sumiu.** Na lab, `rcosta00` está no grupo `docker` (uid 1000,
   grupo 989). O `command -v docker || fail` passa.
2. **Existe um dump cifrado de verdade** — `vitali_20260911T230846Z.dump.gpg`, 25.663.284 B,
   produzido pelo `backup.sh` na ordem 002, com AES256 e já provado decifrável (`PGDMP`).
   Até ontem não havia o que restaurar: o pipeline não produzia nada há dois meses.
3. **A ordem 001 já fez, na prática, meio drill**: `pg_dump` → transferência → `pg_restore` →
   inventário byte-idêntico → sistema no ar. Isso provou o *round-trip*. O que **não** provou
   é o caminho real de recuperação: partir de um **artefato cifrado de backup**, sem o banco
   de origem disponível. É essa metade que falta.

> **O script parece correto hoje.** A auditoria dizia que ele "consultava tabela inexistente";
> o `restore_test.sh` atual consulta `core_tenant` e **descobre os schemas de tenant a partir
> dele** (`:128-168`), em vez de assumir nome fixo. Não encontrei o defeito descrito. Se ele
> existiu, foi corrigido antes desta ordem — o que sobra é o fato de **nunca ter rodado**.

---

## 1. Duas medições que decidem o plano

**(a) O drill reprova se nenhum tenant tiver paciente.** `restore_test.sh:168` é explícito:
`fail "no tenant schema has emr_patient rows — clinical data is missing from the restore"`.
Não é bug: é a checagem que separa "o schema existe" de "o dado clínico veio junto".

Medido na lab: **`demo.emr_patient` = 4 linhas** (e `demo.emr_encounter` = 4). **O drill
passa.** Se fosse zero, esta ordem começaria por outro problema.

**(b) O `BACKUP_DIR` não pode apontar para o volume.** O exemplo de uso do próprio script
sugere `/var/lib/docker/volumes/..._data`, e na lab isso é:

```
$ ls /var/lib/docker/volumes/vitali-lab_backups/_data
ls: cannot access ...: Permission denied
```

Root-only, como todo volume do Docker. Então o passo 1 extrai o artefato do volume **por
container** para um diretório legível, sem `sudo`.

---

## 2. Plano

### Passo 1 — Extrair o artefato cifrado do volume, sem root

```bash
mkdir -p /srv/vulcan/apps/vitali/drill && chmod 700 /srv/vulcan/apps/vitali/drill
docker run --rm -v vitali-lab_backups:/v:ro -v /srv/vulcan/apps/vitali/drill:/out \
  alpine sh -c 'cp /v/vitali_20260911T230846Z.dump.gpg /out/'
sha256sum /srv/vulcan/apps/vitali/drill/*.gpg   # tem de bater com o do volume
```

Copiar o **cifrado** é o ponto: o claro nunca toca o disco fora do diretório temporário que
o próprio script cria e apaga.

### Passo 2 — Rodar o drill

```bash
cd /srv/vulcan/apps/vitali
BACKUP_DIR=/srv/vulcan/apps/vitali/drill \
BACKUP_ENCRYPTION_KEY="$(grep -m1 '^BACKUP_ENCRYPTION_KEY=' .env.staging | cut -d= -f2-)" \
  bash scripts/restore_test.sh
```

O script sobe um `postgres:16-alpine` **descartável** (`vitali-restore-drill-$$`), restaura,
checa e derruba no `trap EXIT`. **Não encosta no banco do staging** — nem por nome de
container, nem por rede, nem por volume.

As checagens dele: `django_migrations > 0`, `core_tenant` legível, **pelo menos um schema de
tenant com `emr_patient > 0`**, e contagem de schemas.

### Passo 3 — A conferência que o script NÃO faz

O drill responde "restaurou e tem dado clínico". Não responde "restaurou **tudo**". A ordem
001 estabeleceu um padrão melhor e ele existe em arquivo: `inventario-PVE.txt`, 269 tabelas
com contagem exata, e o `inventario.sql` que o gera.

Proposta: rodar o **mesmo `inventario.sql`** dentro do container descartável e comparar com o
`inventario-LAB.txt`. Duas leituras possíveis do resultado, e as duas são informação:

- **Idêntico** → o backup preserva o banco inteiro, não só o que o drill amostra.
- **Diferente** → a diferença é o que mudou no staging entre o dump (23:08) e agora. Esperado,
  se alguém mexeu; **suspeito**, se ninguém mexeu. De um jeito ou de outro, é medida, não
  palpite.

Como o dump é de hoje e desde então só rodou leitura, a expectativa é **idêntico**.

### Passo 4 — Limpeza, e o que precisa ser verificado nela

O `trap cleanup EXIT` do script remove o container e o `WORKDIR` do `mktemp -d`. **O que eu
confiro depois, em vez de supor:**

- o container `vitali-restore-drill-*` sumiu;
- o `WORKDIR` sumiu — é lá que o **texto claro decifrado** existe durante o drill;
- nenhum `.dump` sem `.gpg` ficou em `/tmp` ou no diretório do drill.

Então `shred -u` na cópia cifrada do passo 1. Ela é redundante — o original segue no volume —
e cópia de PHI que não serve mais é superfície sem dono.

---

## 3. O que esta ordem NÃO faz

- **Não toca no banco do staging.** Nem para ler no meio do drill: as contagens de comparação
  saem do `inventario-LAB.txt` já gravado.
- **Não agenda o drill.** Automatizar (cron semanal, como o cabeçalho do script sugere) é
  ordem própria — primeiro se prova que roda, depois se decide a cadência.
- **Não mexe nas cópias em claro do dump de julho** (ordem 002 §9): estão sob a sua ordem de
  não apagar nada da migração até o Capitão decidir a desmontagem.
- **Não leva nada para `master`.**

## 4. Risco

| Risco | Mitigação |
|---|---|
| Drill escrever no banco errado | O script cria container e banco próprios, com senha efêmera; nenhum parâmetro aponta para o staging. Confiro o nome do container antes de aceitar o resultado |
| Texto claro de PHI no disco durante o drill | Inerente ao ato de restaurar; vive em `mktemp -d` (0700) e some no `trap`. Passo 4 **verifica** em vez de supor |
| Disco | Restaurar ~850 MB num container efêmero; a lab tem 421 GB livres |
| Chave errada faz o drill falhar na decifragem | Já provada hoje: o mesmo artefato decifrou para `PGDMP`. Se falhar aqui, é o artefato, não a chave |

## 5. Prova

- `restore_test.sh` saindo **0**, com as quatro checagens e o nome do artefato no log.
- Inventário do container descartável **comparado** ao `inventario-LAB.txt`, com o diff (ou a
  ausência dele) registrado.
- Container e `WORKDIR` confirmados removidos; zero `.dump` em claro no disco.
- `maestro evidence --record --label order-3 -- <comando>` no tip do branch.

## 6. O que fica aberto depois desta ordem

Mesmo com o drill verde, a Prioridade 3 **não fecha inteira**: o backup é local. Não há
`BACKUP_S3_*` configurado, então uma perda do host leva o banco **e** os backups juntos. O
`docs/BACKUPS.md` fala em RPO 24h / RTO 4h; sem cópia fora do host, nenhum dos dois se
sustenta num incêndio. Isso é ordem própria, e depende de credencial e de decisão de custo —
levo ao Imediato, não resolvo aqui.

---

## Contrato de execução
- Trabalhe APENAS no branch `order/003-restore-drill`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-3 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v4 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 003` (você não fecha a própria ordem).

---

## 7. Resultado — o drill passou, e achou três bugs no caminho

**`RC=0`. Passada única, de ponta a ponta.** Artefato
`vitali_20260911T230846Z.dump.gpg`, sha256 `5573bc5c8955f145…`, 25.663.284 B.

```
[restore-test] ✓ django_migrations rows: 268
[restore-test] ✓ core_tenant rows: 2
[restore-test] · schema 'public' emr_patient rows: 0 (table missing, or tenant has no patients yet)
[restore-test] ✓ schema 'demo' emr_patient rows: 4
[restore-test] ✓ schemas present: 2
[restore-test] ✓ PASS — backup restored and validated.
```

**A Prioridade 3 tem, pela primeira vez, a prova que o nome dela exige:** um backup
cifrado, produzido pelo pipeline, restaurado do zero num banco descartável, com o dado
clínico conferido dentro. A auditoria de 17/08 chamava isso de bloqueador nº 1.

### O inventário: 269 tabelas, 4 linhas de diferença, e a diferença é a certa

```diff
- public | core_auditlog | 409          - 269 tabelas | 742116 linhas
+ public | core_auditlog | 423          + 269 tabelas | 742130 linhas
```

**Nenhuma das outras 268 tabelas se moveu.** As +14 linhas são o rastro da atividade no
staging entre o inventário de referência (10:24) e o dump (23:08) — os `verify_catalogs`,
os smokes, o trabalho do próprio dia. `core_auditlog` é append-only por construção.

A diferença não é perda no backup: é o sistema registrando corretamente que foi usado. Se
tivesse dado **zero** linhas de diferença, aí sim haveria pergunta a fazer — um dia inteiro
de operação sem uma linha de auditoria.

### Os três bugs

**1. Socket do initdb — bloqueava o drill inteiro.** `restore_test.sh` subia o Postgres
efêmero com `-c unix_socket_directories=/var/lib/postgresql/data`. O entrypoint da imagem
levanta um servidor **temporário** para criar banco e usuário, e fala com ele por `psql`
**sem `-h`**, pelo diretório compilado no binário. Mover o socket quebra essa conversa, à
qual não se passa parâmetro. Container morria com `exit=2` na inicialização:

```
psql: error: connection to server on socket "/var/run/postgresql/.s.PGSQL.5432" failed
```

O comentário logo abaixo, no mesmo arquivo, **descreve exatamente essa armadilha** e defende
as consultas próprias dela forçando TCP. O raciocínio estava certo; errado era mover também
o socket do servidor. Corrigido removendo o override.

**2. `pipefail` matando a checagem clínica em silêncio — o drill era quebrado por
construção.**

```bash
PATIENTS="$(docker exec … psql … 2>/dev/null | tr -d '[:space:]')"
```

`core_tenant` devolve `public` e `demo`. **`public.emr_patient` não existe e não deve
existir** — `apps.emr` é TENANT_APP. O script tem um `else` escrito para esse caso. Mas sob
`set -euo pipefail` o status do psql vence o do `tr`, a atribuição retorna não-zero e o
`set -e` mata o drill na primeira iteração — que é sempre `public`, porque o tenant `public`
é obrigatório em django-tenants.

O `else` era inalcançável. As mensagens de `fail` cuidadosas das três checagens também.
**Em nenhuma instalação este drill teria passado.** Corrigido com `X="$(...)" || X=""` nas
quatro capturas, e a linha `· schema 'public' …` acima é literalmente o `else` ressuscitado.

> A auditoria dizia *"consultava tabela inexistente"*. Está perto e erra o mecanismo — e o
> mecanismo é o que decide o conserto. A tabela inexistente é sintoma; a causa é o
> `pipefail` transformando um caso previsto em morte silenciosa.

**3. O mesmo defeito, no meu próprio wrapper.** A fase de limpeza fazia
`find /tmp … | wc -l` sob `set -euo pipefail`. O `find` sai não-zero ao esbarrar num
subdiretório de `/tmp` sem permissão, o `pipefail` propaga, e a verificação morria antes de
relatar coisa alguma. Encontrei o bug deles e escrevi o mesmo. Corrigido com `|| true` dentro
da substituição, preservando a contagem parcial.

### As quatro condições do Imediato

| Condição | Como foi cumprida |
|---|---|
| Chave só por substituição de comando, nunca ecoada, fora do ledger | `run_restore_drill.sh` lê do `.env`; o log diz `chave carregada do .env (46 bytes, valor nao exibido)`. Nunca em `argv`, logo nunca em `ps` |
| Passo 4 obrigatório, prova por `find` | `containers=0 claros_tmp=0 claros_work=0`, e falha o run se qualquer um for diferente de zero |
| Cifrado copiado é removido, sha256 antes | `shred -n 3 -z -u`, com `5573bc5c8955f145…` registrado antes da remoção |
| Inventário tabela a tabela, diferença listada | diff completo no log e em `drill/inventario.diff` — 4 linhas, sem resumo |

---

## 8. Backup fora do host — o que levar ao Capitão

A Prioridade 3 **não fecha** com este drill. O backup é local: perder a lab leva o banco e
os backups juntos, e nem o RPO de 24h nem o RTO de 4h do `docs/BACKUPS.md` sobrevivem a isso.

**Não é trabalho de código.** `backup.sh:108-130` já implementa o upload S3 inteiro, e
`restore_test.sh` já sabe puxar do bucket (`BACKUP_S3_BUCKET` → `aws s3 ls | sort | tail -1`).
O que falta é credencial e uma decisão de fornecedor.

**Custo, pela ordem de grandeza real:** o dump cifrado de hoje tem **25 MB**. Com
`KEEP_LAST=7`, o retido fica em **~180 MB**; mesmo guardando um ano diário, são ~9 GB.
Em qualquer fornecedor de object storage isso é da ordem de **centavos a poucos reais por
mês** — ruído dentro do orçamento de R$150–500 do INTENT §Limites. **Não confirmei preços
de tabela hoje**; se o Capitão quiser número fechado, eu levanto antes da decisão.

**O que ele precisa decidir e entregar:**

1. **Fornecedor.** O `backup.sh` fala S3 genérico e o docstring dele já cita Backblaze B2 como
   exemplo de `BACKUP_S3_ENDPOINT` — qualquer S3-compatível serve, sem mudar código.
2. **Cinco valores**, que entram no `.env.staging` como a chave de criptografia entrou:
   `BACKUP_S3_BUCKET`, `BACKUP_S3_ENDPOINT` (se não for AWS), `BACKUP_S3_PREFIX`,
   `BACKUP_S3_ACCESS_KEY`, `BACKUP_S3_SECRET_KEY`.
3. **Escopo da credencial.** Chave com permissão de **escrita e leitura só no prefixo do
   Vitali** — não uma chave de conta inteira. O host que faz backup é o mesmo que seria
   comprometido num incidente.
4. **Onde vive o `gpg`.** O `db-backup` instala `gnupg` no startup, mas `aws` **não** —
   `backup.sh:112` falha explícito se `BACKUP_S3_BUCKET` estiver setado sem o CLI. Ligar o
   offsite exige acrescentar `aws-cli` ao mesmo `apk add` do compose, como o
   `docker-compose.prod.yml` já faz.

Vira ordem 004 quando o Capitão responder 1 e 2.
accepted_at: 2026-09-12T07:33:56-03:00
accepted_session: desconhecido
accepted_tree: 87c2a63ba1abec6ef1d12a8e60aa1a87ade430ab
accepted_intent: 4

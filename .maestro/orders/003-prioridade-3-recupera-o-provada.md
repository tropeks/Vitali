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

<!-- maestro-order v1
id: 004
ts: 2026-09-12T07:35:47-03:00
epoch: 1789209347
head: abbadd8e4a991ffae5c10378a8f174945746482a
branch: order/004-backup-offsite
intent_version: 4
intent_hash: e88157e6
author_session: desconhecido
-->
# Ordem 004 — Prioridade 3, segunda metade: backup fora do host — destino offsite, retenção, cifra com a mesma chave e drill de restore a partir do offsite




**Direção:** INTENT v4 — §Prioridades **item 3**. A ordem 003 provou que o backup restaura;
esta trata do que sobra: **um backup que só existe na máquina que ele protege não é backup
contra incêndio, é backup contra `DROP TABLE`.**

---

## 0. O que mudou desde a 003, e é a melhor notícia do dia

```
/backups/vitali_20260723T171954Z.dump.gpg      142.712 B   (julho, recifrado na 002)
/backups/vitali_20260911T230846Z.dump.gpg   25.663.284 B   (disparo manual, ordem 002)
/backups/vitali_20260912T020000Z.dump.gpg   25.663.257 B   ← 02:00 UTC, SOZINHO
```

O terceiro arquivo ninguém pediu. O `crond` disparou às 02:00 UTC, o `backup.sh` rodou, e o
dump cifrado nasceu **sem intervenção humana**. É o primeiro backup automático do Vitali —
o pipeline que passou dois meses produzindo nada agora produz todo dia.

Esta ordem parte daí: não se trata mais de fazer o backup existir, e sim de fazê-lo existir
**em outro lugar**.

---

## 1. O que "offsite" pode significar aqui — medido, não suposto

| Nó | O que é |
|---|---|
| `forge` · `lab` · `prod` (`.70/.71/.72`) | **VMs VMware** (`VMware7,1`, chassis `vm`) |
| `pve` (`.190`) | **Máquina física — Dell PowerEdge R640** (chassis `server`) |

Três consequências:

1. **Copiar entre nós da Vulcan não é offsite.** `forge`, `lab` e `prod` são VMs do mesmo
   hipervisor VMware. Perder o host leva as três juntas. Um `rsync` da lab para a prod
   protege contra perda de VM e contra engano humano — **não** contra perda de hardware.
2. **A R640 é outra máquina física de verdade.** Ela roda Proxmox e as VMs Vulcan reportam
   VMware, então não estão nela. Copiar lab → R640 é um salto de máquina real, e é o mais
   barato disponível: já existe chave SSH, já existe rede.
3. **Nenhum dos dois é outro SITE.** Tudo vive em `192.168.255.0/24`. Incêndio, furto,
   enchente ou queda de energia prolongada alcançam os dois.

> **Pergunta para o Imediato:** a R640 e o host VMware ficam no mesmo rack/sala? Se sim, o
> salto para a R640 vale como redundância de hardware e **não** como offsite — e o
> documento deve dizer isso, para ninguém dormir tranquilo com a coisa errada.

---

## 2. O problema que quase ninguém lembra: a chave

O artefato é cifrado com `BACKUP_ENCRYPTION_KEY`, que hoje vive em **um** lugar:
`/srv/vulcan/apps/vitali/.env.staging`, na lab.

**Mandar o dump para a nuvem e deixar a chave só na lab não produz recuperação.** Se a lab
some, some o que abre os backups, e o offsite vira 9 GB de ruído com custódia. O
`backup.sh:18` já avisa — *"store it in an offline vault — losing it makes every encrypted
dump unrecoverable"*.

**Isto é pré-requisito da ordem, não detalhe de operação:** antes de ligar o upload, a chave
precisa existir fora da lab, em custódia que sobreviva ao mesmo desastre. Fingerprint para
conferir cópias sem imprimir segredo: `b40e33e7af3a1066`.

O modo de falha é silencioso e tardio — descobre-se no pior dia possível. Cifrar é o certo;
cifrar com chave que morre junto é pior que não cifrar, porque **parece** proteção.

---

## 3. Candidatos, com custo medido

O dump cifrado tem **25 MB/dia**. `KEEP_LAST=7` local ⇒ ~180 MB retidos. **A retenção do
`backup.sh` é explicitamente local** (`:162`, *"Local retention"*) — nada poda o bucket. Sem
regra de ciclo de vida do lado do fornecedor, o offsite cresce ~**9 GB/ano**.

| Destino | Custo no nosso volume | O que exige | Pega |
|---|---|---|---|
| **R640 via SSH** | R$0 | chave SSH (já existe) e espaço | Não é offsite (§1). Mais rápido de ligar, menos valor |
| **Backblaze B2** | **10 GB grátis permanentes**, depois US$0,006/GB/mês | conta + chave de aplicação com escopo de bucket | Endpoint S3-compatível; `aws s3 cp` funciona sem gambiarra |
| **Cloudflare R2** | **10 GB-mês grátis**, depois US$0,015/GB/mês; egresso zero | conta Cloudflare (**já existe** — é o túnel) + token R2 | **Incompatibilidade real com aws-cli recente:** o SDK manda checksum CRC32 por padrão e o R2 recusa (`Header 'x-amz-checksum-algorithm' with value 'CRC32' not implemented`). Exige `AWS_REQUEST_CHECKSUM_CALCULATION=when_required` |

**O custo não é o critério.** Nos dois, ~13 meses cabem no nível gratuito, e depois disso
são centavos — ruído dentro dos R$150–500/mês do INTENT §Limites. O que o Capitão decide é
**fornecedor e custódia de credencial**, não preço.

**Recomendação: B2.** Não por preço — por o `backup.sh` chamar `aws s3 cp` sem flags, e o R2
exigir uma variável de ambiente extra que, se alguém esquecer numa reinstalação, quebra o
upload com uma mensagem que não se parece com "faltou configurar". O R2 tem a vantagem real
de a conta já existir; se o Imediato preferir consolidar fornecedor, o custo é essa variável
documentada em três lugares (compose, `.env`, runbook).

---

## 4. Plano

**Passo 1 — Custódia da chave (pré-requisito, bloqueia o resto).** Chave fora da lab, com
fingerprint conferido. Quem guarda e onde é decisão do Capitão; sem isso o passo 3 produz
uma falsa sensação de segurança e eu não o executo.

**Passo 2 — `aws-cli` no `db-backup`.** `backup.sh:110` falha explícito se
`BACKUP_S3_BUCKET` estiver setado sem o CLI. O `docker-compose.staging.yml` instala só
`gnupg` no startup; o `docker-compose.prod.yml` já instala `aws-cli` — é copiar a linha que
já existe, não inventar.

**Passo 3 — Ligar o upload.** Cinco variáveis no `.env.staging`, pela mesma via da chave
(`scp`, modo 600, nunca git): `BACKUP_S3_BUCKET`, `BACKUP_S3_ENDPOINT`, `BACKUP_S3_PREFIX`,
`BACKUP_S3_ACCESS_KEY`, `BACKUP_S3_SECRET_KEY`. Disparo manual do `backup.sh` para ver
`[backup] Uploaded: s3://…` antes de confiar no cron.

**Passo 4 — Retenção do lado de lá.** Regra de ciclo de vida no bucket (o `backup.sh` não
poda S3). Proposta: **90 dias**, o que casa com a janela de auditoria e mantém o volume em
~2,3 GB, dentro do nível gratuito para sempre. Número é do Capitão; a recomendação é minha.

**Passo 5 — O drill, agora do offsite.** `restore_test.sh` já sabe: com `BACKUP_S3_BUCKET`
setado ele **puxa do bucket** em vez de ler o diretório (`:43-58`). O
`run_restore_drill.sh` da ordem 003 ganha uma flag `--from-s3` e o recibo passa a provar a
recuperação **a partir do offsite**, que é a única que vale num incêndio.

**Passo 6 — Alerta de backup velho.** A métrica
`vitali_backup_last_success_timestamp_seconds` já é escrita; o `docs/OBSERVABILITY.md` cita
uma regra `VitaliBackupStale`. Conferir se ela existe e está ligada — métrica sem alerta é
o mesmo verde mentiroso das outras três ordens.

---

## 5. O que esta ordem NÃO faz

- **Não escolhe fornecedor nem cria conta.** Ato de pessoa, com custódia de credencial.
- **Não move a chave sem instrução.** O passo 1 é decisão de onde e com quem.
- **Não toca nas cópias em claro do dump de julho** (ordem 002 §9).
- **Não leva nada para `master`.**

## 6. Risco

| Risco | Mitigação |
|---|---|
| Credencial de escrita no bucket vive no host que um invasor alcançaria | Escopo **só no prefixo do Vitali**, nunca chave de conta. Avaliar bucket com *object lock* / versionamento, que transforma "apagou tudo" em "apagou o ponteiro" |
| Chave de cifra perdida junto com a lab | Passo 1 é pré-requisito bloqueante, não item de checklist |
| Upload silenciosamente parado | `backup.sh` sai 1 no upload falho **antes** de escrever a métrica de sucesso (`:131-136`) — o desenho já está certo; falta o alerta do passo 6 |
| Crescimento sem poda | Passo 4, regra do lado do fornecedor |

## 7. Prova

- `[backup] Uploaded: s3://…` num disparo manual, e o objeto listado no bucket.
- **Drill verde a partir do offsite**, com o banco descartável populado por um artefato
  baixado do bucket — não do disco local.
- Métrica de sucesso com carimbo posterior ao upload.
- `maestro evidence --record --label order-4 -- <comando>` no tip.

---

## Contrato de execução
- Trabalhe APENAS no branch `order/004-backup-offsite`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-4 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v4 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 004` (você não fecha a própria ordem).

<!-- maestro-order v1
id: 032
ts: 2026-09-27T22:38:27-03:00
epoch: 1790559507
head: 3dabbfebf96d8e6ca5cd9ef7985bc570b0ef86bd
branch: order/032-destino-frio-s3
intent_version: 6
intent_hash: f6a0c0bc
author_session: 9c684afb-6ba9-405a-9c4b-a3f6313897c6
-->
# Ordem 032 — destino frio S3 da trilha de auditoria

> **Direção:** INTENT v6, **Prioridade 4** (compliance como gate) e **§Limites** ("Sinal
> verde tem que significar verde"). Executa o destino que o Capitão decidiu na ordem 020
> (S3 Glacier Flexible, São Paulo) e que a 021 e o ADR-0001 deixaram "não implementado".
> Pedida pelo Diretor em 27/09, com autorização de `boto3` e de um **MinIO efêmero na lab,
> só para teste, sem dado real, derrubado ao fim de cada recibo**.

## O que existe, e o que falta

A 020 entregou a sequência inteira até o armazenamento: exportar em JSONL, sha256 do claro,
cifrar com gpg (a chave do `backup.sh`), decifrar e comparar com a partição viva linha a
linha, e **só então** entregar ao backend, que confere o que guardou. `drop_partition` recusa
sem esse recibo. Mas o único backend é `LocalDiskColdStorageBackend`: a cópia "fria" mora no
mesmo servidor que a quente. Os 20 anos de retenção (240 meses, ADR-0001) não têm destino
offsite.

## As decisões do Capitão (ordem 020) que este backend cumpre, uma a uma

| decisão | como |
|---|---|
| cifrado por nós antes de subir | inalterado: o backend recebe o `.jsonl.gpg` já conferido |
| um objeto por partição, manifesto como objeto próprio | dois `PutObject`; o manifesto fica em `STANDARD`, legível sem pedir restauração, e o payload vai em `GLACIER` |
| Object Lock em modo compliance pelo prazo | `ObjectLockMode=COMPLIANCE`, `RetainUntilDate` = agora + `AUDIT_LOG_COLD_LOCK_MONTHS` (240), em meses como o ADR-0001 |
| credencial que só grava | política em `docs/ops/auditlog-cold-writer-policy.json`: grava, lê e pede restauração; `Deny` explícito em apagar, bypass, legal hold e reconfigurar o bucket |
| verificar antes de subir | inalterado (a 020 já faz); e o upload leva `ChecksumSHA256`, que o S3 confere na chegada |
| conferir o remoto antes do DROP | `verify_stored` faz `HeadObject` da versão exata: checksum, modo `COMPLIANCE` e prazo da trava. Não baixa o objeto, porque no Glacier não daria |
| drill que baixa, decifra e confere a contagem | `drill_cold_copy` / `manage.py drill_audit_cold_copy`, com o ciclo assíncrono do Glacier: pede restauração, reconhece a espera (sai com 75, `EX_TEMPFAIL`), e só confere quando o objeto voltou |
| nada vai ao ar antes da conta AWS | `AUDIT_LOG_COLD_STORAGE_BACKEND` continua `local` por padrão; `s3` exige `AUDIT_LOG_COLD_S3_BUCKET` e recusa nomeando a setting |

## O que a medição na lab mostrou antes do código

Sondado num MinIO efêmero (derrubado em seguida), com a política acima no usuário gravador:
- o gravador **não apaga**, com ou sem `VersionId` (`AccessDenied`);
- nem o root apaga a versão, encurta a trava ou rebaixa para governance, mesmo com
  `BypassGovernanceRetention` (`Object is WORM protected`);
- bucket sem Object Lock recusa `PutObject` com lock (`Bucket is missing ObjectLockConfiguration`);
- checksum errado no PUT é recusado (`XAmzContentChecksumMismatch`);
- **um PUT sem os parâmetros de lock PASSA** num bucket com lock e sem retenção padrão. Só
  a conferência do `HeadObject` pega: por isso ela confere modo e prazo, não só o checksum;
- **o MinIO não aceita a classe `GLACIER`** (`InvalidStorageClass`). O ciclo de restauração
  se prova com o `Stubber` do botocore (parâmetros conferidos contra o modelo real da API),
  servindo o conteúdo cifrado de um export de verdade. O MinIO prova o resto com `STANDARD`.

**A imagem do MinIO:** o projeto arquivou o repositório e tirou as imagens do Docker Hub e
do quay e o `dl.min.io` (HTTP 410). `scripts/lab-minio/Dockerfile` baixa os binários do
release do GitHub (`RELEASE.2025-09-07T16-13-09Z`, `mc` `RELEASE.2025-08-13T08-35-41Z`) com o
sha256 **fixado no Dockerfile**. `PYTEST_MINIO=1 scripts/pytest.sh` sobe o MinIO na rede da
suíte, sem porta publicada, com credenciais aleatórias do recibo, e o derruba na saída com
qualquer código, conferindo por `docker --context lab ps -a` que sumiu.

## Achado na execução: o ponteiro da cópia fria morava só no stdout

`purge_audit_logs` imprimia a `stored_location` e mais nada. Depois do `DROP`, a cópia
fria é a única, e o drill precisa da location com as versões exatas. Agora cada expurgo
grava uma linha `audit_partition_purged` na trilha do próprio tenant, com a location e o
manifesto; o drill parte dela (teste: expurga, lê a linha, drila, confere). O teste antigo
que contava 1 linha na partição do mês corrente passa a contar a linha semeada mais a do
expurgo.

O drill mora em `apps/core/cold_drill.py` (responsabilidade própria; `cold_storage.py`
passaria de 400 linhas), e os testes publicados no vermelho o chamam por lá.

## Provas

- **Vermelho primeiro, publicado sozinho**, com a dependência (`boto3` no `base.txt` e no
  `production.lock`, só o fecho do boto3 entra) e o harness do MinIO: 27 testes falham por
  ausência do backend, da escolha de backend e do drill.
- Três camadas: `test_cold_storage_s3.py` (Stubber: parâmetros e recusas),
  `test_cold_drill.py` (ciclo do Glacier e controle negativo do drill: contagem, cifrado
  adulterado, claro divergente), `test_cold_storage_minio.py` (MinIO: exporta, confere,
  drila e só então dropa; o gravador não apaga; compliance recusa o root; bucket sem lock
  recusa; objeto sem lock não passa; manifesto adulterado no bucket é reprovado pelo drill).
- Sem MinIO (CI), a camada MinIO é pulada com motivo; com o endpoint definido e o MinIO fora
  do ar, ela falha.
- Recibo `order-32` na lab, suíte inteira **com `PYTEST_MINIO=1`**, no tip do branch; a
  saída mostra o MinIO derrubado.

## Fora desta ordem

- Criar o bucket e a credencial na AWS: não há conta (decisão do Capitão, ordem 020). O
  runbook diz o que criar e com qual política.
- Ligar o backend `s3` ou o expurgo em qualquer ambiente: decisão operacional posterior.
- `invite_token` com hash (ordem própria, fila do Diretor).

Nenhuma migration, nenhuma mudança de model, nenhuma mudança de permissão.


## Contrato de execução
- Trabalhe APENAS no branch `order/032-destino-frio-s3`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-32 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v6 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 032` (você não fecha a própria ordem).

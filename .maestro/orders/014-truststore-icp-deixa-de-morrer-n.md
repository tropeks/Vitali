<!-- maestro-order v1
id: 014
ts: 2026-09-16T12:51:42-03:00
epoch: 1789573902
head: c320d6b6aed4057fd555a01faddefea43bc15d4d
branch: order/014-truststore-icp-volume
intent_version: 5
intent_hash: a6120b3c
author_session: desconhecido
-->
# Ordem 014 — Truststore ICP deixa de morrer no deploy



## A medição

Instalei as âncoras ICP-Brasil no contêiner de staging às **15:27** por `docker cp`.
O deploy do vulcan-infra às **15:39** subiu a imagem nova e **elas sumiram** — o
truststore vem da imagem e não está montado em lugar nenhum.

```
15:27  docker cp  → 3 âncoras no truststore, assinatura com is_icp_brasil=True
15:39  up -d      → imagem nova
agora  ls         → só .gitignore e README
```

## Por que isso é grave, e não só inconveniente

A degradação é **silenciosa por desenho**. Com o store vazio, `chain.py` devolve
`"trust store not populated"` e `ICP_BRASIL_ENFORCE_CHAIN` **deliberadamente não
bloqueia** a assinatura — ela é gravada com `is_icp_brasil=False`.

Ou seja: o médico assina, a API responde **201**, a linha entra no `DigitalSignature`,
e a assinatura **perde o valor legal** sem que ninguém veja. Não há erro, não há alerta,
não há vermelho em lugar nenhum. É exatamente o verde mentiroso que o INTENT §Limites
proíbe — e nesta forma custa validade jurídica de prontuário.

## A mudança

Volume nomeado `icp_truststore` montado em `/app/apps/signatures/truststore`, no
`django` de **staging e produção**. As âncoras passam a sobreviver ao `up -d`, e
`refresh_icp_truststore` rodado uma vez dentro do contêiner persiste.

## Prova

```
staging  docker compose --env-file .env.staging config   OK, volume renderizado
prod     yaml válido, 14 serviços, volume declarado
```

Não é mudança de código de aplicação — é de topologia. O teste que a exerce é o próprio
`config` + o `ls` do truststore sobrevivendo a um recreate.

## O que NÃO entra

Popular o truststore. Hoje `refresh_icp_truststore` falha porque o
`acraiz.icpbrasil.gov.br` serve TLS **sem o intermediário** e encadeado na raiz
`ISRG Root YE`, ausente de todo trust store corrente (medido em 16/09). A saída não é
`verify=False` — é `--file` com o bundle baixado por um navegador. Isso é ato de operação,
não desta ordem.


## Contrato de execução
- Trabalhe APENAS no branch `order/014-truststore-icp-volume`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-14 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v5 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 014` (você não fecha a própria ordem).

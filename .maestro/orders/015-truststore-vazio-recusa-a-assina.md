<!-- maestro-order v1
id: 015
ts: 2026-09-16T15:34:43-03:00
epoch: 1789583683
head: 5e3b4991ca85f73c5c976b94267668d050298efb
branch: order/015-store-vazio-recusa
intent_version: 5
intent_hash: a6120b3c
author_session: desconhecido
-->
# Ordem 015 — Truststore vazio recusa a assinatura, em vez de grava-la como nao-ICP em silencio



## A medição — o defeito aconteceu de verdade, hoje

```
15:27  docker cp das âncoras      → assinatura real com is_icp_brasil=True
15:39  up -d do vulcan-infra      → âncoras apagadas
17:xx  ls no truststore           → só README.md
```

Entre 15:39 e agora, **qualquer assinatura feita em staging nasceria sem valor
legal** — e o sistema responderia `201`. O ramo em `icp_brasil.py:141` degradava
de propósito: logava um warning e gravava `is_icp_brasil=False`.

Um warning em log não é sinal. Ninguém lê log de staging a tempo de impedir a
assinatura que já foi dada como boa.

## O contrato novo

`ICP_BRASIL_ENFORCE_CHAIN` passa a valer também para o store vazio:

| valor | onde | store vazio |
|---|---|---|
| `True` | staging, produção (default do `base.py`) | **recusa** — `400`, motivo nomeado, nada gravado |
| `False` | dev, CI (agora explícito no `development.py`) | assina e grava `is_icp_brasil=False` |

Sem flag nova. O interruptor que já existia passa a cobrir o caso que faltava.

## O raio, e por que ele não estourou

Eram ~24 pontos de assinatura em teste, quase nenhum com `override_settings`, e o
`development.py` herdava `True`. **Eu previ no plano que precisaria editar três
asserções existentes** (`test_icp_brasil_signer.py:70` e `:103-116`,
`test_icp_brasil_chain.py:442-443`).

**Não precisei tocar em nenhuma.** Fixar a flag no `development.py` bastou: o
regime que elas descrevem continua sendo o regime de dev, e elas continuam
passando sem edição. O diff são dois arquivos de código e um de teste novo.

## Prova

```
teste que falha antes    2 falhas (serviço levanta, endpoint 400)
suíte completa           40 passam — signatures + lab reports
gate local               ruff check · ruff format · mypy · makemigrations --check
```

O teste do endpoint usa `TenantTestCase`: `signatures_digitalsignature` é tabela de
tenant, e rodar no schema público dá "relation does not exist" — erro que não diz
nada sobre a recusa que se quer provar. E ele verifica as **duas** metades: o `400`
com o motivo, e que **nenhuma linha** foi gravada. Recusa que deixa rastro de
assinatura feita não é recusa.

## O que NÃO entra

Popular o truststore de staging. O `#218` (volume) está mesclado mas **não
implantado** — medido agora: o compose da lab não tem o volume, o volume não existe.
Depois do próximo deploy, `refresh_icp_truststore --file` com o bundle que o Capitão
vai subir.

**Consequência operacional imediata:** com esta ordem em produção e o store vazio,
a assinatura **para de funcionar** até alguém popular o trust store. É o
comportamento correto — e é melhor descobrir isso por um `400` do que por um
prontuário sem validade jurídica seis meses depois.


## Absorção

Mesclada em `onda0-perimetro-multitenant` pelo PR #219. Como nas ordens 013 e 014, o
ledger não registra a absorção: `--absorbed-by` exige um branch chamado `main` e o
principal deste repositório é `master` — quarta ocorrência do mesmo defeito do maestro,
já na lista de issues do Imediato. Fica escrito aqui.

**Ordem de operação antes de isto valer em produção:**

1. deploy do `#218` — o volume `icp_truststore`
2. `refresh_icp_truststore --file <ACcompactado.p7b>` dentro do contêiner
3. só então a 015 em produção, senão ninguém assina — por escolha, não por acidente


## Contrato de execução
- Trabalhe APENAS no branch `order/015-store-vazio-recusa`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-15 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v5 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 015` (você não fecha a própria ordem).
accepted_at: 2026-09-16T16:38:40-03:00
accepted_session: desconhecido
accepted_tree: 983e61cb1079b668753f46bf012f0032d0699b83
accepted_intent: 5

<!-- maestro-order v1
id: 013
ts: 2026-09-16T07:52:43-03:00
epoch: 1789555963
head: c6a4d6236ea3f4bdc0c210e9bad5ce34375621c3
branch: order/013-cbhpm-porte-codigo
intent_version: 5
intent_hash: a6120b3c
author_session: desconhecido
-->
# Ordem 013 — CBHPM: o porte vira codigo, e a valoracao deixa de fingir que ele e numero



## A medição, antes do plano

O Capitão apontou o PDF público da CBHPM 2022 rev. ago/2023 (240 páginas). Antes de
importar, medi o que o `import_cbhpm` esperava contra o que o livro dá:

```
layouts de tabela no PDF          8, mudando por capítulo
procedimentos extraíveis          4.881
porte NUMÉRICO entre eles         0
porte fracionário ("0,01 de 1A")  1.046  (21% do catálogo)
```

`CBHPMItem.porte` era `DecimalField`, rotulado "quantidade de CH", e o importador o
passava por `_to_decimal()` — que levanta em `"3B"`. **O catálogo importaria 0 linhas.**

E o erro tentador era pior que a recusa: cortar o `0,01 de` e gravar `1A` como `1`
infla o porte **de 25 a 100 vezes** no capítulo mais volumoso do livro. INTENT
§Limites: nenhum número contratual inventado.

**A separação que esta ordem faz.** O livro dá CLASSIFICAÇÃO; a VALORAÇÃO é contrato —
o §1.2 da própria CBHPM diz que os portes "não expressam valores monetários" e que a
valoração "ficará sujeita a [negociação] entre as partes".

| campo | o que guarda | de onde vem |
|---|---|---|
| `porte` (novo: `CharField`) | a classe publicada: `3B`, `13C`, `0,01 de 1A` | do livro |
| `porte_ch` (novo) | a quantidade de CH | **só** de tabela de valoração contratada |
| `valor()` | `porte_ch × valor_ch` | zero enquanto não houver contrato |

Importar o livro passa a **não produzir preço**, e é assim que tem de ser.

## O que a migration faz com o dado que já existe

O decimal que estava em `porte` sempre significou quantidade de CH — é o que o
`help_text` dizia e o que `valor()` multiplicava. Ele é **renomeado, copiado para
`porte_ch` e só então removido**, em quatro operações visíveis no diff. Nenhuma
valoração muda de resultado. `porte` nasce vazio: a classe publicada é informação que
o banco nunca teve, e derivá-la do número seria fabricar dado.

## Prova

```
teste que falha antes      5 falhas em test_cbhpm_porte_codigo.py
suíte CBHPM completa       25 passam (modelo, importador, valoração, faturamento)
dry-run das 4.881 reais    4.881 created · 0 updated · 0 skipped · success
gate local                 ruff check · ruff format · mypy · makemigrations --check
```

O dry-run achou mais dois defeitos meus, ambos consertados:

- **`3.09.11.00-1`** é código de **seção**, não procedimento — arrastava um bloco de
  OBSERVAÇÕES e o importador recusou a linha ao ler `CARDIOLOGIA` como decimal.
- **`3.02.08.15-7` aparece duas vezes**, e isso é do livro: impresso em duas páginas
  com porte, auxiliares e anestésico idênticos. Deduplicado; repetição com dados
  **diferentes** iria para quarentena, nunca "o último que escreveu ganha".

O extrator entrou no repo (`scripts/catalogs/etl_cbhpm_pdf.py`) e a cópia versionada
reproduz byte a byte o CSV que passou no dry-run — o PDF não é reproduzível a partir
de um script que vive no `/tmp` de alguém.

## O que NÃO entra

**Nenhuma linha da CBHPM é importada por este PR.** A folha de rosto diz `© 2022
Editora Manole / AMB — Todos os direitos reservados`; o Imediato autorizou importar em
staging enquanto a licença está com o Capitão, e **cobrar por ela não**. Este PR entrega
a forma do campo, o importador e a prova — o import fica para quando a licença voltar.


## Absorção

Mesclada em `onda0-perimetro-multitenant` pelo PR #217, com os cinco jobs verdes em
`36dd241`. **O ledger não registra a absorção**: `maestro order --accept --absorbed-by
main` exige um branch chamado `main`, e o principal deste repositório é `master` —
terceira vez que este defeito aparece, e já está na lista de issues do Imediato para o
Maestro. Fica escrito aqui, que é onde quem procurar vai achar.


## Contrato de execução
- Trabalhe APENAS no branch `order/013-cbhpm-porte-codigo`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-13 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v5 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 013` (você não fecha a própria ordem).
accepted_at: 2026-09-16T09:25:04-03:00
accepted_session: desconhecido
accepted_tree: 04e5c0658e762780296676596f8d18bf27c044e9
accepted_intent: 5

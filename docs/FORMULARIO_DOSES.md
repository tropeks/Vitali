# Contrato do arquivo do formulário de doses (ordem 028)

> **Para:** o farmacêutico clínico que compila o arquivo-fonte do verificador
> automático de dose do Vitali (contratado pelo Capitão, decisão do Diretor de
> 26/09/2026).
>
> **Este documento é o CONTRATO do arquivo.** O importador
> (`apps.pharmacy.services.formulary_import`, usado pelo comando
> `import_formulary` e pela UI de upload) recusa qualquer desvio dele, nomeando
> a linha física e a coluna do erro. Nada aqui é negociável em código — se o
> arquivo não seguir o contrato, o import falha alto (nada é gravado).
>
> ⚠️ **O exemplo abaixo usa uma droga FICTÍCIA ("Ficticiol") e valores
> FICTÍCIOS, marcados como tal.** Eles existem só para mostrar o formato das
> colunas — **não são posologia real e nunca devem ser copiados para o arquivo
> de verdade.** O arquivo real é pesquisado e assinado por você; nenhum agente
> de IA nem código deste repositório inventa, corrige ou completa um número
> clínico.

## 1. Formato geral

- CSV delimitado por vírgula (`,`), primeira linha = cabeçalho com os nomes de
  coluna exatos da seção 2 (case-sensitive).
- Linhas começadas com `#` são comentários e são ignoradas — use-as para
  observações, ou para o cabeçalho de versão (seção 4).
- Uma linha = uma **regra de dose** (`DoseRule`). Um mesmo medicamento pode ter
  várias linhas (uma por banda de idade/peso/frequência/papel — ver seção 3).
- O importador roda em duas passadas e **nunca importa parcialmente**: se
  QUALQUER linha falhar (parse ou validação de modelo), NENHUMA linha é
  gravada. O erro nomeia `Line N` (contando comentários, 1-based) e a coluna.

## 2. Colunas

| Coluna | Obrigatória | Tipo / valores aceitos | Observação |
|---|---|---|---|
| `drug_name` | sim | texto | Nome do medicamento (`Drug.name`, criado se não existir) |
| `drug_generic` | não | texto | Nome genérico |
| `strength_value` | sim | decimal | Força/concentração da apresentação canônica |
| `strength_unit` | sim | `mg`\|`mcg`\|`mEq`\|`unit`\|`g` | Unidade de massa da força |
| `route` | sim | `IV`\|`IM`\|`SC`\|`PO` | Via de administração canônica |
| `basis` | sim | `per_kg`\|`fixed` | `per_kg` = a faixa escala com o peso; `fixed` = faixa absoluta |
| `dose_unit` | sim | `mg`\|`mcg`\|`mEq`\|`unit`\|`g` | Unidade ABSOLUTA de massa — nunca "mg/kg"; o "/kg" já está implícito em `basis=per_kg` |
| `min_per_kg` / `max_per_kg` | obrigatórias se `basis=per_kg` | decimal | Faixa por kg de peso, por administração, em `dose_unit`/kg |
| `min_per_dose` / `max_per_dose` | obrigatórias se `basis=fixed` | decimal | Faixa absoluta por administração, em `dose_unit` |
| `absolute_max_dose` | **sempre obrigatória** | decimal (> 0) | Teto absoluto por administração, em `dose_unit`. Sempre bloqueia (é o que pega peso digitado errado: 70 kg virar 700 kg) |
| `max_per_day` | não | decimal | Teto da dose diária cumulativa (dose × frequência), em `dose_unit` |
| `dose_role` | não (default `maintenance`) | `maintenance`\|`loading` | Eixo 2: uma regra `loading` só é escolhida quando o item é marcado explicitamente como ataque |
| `enforcement` | não (default `block`) | `block`\|`advise` | Eixo 3: `advise` é para droga sem teto farmacológico rígido (opioide/sedativo titulado) — o veredito fora da faixa vira alerta, não bloqueio. `absolute_max_dose` e a falta de peso continuam bloqueando mesmo em `advise` |
| `freq_min_per_day` / `freq_max_per_day` | não | inteiro | Eixo 1: banda de frequência a que a regra se aplica (permite 2 regras para a mesma droga, ex. esquema estendido vs tradicional) |
| `age_min_days` / `age_max_days` | não | inteiro (dias, não anos) | Banda etária. Vazio = sem limite naquele lado |
| `weight_min_kg` / `weight_max_kg` | não | decimal | Banda de peso. Vazio = sem limite naquele lado |
| `fonte_tipo` | **sim** | `bula_anvisa`\|`literatura` | Procedência — ver seção 3 |
| `fonte_ref` | **sim** | texto | Procedência — ver seção 3 |
| `fonte_trecho` | **sim** | texto | Procedência — ver seção 3 |

Uma banda vazia (`age_min_days`, `weight_min_kg`, etc.) é **sem limite** naquele
lado — não é zero. `min_per_dose`/`max_per_dose`/`min_per_kg`/`max_per_kg`
vazios são permitidos apenas quando `basis` não os exige (ex. `min_per_kg` fica
vazio quando `basis=fixed`).

## 3. Procedência — obrigatória em TODA linha

INTENT v6 §Limites: nenhum número de dose entra no sistema sem procedência
registrada. As três colunas de procedência são obrigatórias em cada linha —
uma linha sem elas reprova o import inteiro:

- **`fonte_tipo`**: `bula_anvisa` (o número veio de uma bula registrada na
  ANVISA) ou `literatura` (veio de uma referência bibliográfica/protocolo).
- **`fonte_ref`**:
  - se `fonte_tipo=bula_anvisa`: o **registro ANVISA** do produto e a **data**
    da bula consultada (ex.: `"1.2345.6789.001-0, bula rev. 2025-03"`).
  - se `fonte_tipo=literatura`: a referência ou o **DOI** (ex.:
    `"DOI:10.xxxx/exemplo"` ou a citação completa).
- **`fonte_trecho`**: a posologia **tal como consta na fonte** (a citação
  literal, não uma paráfrase) — o texto que justifica o número que você
  colocou em `min_per_kg`/`max_per_dose`/etc.

O importador não confere se a citação é verdadeira — confere só que ela
**existe**. A responsabilidade pelo número é de quem assina o arquivo (você).

## 4. Cabeçalho de versão e catálogo

O arquivo em si NÃO carrega a versão — a versão vive no manifesto
(`scripts/catalogs/manifest.toml`, catálogo `formulario_doses`), com
`version` (a data da compilação da base), `sha256` do arquivo e
`source_kind = "bulario_anvisa+literatura"`. Isso é preenchido por quem opera
o `seed_catalogs`, não por você — mas cada revisão do arquivo que você entrega
deve ter uma data (no nome do arquivo ou na comunicação) para que essa versão
seja registrada corretamente.

Um arquivo com o cabeçalho de comentário `# sintetico: true` é tratado como
**dado de teste fabricado** e o importador o recusa fora de teste — nunca
inclua essa linha no arquivo real.

## 5. O que a reimportação faz com uma linha já validada

Se você reenviar uma versão do arquivo em que a **banda, o teto (absolute_max_dose,
max_per_day) ou a unidade** de uma linha já `validado` (assinada por outro
farmacêutico anteriormente) mudou, o import:

1. volta essa linha para `nao_validado` automaticamente;
2. limpa o registro de quem validou e o retrato do CRF (a validação antiga não
   valia para os números NOVOS);
3. grava uma auditoria com o valor antigo e o novo.

Uma linha que **não mudou clinicamente** mantém a validação — reenviar o mesmo
arquivo (ou um arquivo onde você só corrigiu a citação em `fonte_trecho`, sem
mudar número/unidade) não desvalida nada.

## 6. Como validar (você, farmacêutico)

Validar uma linha SEMPRE exige que você tenha, no Vitali, um cadastro
profissional ativo com `council_type="CRF"` (seu número e UF de conselho).
Sem isso, o sistema recusa a validação com 403. Ao validar pela tela de
curadoria, o sistema grava o retrato do seu CRF (número e UF) e a data — um
retrato imutável: se seu cadastro mudar depois (renovar CRF, mudar de UF), o
retrato da validação já feita não muda.

Uma linha `nao_validado` já aparece no sistema como **alerta informativo**
(nunca bloqueia sozinha) assim que o arquivo é importado — ela não fica
invisível esperando sua revisão; ela sinaliza que ainda não foi revisada.

## 7. Exemplo (FICTÍCIO — não copiar números para produção)

```csv
# sintetico: true
drug_name,drug_generic,strength_value,strength_unit,route,basis,dose_unit,min_per_dose,max_per_dose,absolute_max_dose,dose_role,enforcement,fonte_tipo,fonte_ref,fonte_trecho
Ficticiol,ficticiolum,100.000,mg,IV,fixed,mg,1,2,2,maintenance,block,literatura,DOI:10.0000/ficticiol,Trecho ficticio de teste — nao clinico
```

A linha `# sintetico: true` acima é o que faz o importador recusar este
exemplo fora de um teste automatizado — remova-a (e os valores fictícios) no
arquivo real.

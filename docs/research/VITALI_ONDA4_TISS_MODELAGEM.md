# Onda 4 — Modelagem de domínio para fechar SP/SADT e Resumo de Internação (TISS 4.01.00)

> Documento de planejamento. Não altera código. Alvo: `SadtGuideXMLConformanceTests` e
> `InternacaoGuideXMLConformanceTests` (`backend/apps/billing/tests/test_xml_engine.py`),
> hoje `xfail(strict=True)`.

## Resumo executivo (leia isto e decida)

1. **`xfail` subestima de novo** — não é só dado faltando, é **forma errada**:
   `sadt`/`internacao_guide.xml.j2` nunca foram reescritos pós-Onda 2, cabeçalho não bate
   com o XSD real. `consulta_guide.xml.j2` (já passa) prova a forma certa. **Fatia 0 = portar
   essa forma, zero migration**, antes de tocar em model.
2. `dadosSolicitante` só existe em SP/SADT, **não** em Resumo de Internação — escopo menor
   do que o pedido supunha.
3. Precedente pronto para copiar: `AihAutorizacao` (SUS/B7) já tem `carater_internacao`
   (`TextChoices`) + `professional_solicitante` FK. Códigos diferem (SUS `'01'/'02'` × TISS
   `'1'/'2'`) — mapear, não reusar cru.
4. `ct_guiaValorTotal` não tem classificação por categoria em lugar nenhum hoje, e
   `TUSSCode.group` é grosso demais para separar taxa de gás medicinal. Seção própria (§4).
5. Taxonomias fechadas pequenas (≤30 valores, XSD pinado) → `TextChoices` no model, como
   `Admission.AdmissionSource`/`AihAutorizacao` já fazem — **não** criar catálogo governado.
6. XSD não traz rótulo em português dos códigos — não fabricar copy de UI sem checar o
   manual ANS.
7. Sequência: **Fatia 0 (template) → 1 (`reducaoAcrescimo`) → 2 (solicitante+caráter SADT)
   → 3 (taxonomias internação) → 4 (referência+senha) → 5 (`valorTotal` simples) → 6
   condicional (`valorTotal` completo)**.

> **ESTADO EM 18/08/2026 — leia antes do resto.** A guia de Resumo de Internação está
> em conformidade total (`validate_xml == []`) e **com discriminação de itens**:
> `procedimentosExecutados` passou a ser emitido. O que este documento chamava de
> "campo novo trivial, default `0`" para `reducaoAcrescimo` **estava errado e foi
> corrigido** — é fator multiplicativo, neutro `1.00` (§2). Residual real que
> permanece: (a) `valorTotal` ainda é a Alternativa A (só `valorTotalGeral`, sem
> breakdown por categoria — glosa por isso é prática real de mercado); (b) linhas
> faturadas antes da migration `0036` não têm `execution_date` e a emissão falha
> alto nelas, de propósito, porque não há fonte honesta para backfill; (c) a SP/SADT
> segue em `xfail`, parada em `dadosSolicitante`.

**3 decisões do Capitão**: (a) aprovar Fatia 0 como pré-requisito; (b) taxonomias de
internação moram em `Admission` ou só em `TISSGuide`? (§5); (c) `ct_guiaValorTotal` aceita
total único ou exige classificação por item? (§4).

---

## 1. Metodologia desta investigação

Os XSDs foram parseados programaticamente (`lxml`, não `grep` — o arquivo é ISO-8859-1 e
tem linhas de dezenas de KB, `grep` cego mentiria por omissão, que foi exatamente o erro da
leitura manual da Onda 2). Percorri `ctm_sp-sadtGuia` e `ctm_internacaoResumoGuia`
recursivamente, incluindo tipos aninhados e `xs:extension`, até a folha, resolvendo cada
`simpleType` para seu enum fechado quando existe. A árvore completa está no apêndice §7; as
tabelas abaixo são a leitura orientada a "de onde vem o dado".

## 2. Inventário — SP/SADT (`ctm_sp-sadtGuia`)

| Campo XSD | Obrigatório | Hoje existe? | Onde | Fonte real no fluxo clínico |
|---|---|---|---|---|
| `cabecalhoGuia.registroANS` | sim | ✅ | `guide.provider.ans_code` | já funciona (Onda 2) |
| `cabecalhoGuia.numeroGuiaPrestador` | sim | ✅ | `guide.guide_number` | já funciona |
| `dadosAutorizacao.dataAutorizacao` | sim, **se o bloco existir** (bloco é opcional) | ✅ **(B10, resolvido)** | `TISSGuide.authorization_date` — resolvido a partir de `Authorization` aprovada (fonte preferida) ou, na ausência, da digitação manual (`authorization_number`+`authorization_date` juntos); ver `xml_engine._resolve_internacao_authorization` | campo existe (models.py, migration `0034`); SADT ainda não invoca o resolver (só `internacao` — §3 — o bloco `dadosAutorizacao` do SADT continua fora desta fatia) |
| `dadosAutorizacao.senha` | opcional dentro do bloco | ✅ | `guide.authorization_number` | já existe, `blank=True` |
| `dadosBeneficiario.numeroCarteira` | sim | ✅ | `guide.insured_card_number` | já funciona |
| `dadosBeneficiario.atendimentoRN` | sim (S/N) | ❌ | — | hoje hardcoded `"N"` no template — aceitável como default documentado (RN é minoria), não é bloqueador de dado |
| `dadosSolicitante.contratadoSolicitante` (CNPJ/CPF/`codigoPrestadorNaOperadora`) | sim | ❌ | — | é o prestador (clínica/consultório) do profissional solicitante — **não existe conceito de "prestador do solicitante" no Vitali**, só do executante (via `professional.cnes_code` usado como placeholder, mesma gambiarra já aceita na Onda 2 para o executante) |
| `dadosSolicitante.nomeContratadoSolicitante` | sim | ❌ | — | idem |
| `dadosSolicitante.profissionalSolicitante` (conselho/nº/UF/CBOS) | sim | ❌ (mas há filtros Jinja prontos: `conselho_ans_code`, `uf_ibge_code`) | — | **fonte real já existe em parte**: `emr.LabOrder.requested_by` é `core.User` — quando a guia SADT nasce de um pedido de exame (ponte `TISSGuide.lab_order`), o solicitante é literalmente quem pediu o exame. Falta (i) resolver `User → Professional` (`user.professional`, nem todo `requested_by` tem perfil de profissional) e (ii) um FK em `TISSGuide` para guardá-lo. Para guias sem `lab_order` (ex.: SADT manual), não há hoje NENHUMA captura — precisa de tela nova. |
| `dadosSolicitacao.caraterAtendimento` | sim | ❌ | — | ver precedente `AihAutorizacao.CaraterInternacao` (§5); para SADT ligado a `SurgicalCase`, `SurgicalCase.Priority` (eletiva/urgência/emergência) é candidato de mapeamento |
| `dadosSolicitacao.indicacaoClinica` | opcional | parcial | `guide.encounter` tem `chief_complaint` (encrypted) — não é o mesmo campo semântico | não bloqueador (opcional) |
| `dadosSolicitacao.indCobEspecial` | opcional | ❌ | — | não bloqueador (opcional) |
| `dadosExecutante.contratadoExecutante` (choice) | sim | ✅ (placeholder) | template já usa `professional.cnes_code` como `codigoPrestadorNaOperadora` — mesmo padrão aceito no `consulta_guide.xml.j2` | já resolvido do jeito "placeholder documentado" — só falta portar a forma para o template SADT (Fatia 0) |
| `dadosExecutante.CNES` | sim | ✅ | `professional.cnes_code` (governado via `core.CNESEstablishment`) | já funciona |
| `dadosAtendimento.tipoAtendimento` | sim | ❌ | — | taxonomia ANS de 9 valores sem equivalente — **decisão de produto**: provavelmente sempre "SADT" (código a confirmar no manual ANS), pode ser default fixo documentado em vez de campo por guia |
| `dadosAtendimento.indicacaoAcidente` | sim | ❌ | — | já tem default seguro `"9"` (não acidente) usado no `consulta_guide.xml.j2`; portar |
| `dadosAtendimento.regimeAtendimento` | sim | ❌ | — | 5 valores; SADT ambulatorial = "01" cobre a maioria; internado precisaria saber se a guia SADT nasceu durante uma internação (`guide.admission_id` já existe como sinal) |
| `procedimentosExecutados[].reducaoAcrescimo` | sim, por item | ✅ **(resolvido)** | `TISSGuideItem.reduction_increase_factor` (migration `0036`) | **CORREÇÃO — o `default 0` proposto aqui estava ERRADO.** É um FATOR multiplicativo, não um valor: o tipo irmão `ct_procedimentoExecutado` chama o mesmo conceito de `fatorReducaoAcrescimo`, e `st_decimal3-2` (totalDigits 3, fractionDigits 2 → máx **9,99**) é faixa de multiplicador, não de reais nem de percentual. O neutro é **`1.00`**; `0.00` declararia à operadora que a linha vale zero e ainda cobraria `valorTotal`. Precedente do próprio repo, anterior a este doc: `docs/DATA_MODEL.md` já especificava `reduction_factor DECIMAL DEFAULT 1.0`. O rótulo ANS segue não conferido — 1.00 é o neutro por consistência aritmética (`valorTotal = valorUnitario × quantidadeExecutada × fator`), não por manual lido |
| `valorTotal` (`ct_guiaValorTotal`) | sim | parcial | `guide.total_value` (total único) | seção própria §4 |

## 3. Inventário — Resumo de Internação (`ctm_internacaoResumoGuia`)

**Correção ao escopo do pedido**: este guide type **não tem** `dadosSolicitante`. Tem
`numeroGuiaSolicitacaoInternacao` (referência textual a um documento anterior) e
`dadosExecutante` (mesma choice `contratadoExecutante` + CNES do SADT — já resolvido pelo
placeholder existente).

| Campo XSD | Obrigatório | Hoje existe? | Onde | Fonte real |
|---|---|---|---|---|
| `numeroGuiaSolicitacaoInternacao` | sim | ❌ | — | referência a uma guia de solicitação de internação que o Vitali não modela como documento separado; candidato mais barato: reusar `guide.guide_number` da própria guia como autorreferência (defensável só se não existir uma guia de solicitação prévia real) — **decisão de produto**, não é puramente técnico |
| `dadosAutorizacao.senha` + `dadosAutorizacao.dataAutorizacao` | **sim** (obrigatório aqui, opcional no SADT) | ✅ **(B10, resolvido)** | `guide.authorization_number` (senha) + `TISSGuide.authorization_date` (fallback de digitação) ou `Authorization` aprovada resolvida (fonte preferida — vence sempre que resolve) | `generate_guide_xml` falha alto (`TISSXMLGenerationError`, mensagem acionável) quando nem a `Authorization` resolve nem o par digitado está completo — nunca fabrica a data; ver `xml_engine._resolve_internacao_authorization` |
| `dadosBeneficiario` | sim | ✅ **(resolvido, esta fatia)** | `guide.insured_card_number` + `atendimentoRN="N"` default | `ct_beneficiarioDados` — MESMO tipo já emitido por `consulta_guide.xml.j2`/`sadt_guide.xml.j2`; pura ligação, sem campo novo |
| `dadosExecutante` | sim | ✅ **(resolvido, esta fatia)** | `professional.cnes_code` (encounter.professional) | forma nova (`contratadoExecutante`/`ct_contratadoDados` + `CNES` irmão, diferente do par `contratadoExecutante`+`profissionalExecutante` de `guiaConsulta`), mas dado já resolvido em todo template desta pasta — mesmo placeholder de `codigoPrestadorNaOperadora` do cabeçalho do lote |
| `dadosInternacao.caraterAtendimento` | sim | ✅ **(ligado)** | `Admission.carater_atendimento` via `TISSGuide.admission` | `xml_engine._resolve_internacao_dados` resolve a internação vinculada e falha alto (`TISSXMLGenerationError` acionável) quando o campo está vazio — nunca default silencioso |
| `dadosInternacao.tipoFaturamento` | sim | ✅ **(resolvido)** | `TISSGuide.tipo_faturamento` (`TextChoices`, migration `0035_guide_tipo_faturamento`) | **CORREÇÃO ao §5 abaixo**: mora em `TISSGuide`, NÃO em `Admission`. A medição do XSD (feita depois deste doc) mostrou que `ctm_internacaoDados` tem OITO filhos obrigatórios, não quatro — os quatro que faltavam nesta tabela são `dataInicioFaturamento`/`horaInicioFaturamento`/`dataFinalFaturamento`/`horaFinalFaturamento`, que provam que o bloco descreve o PERÍODO DE FATURAMENTO da guia, não a estada. Rótulos deliberadamente pendentes ("Código N (rótulo a confirmar no manual ANS)") — o XSD não tem `xs:documentation` e o manual ANS não está no repo |
| `dadosInternacao.tipoInternacao` | sim | ✅ **(ligado)** | `Admission.tipo_internacao` | idem `caraterAtendimento` |
| `dadosInternacao.regimeInternacao` | sim | ✅ **(ligado)** | `Admission.regime_internacao` | idem `caraterAtendimento` |
| `dadosInternacao.data/horaInicioFaturamento` | sim | ✅ **(ligado)** | `Admission.admission_datetime` | NÃO estava nesta tabela até a medição do XSD. Convertido para o fuso da clínica antes de formatar (`_local_datetime`): `st_data`/`st_hora` são locais, o banco guarda UTC |
| `dadosInternacao.data/horaFinalFaturamento` | sim | ✅ **(ligado)** | `Admission.actual_discharge_datetime` | idem. Internação ainda aberta → falha alta: a guia de resumo só fecha depois da alta |
| `dadosSaidaInternacao.indicadorAcidente` | sim | ✅ (default) | — | `"9"` (não acidente), mesmo default já documentado em `consulta_guide.xml.j2` |
| `dadosSaidaInternacao.motivoEncerramento` (`dm_motivoSaida`, 28 valores) | sim | ✅ **(ligado)** | `Admission.disposition_ans_code` (Fatia 3, já landed — campo TISS-specific dedicado, NÃO reaproveita `Admission.disposition`) | resolveu a ressalva de granularidade abaixo: em vez de mapear `Disposition` (6 valores clínicos), ganhou campo próprio com os 28 códigos ANS; ligação feita nesta fatia — vazio na internação → falha alta apontando a tela de alta |
| `valorTotal` (`ct_guiaValorTotal`) | sim | ✅ **(Alternativa A)** | `valorTotalGeral = guide.total_value`, sete breakdowns omitidos | §4. Fecha o schema, NÃO fecha o aceite: o breakdown diária × taxa × gás medicinal continua ausente e `DailyCharge`/`InpatientFee` seguem fundidos em `TISSGuideItem` sem proveniência (Alternativa B, aberta) |
| `procedimentosExecutados` (bloco) | **não** (`minOccurs="0"`) | ✅ **EMITIDO (fatia final)** | `xml_engine._resolve_internacao_procedimentos` + `internacao_guide.xml.j2` | o bloco é opcional no schema, e era omitido — a guia saía **schema-válida com o total geral e zero discriminação de itens, que nenhuma operadora paga**. Destravado com os dois campos novos em `TISSGuideItem` (`execution_date`, `reduction_increase_factor`, migration `0036`) e com as CINCO pontes clínico→faturamento passando a datar cada linha da fonte real: diária/taxa pela `service_date`, exame pelo `resulted_at`, cirurgia e material pela **incisão** (`SurgicalTime.INCISAO`, não `scheduled_start` — agendar não é executar), medicamento pelo `dispensed_at` que agora trafega no payload do sinal (a fronteira `billing ⇸ pharmacy` do import-linter impede ler `Dispensation` do faturamento). Nenhuma usa `now()`: data de faturamento não é data clínica |
| `procedimentosExecutados[].reducaoAcrescimo` | sim, por item | ✅ **(resolvido)** | `TISSGuideItem.reduction_increase_factor` | mesmo campo do SADT (é o mesmo `TISSGuideItem`) — ver a correção do `default 0` na linha correspondente do §2 |

## 4. `ct_guiaValorTotal` — seção própria

```
valorProcedimentos      opcional
valorDiarias             opcional
valorTaxasAlugueis       opcional
valorMateriais           opcional
valorMedicamentos        opcional
valorOPME                opcional
valorGasesMedicinais     opcional
valorTotalGeral          OBRIGATÓRIO
```

Só `valorTotalGeral` é obrigatório — tecnicamente uma guia com todos os sete breakdowns
omitidos e só o total geral já é *schema-válida*. Isso muda o cálculo de custo: **não é
preciso classificar cada item para sair do `xfail`** — dá para emitir `valorTotalGeral =
guide.total_value` e nada mais, e o XSD aceita. A pergunta de produto é se isso é
*semanticamente aceitável* para a operadora (glosa por breakdown ausente é uma prática real
de algumas operadoras, mas não é violação de schema).

### Por que não é trivial derivar o breakdown completo hoje

- `TUSSCode.group` é **grosso demais**: `test_inpatient_fees.py` usa
  `group="Diárias, taxas e gases medicinais"` para a tabela 18 inteira. `valorDiarias`,
  `valorTaxasAlugueis` e `valorGasesMedicinais` são três campos TISS distintos que essa
  única string ANS não separa.
- `TUSSCode.table_number` (`dm_tabela`: `18,19,20,22,90,98,00`) é o eixo mais promissor —
  mas eu **não vou fabricar** a correspondência tabela→categoria neste documento. O
  significado oficial de cada número (18=diárias/taxas/gases é conhecido pelo código já
  escrito em `record_inpatient_fee`; os demais não foram confirmados aqui contra uma fonte
  primária). Antes de codar a Fatia 4, rodar
  `TUSSCode.objects.values('table_number').distinct()` contra o catálogo importado de
  verdade (ou o manual ANS) e fixar a tabela de correspondência como parte do PR, não do
  planejamento.
- **Proveniência se perde na agregação**: `generate_internacao_guide_for_admission` funde
  `DailyCharge` (diária) e `InpatientFee` (taxa/gás) no mesmo dicionário `aggregated` por
  `tuss_code_id`, e `TISSGuideItem` não guarda de qual dos dois modelos veio (ao contrário
  de `surgical_material`/`dispensation_source_id`, que TISSGuideItem já rastreia para
  OPME/medicamento). É recuperável **hoje** só porque `DailyCharge`/`InpatientFee`
  continuam existindo como linhas próprias ligadas à `Admission` (não são apagados após
  virar guia) — dá para re-somar por fora sem tocar no agregado da guia. Isso é frágil: se
  algum dia esses registros passarem a ser podados/arquivados, a reconstrução quebra
  silenciosamente.
- Para SADT, o sinal é melhor: `TISSGuideItem.surgical_material` (não nulo → material/OPME)
  e `dispensation_source_id` (não nulo → medicamento) já existem. Combinados com
  `TUSSCode.group`/`table_number`, cobrem `valorMateriais`/`valorOPME`/`valorMedicamentos`
  razoavelmente bem sem campo novo. `valorProcedimentos` é "o resto".

### Duas alternativas

**A — Total único, breakdown zero.** `valorTotalGeral = guide.total_value`, os sete campos
opcionais omitidos. Sai do `xfail` imediatamente, zero migration, zero decisão de produto.
Risco: operadoras que exigem breakdown (prática comum em glosas hospitalares) rejeitam ou
glosam na prática, mesmo com XML schema-válido — **conformidade de schema ≠ aceite da
operadora**, e isso precisa estar explícito para quem for aprovar esta fatia como "pronta".

**B — Breakdown derivado por classificação de item.** Requer (i) fixar a correspondência
`table_number`/`group` → categoria TISS contra o catálogo real (medição, não suposição),
(ii) para o caso de internação, decidir se a proveniência `DailyCharge` vs `InpatientFee`
continua sendo reconstruída por fora do agregado ou se `TISSGuideItem` ganha um campo de
categoria explícito (mais robusto, mais migration) preenchido no momento da agregação em
`generate_internacao_guide_for_admission`. Retroativo: guias já geradas **antes** dessa
mudança não têm como ser reclassificadas com certeza se a proveniência já foi perdida (só
as futuras, geradas depois do campo existir, seriam confiáveis 100%; as passadas dependem
da reconstrução por `Admission.daily_charges`/`inpatient_fees`, que funciona hoje mas não é
garantida para sempre).

**Recomendação**: começar pela Alternativa A (sai do `xfail`, mede o resto do gap real) e
tratar B como uma fatia separada, condicionada a (a) confirmar a correspondência
tabela→categoria contra dado real e (b) o Capitão decidir se a operadora-alvo do MVP exige
breakdown de fato ou se `valorTotalGeral` sozinho já resolve o caso de uso imediato.

## 5. Proposta de modelagem — taxonomias fechadas

Todas as enumerações abaixo (`caraterAtendimento`, `tipoInternacao`, `regimeInternacao`,
`tipoFaturamento`, `tipoAtendimento`, `regimeAtendimento`, `motivoEncerramento`) têm entre 2
e 28 valores, são publicadas pela ANS como parte fixa da versão 4.01.00 do XSD (não são
recarregadas por CSV/ETL como TUSS/CBO/CNES/CID-10), e o repo já tem um padrão testado para
exatamente esse formato: `Admission.AdmissionSource`/`Disposition`/`Status` e, mais perto
ainda, `AihAutorizacao.CaraterInternacao`/`MotivoSaida`/`Situacao` — todos `TextChoices` no
próprio model.

**Alternativa 1 — `TextChoices` no model (recomendada).** Mesmo padrão de
`AihAutorizacao`. Custo: 1 migration por model tocado, zero infraestrutura nova. Risco: se a
ANS revisar a domain table numa versão futura do XSD, o código muda (mas o Capitão já
confirmou que não há troca de versão no horizonte).

**Alternativa 2 — Catálogo governado (`TerminologyCatalog`).** Padrão de `TUSSCode`/CBO/CNES.
Custo: mais alto (model de catálogo + FK + signal de proteção de deleção cross-schema +
comando de import), sem benefício real aqui — não há reimport periódico desses valores, são
≤30 linhas fixas por tabela. **Não recomendado**: over-engineering para o tamanho do
problema, e contraria o próprio critério que justifica o padrão de catálogo em outros
lugares do repo (vocabulário externo grande e versionado).

**Alternativa 3 — `IntegerField`/`CharField` livre validado só na serialização.** Mais
rápido de escrever, mas perde a auto-documentação do `TextChoices.choices` no admin/DRF e
convida a valores inválidos entrarem por fora da API. **Não recomendado.**

Rótulos: os `xs:enumeration` do XSD **não carregam `xs:documentation`** — só os códigos.
Os rótulos em português usados nos exemplos deste documento (ex.: "Eletivo"/"Urgência" para
`dm_caraterAtendimento`) vêm do precedente `AihAutorizacao` (SUS), que é uma tabela
correlata mas **não idêntica** (códigos `'01'/'02'` no SUS vs `'1'/'2'` na ANS/TISS — mesma
semântica, formato diferente). Para as tabelas sem precedente no repo (`tipoInternacao`,
`regimeInternacao`, `tipoFaturamento`, `tipoAtendimento`, `regimeAtendimento`,
`motivoEncerramento`), os rótulos exatos devem ser conferidos no manual de tabelas de
domínio da ANS antes de escrever `verbose_name`/copy de UI — **não fabricar rótulo clínico
ou financeiro sem a fonte primária**, é exatamente o tipo de erro que os comentários do
repo (`import_tuss.py`, `inpatient_models.py`) tratam como linha vermelha.

### Onde cada campo mora

- **`caraterAtendimento` (internação)**: novo campo em `emr.Admission` (mesmo módulo de
  `AdmissionSource`/`Disposition`) — é dado clínico-administrativo capturado na admissão,
  não no momento de gerar a guia. Cruza a fronteira `billing`→`emr` já existente via
  sinal primitivo (`emr/services/adt_signals.py`) se o billing precisar ler; ou simplesmente
  lido direto (mesma-schema FK já existe via `TISSGuide.admission`, sem violar
  `.importlinter` porque é leitura de atributo em model já FK'd, não import de módulo).
- **`caraterAtendimento` (SADT)**: `TISSGuide` não tem uma "admissão" equivalente para
  ambulatório — precisa de campo próprio em `TISSGuide` (ou em `Encounter`, se o Capitão
  decidir que é dado clínico do atendimento e não do faturamento — ver trade-off (b) do
  resumo executivo).
- **`tipoInternacao`/`regimeInternacao`**: `emr.Admission` — mesma lógica, são atributos da
  internação, não da guia (a guia é derivada, `generate_internacao_guide_for_admission` já lê
  `admission.*` para outros campos). **`tipoFaturamento` NÃO** — ver a correção na linha
  correspondente do §3: ele é atributo do DOCUMENTO (a mesma internação pode render uma guia
  parcial e uma final, e é `tipoFaturamento` que as distingue), então mora em `TISSGuide`.
  Este parágrafo foi escrito antes da medição do XSD que trouxe os quatro campos de período
  de faturamento à luz.
- **`motivoEncerramento`**: **não** sobrescrever `Admission.disposition` (a UI de alta já
  usa esses 6 valores, mudar quebra o fluxo clínico existente). Adicionar um campo TISS-
  specific separado (`Admission.disposition_ans_code` ou similar) preenchido **junto** com
  `disposition` na mesma tela (`DischargeModal.tsx`) — um segundo `<select>`, não
  substituição.
- **`profissionalSolicitante` (SADT)**: novo FK em `TISSGuide` para `emr.Professional`
  (mesma-schema, nome sugerido `solicitante`, mirror de `executor`), nullable. Resolvido
  automaticamente de `lab_order.requested_by.professional` quando a guia nasce de um pedido
  de exame; capturado manualmente quando não.
- **`reducaoAcrescimo`**: `TISSGuideItem.reduction_increase_factor`, `DecimalField(max_digits=3, decimal_places=2)`, default **`1.00`** (o NEUTRO — ver a correção no §2; `0` estava errado).

### Migrations e ordem

1. `apps/billing`: `reducaoAcrescimo` em `TISSGuideItem` (independente, sem dependência de
   outra fatia — pode ir primeiro ou em paralelo).
2. `apps/billing`: `solicitante` FK em `TISSGuide` (+ eventual `caráter_atendimento`,
   `tipo_atendimento`, `regime_atendimento` se ficarem em `TISSGuide` por decisão (b)).
3. `apps/emr`: `caráter_atendimento`, `tipo_internacao`, `regime_internacao`,
   `tipo_faturamento`, `disposition_ans_code` em `Admission` — **depois** da decisão (b),
   porque muda o ponto de entrada de dado (tela de admissão vs. tela de faturamento).
4. Nenhuma migration de `ct_guiaValorTotal` até a Fatia 4 ser aprovada (Alternativa A não
   precisa de migration nenhuma).

`apps/billing` está com as migrations **squashadas** (`0001_initial.py` até B9, só 3
arquivos no diretório hoje) — as próximas migrations desta onda continuam a partir de
`0004_*`. `apps/emr` não está squashado (`0067_*` é a última) — continua normalmente.

## 6. Impacto na UI — quem preenche o quê, em qual tela

| Campo | Tela | Componente | Situação hoje |
|---|---|---|---|
| `Admission.admission_source` | Admitir paciente | `frontend/components/inpatient/AdmitPatientModal.tsx` | já existe (`ADMISSION_SOURCE_OPTIONS`) — **modelo a seguir** para os campos novos de internação |
| `caraterAtendimento`/`tipoInternacao`/`regimeInternacao`/`tipoFaturamento` (internação) | Admitir paciente | mesmo `AdmitPatientModal.tsx` | **novo** — adicionar 3-4 `<select>` ao lado de "Origem da internação", mesmo padrão de opções estáticas locais (`admission-types.ts`) |
| `Admission.disposition` | Dar alta | `frontend/components/inpatient/DischargeModal.tsx` | já existe (`DISPOSITION_OPTIONS`) |
| `motivoEncerramento` ANS (`disposition_ans_code`) | Dar alta | mesmo `DischargeModal.tsx` | **novo** — segundo `<select>` ao lado do desfecho clínico, não substitui |
| `dadosSolicitante.profissionalSolicitante` (SADT) | (a) automático quando a guia vem de `LabOrder`/`SurgicalCase` — nenhuma tela nova; (b) **criação manual de guia SADT** — `frontend/app/(dashboard)/billing/guides/new/page.tsx` (`guide_type` select oferece `sadt`/`consulta`; **não** oferece `internacao` — internação só nasce pela ponte automática `generate_internacao_guide_for_admission`) | **confirmado**: esse formulário existe, tem `provider`/`encounter`/`carteirinha`/`competência`/itens TUSS, mas **nenhum campo de profissional solicitante hoje**. Precisa de um `RemoteCombobox` de profissional (mesmo componente do `AdmitPatientModal.tsx`) adicionado a este form quando `guide_type === 'sadt'`. |
| `caraterAtendimento` (SADT, quando não vem de `SurgicalCase`) | mesmo form `billing/guides/new/page.tsx` | idem | mesmo form — adicionar `<select>` de caráter de atendimento ao lado de "Tipo de guia" |

**Não repetir o erro do B6** (model + serviço + 357 linhas de teste, zero endpoint):
qualquer campo novo em `Admission` só entra no plano de uma fatia se a tela que o preenche
(`AdmitPatientModal.tsx` / `DischargeModal.tsx`) for tocada **no mesmo PR**. Os campos de
`TISSGuide` (`solicitante`, `reducaoAcrescimo`) têm caminho de preenchimento automático via
as pontes já existentes (`lab_order`, `surgical_case`, `admission`) — esses são mais seguros
de fazer sem tela nova primeiro, precisamente porque já têm produtor de dado automático.

## 7. Sequenciamento em fatias verificáveis

Cada fatia termina com `pytest apps/billing/tests/test_xml_engine.py -k Sadt` ou `-k
Internacao` rodado de verdade — o critério de "pronto" é o texto exato que sobra em
`schema.error_log`, não uma lista escrita de antemão. Isso é o que a Onda 2 ensinou: medir,
não estimar.

**Fatia 0 — Reescrever a forma dos templates SADT/internação (sem migration).**
Portar `ct_guiaCabecalho`/`ct_beneficiarioDados`/`contratadoExecutante`/
`profissionalExecutante` de `consulta_guide.xml.j2` para `sadt_guide.xml.j2` e
`internacao_guide.xml.j2`. Mesmos filtros Jinja já existentes (`conselho_ans_code`,
`uf_ibge_code`). Zero model novo. **Agente: `dev-pleno` (só template + o teste rodando de
novo para atualizar a lista real de erros que sobra).**

**Fatia 1 — `reducaoAcrescimo` em `TISSGuideItem`.**
Migration trivial, default `0`. Independente das outras fatias, pode entrar em paralelo.
**Agente: `dev-pleno`.**

**Fatia 2 — `caraterAtendimento` + solicitante (SADT).**
FK `TISSGuide.solicitante` (mirror de `executor`), resolução automática de
`lab_order.requested_by.professional`, campo manual no form `guides/new`. Campo
`carater_atendimento` em `TISSGuide` (`TextChoices`, 2 valores). Depende da decisão (b) do
resumo executivo. **Agente: `dev-pleno`, com decisão de produto do Capitão batida antes de
começar.**

**Fatia 3 — Taxonomias de internação em `Admission`.**
`carater_atendimento`, `tipo_internacao`, `regime_internacao`, `tipo_faturamento`,
`disposition_ans_code`, todos `TextChoices`. UI em `AdmitPatientModal.tsx` (4 selects) e
`DischargeModal.tsx` (1 select adicional). Maior fatia de produto: rótulos exigem conferência
no manual ANS antes de ir para tela. **Agentes: engenheiro (este skill) só se houver
ambiguidade nova de modelagem; execução é `dev-pleno` + frontend; `revisor` no PR;
verificação final com `/qa` (gstack) na tela de admissão/alta.**

**Fatia 4 — `numeroGuiaSolicitacaoInternacao` + regra de `senha` obrigatória na internação.**
Pequena: autorreferência ao `guide_number` (decisão de produto simples, baixo risco) +
validação de negócio bloqueando geração de guia de internação sem `authorization_number`
preenchido. **Agente: `dev-pleno`.**

**Fatia 5 — `ct_guiaValorTotal`, Alternativa A (total único).** ✅ **LANDED** (junto com
`dadosInternacao`/`dadosSaidaInternacao`). `valorTotalGeral = guide.total_value`, sem
breakdown, zero migration. O `xfail` de `InternacaoGuideXMLConformanceTests` CAIU:
`validate_xml` devolve `[]` para a guia de resumo de internação.
**Ressalva que precisa sobreviver a este check verde**: `procedimentosExecutados` é
`minOccurs="0"` e NÃO é emitido — `ct_procedimentoExecutadoInt` exige `reducaoAcrescimo`
(Fatia 1, não landed) e `dataExecucao` por item, e `TISSGuideItem` não tem nenhum dos dois.
Ou seja, a guia sai XSD-válida com o total geral e SEM nenhuma linha de procedimento e sem
breakdown. Schema-válido ≠ aceite: internação sem discriminação de itens é candidata natural
a glosa. Fatia 1 + Alternativa B (§4) continuam abertas.

**Fatia 6 (condicional) — `ct_guiaValorTotal`, Alternativa B (breakdown real).**
Só se o Capitão decidir que a Alternativa A não basta. Primeiro passo obrigatório: medir a
correspondência `table_number`/`group` real contra o catálogo TUSS importado (não supor).
Maior fatia do documento — reabre a pergunta de proveniência `DailyCharge`/`InpatientFee`
em `TISSGuideItem`. **Agente: este skill de novo para desenhar a modelagem específica antes
de qualquer código, dado o tamanho da decisão.**

## 8. Riscos e o que NÃO fazer

- **Não** criar `TerminologyCatalog` para as domain tables pequenas — over-engineering, ver
  §5.
- **Não** fabricar rótulos em português para os códigos ANS sem checar o manual — o XSD não
  documenta, e um rótulo errado em tela de faturamento hospitalar é pior que campo vazio.
- **Não** sobrescrever `Admission.disposition` com a taxonomia ANS — são públicos distintos
  (equipe clínica vs. faturamento), a tela de alta já depende do vocabulário atual.
- **Não** shippar campo novo em `Admission` sem tocar a tela no mesmo PR — é o erro
  explícito do B6 que este documento foi instruído a não repetir, e agora tem tela e
  componente identificados, então não há desculpa de "não sei onde entra".
- **Não** tratar `ct_guiaValorTotal` como "só mais um campo" — é o item que mais mexe em
  faturamento já existente e o único desta lista com risco real de dado retroativo perdido
  (proveniência `DailyCharge`/`InpatientFee` já fundida em `TISSGuideItem`).
- **Risco aberto**: não confirmei os rótulos nem a correspondência completa
  `dm_tabela`→categoria financeira contra uma fonte primária ANS — isso é medição
  pendente, não suposição resolvida. Quem pegar a Fatia 3 ou a Fatia 6 precisa fazer essa
  checagem antes de escrever `verbose_name`/UI copy.
- **Risco aberto**: não localizei nenhum teste ou tela que exercite `tipoFaturamento` como
  ciclo de vida real (parcial → final) — o Vitali hoje só gera a guia de internação na alta
  (`generate_internacao_guide_for_admission` é chamado uma vez, no fim da estada). Se o
  produto quiser faturamento parcial durante a internação, isso é uma mudança de fluxo bem
  maior que um campo — vale confirmar antes de assumir "default fixo" na Fatia 3.

## 9. Estimativa honesta de tamanho

| Fatia | Tamanho | Decisão de produto necessária? |
|---|---|---|
| 0 — templates | Pequena (1-2 arquivos, sem migration) | Não |
| 1 — `reducaoAcrescimo` | Pequena (1 migration, 1 campo) | Não |
| 2 — solicitante SADT | Média (1 migration + 1 tela) | Sim — (b) do resumo |
| 3 — taxonomias internação | Grande (2 migrations, 2 telas, rótulos a confirmar) | Sim — rótulos ANS + escopo de `tipoFaturamento` |
| 4 — `numeroGuiaSolicitacaoInternacao` + senha | Pequena | Sim, mas simples (autorreferência) |
| 5 — `ct_guiaValorTotal` A | Muito pequena (sem migration) | Sim — (c) do resumo, mas decisão binária rápida |
| 6 — `ct_guiaValorTotal` B | Grande, tamanho não fechado até medir `table_number` real | Sim, a mais cara do documento |

## 10. Apêndice — árvore completa dos XSDs investigados

A extração recursiva completa de `ctm_sp-sadtGuia` e `ctm_internacaoResumoGuia` (elemento,
tipo, `minOccurs`/`maxOccurs`, e o enum fechado de cada `simpleType` folha) foi gerada por
script e está preservada em
`/tmp/claude-1000/-home-rcosta00-dev-vitali/3d7e2f98-ac29-4e2e-bca4-a6abf0dcf788/scratchpad/sadt_dump.txt`
(scratchpad da sessão — não versionado; reproduzir com o mesmo script `lxml` contra
`backend/apps/billing/schemas/tissGuiasV4_01_00.xsd` se precisar de novo, já que o arquivo é
efêmero). As tabelas §2 e §3 acima são a leitura orientada a produto dessa árvore; a árvore
crua é útil para conferir minOccurs/maxOccurs exatos ao implementar.



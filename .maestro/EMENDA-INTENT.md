# Emenda ao INTENT v5 → v6: registro

> **Status: APROVADA pelo Capitão em 25/09/2026 e APLICADA.** A direção vigente é o
> **INTENT v6** (`.maestro/INTENT.md`). Este arquivo não é direção: é o registro de **por que**
> a v6 mudou o que mudou, com a fonte de cada mudança. Se ele divergir do INTENT, vale o
> INTENT.
>
> **O aval:** o Capitão aprovou a emenda em 25/09/2026 com a recomendação do Imediato: **a
> receita sai do posto 2 e vira guarda permanente, "a receita não regride", e o isolamento
> entre tenants continua em 1.** O `maestro intent --bump` para a v6 rodou por ordem do
> Imediato, transmitindo esse aval, no branch do PR #228.
>
> **O que o aval mudou em relação ao rascunho:** o rascunho propunha manter a receita no
> posto 2, reescrita como guarda. Na versão aprovada, a receita **sai das prioridades** e vai
> para §Limites como guarda permanente. As prioridades seguintes sobem uma posição:
> Recuperação passa de 3 para 2, Interceptação de 4 para 3 e Compliance de 5 para 4. Ordens
> carimbadas até a v5 continuam citando a numeração antiga.
>
> Rascunho redigido em 25/09/2026, na retomada depois da PARADA de 18/09, contra o estado de `onda0`
> em `1670a07` (ordens 005 a 021 aceitas).

## Por que emendar agora

O INTENT v5 foi carimbado em 12/09. Depois disso, quinze ordens (007 a 021) mudaram o estado
do produto, e três trechos da direção ficaram falsos ou incompletos:

1. **A Prioridade 2 descreve um problema que já foi resolvido.** Ela manda destravar a
   receita e aponta dois bloqueadores de catálogo (CBHPM em zero, LOINC com 6 linhas). As
   ordens 006 a 010 fecharam a cadeia de receita, e os dois catálogos estão carregados em
   staging. Uma ordem que cite a §Prioridade 2 hoje estaria citando uma pendência que não
   existe mais.
2. **A série de auditoria (016 a 021) não aparece na direção.** Ela criou regras que
   decidem ordem futura: a cobertura se mede pelo roteador, a trilha cobre a rota e não a
   classe, e a trilha fica guardada por 20 anos. Essa última é **decisão do Capitão** (22/09),
   e hoje só está no ADR-0001.
3. **A regra de que a forge não roda compose do Vitali** (Imediato, 17/09) não está em
   lugar nenhum da direção. É restrição de execução que toda ordem precisa respeitar, e as
   ordens a repetem uma a uma.

Nada abaixo inventa direção nova. Cada mudança transcreve uma decisão já tomada ou um estado
já medido, e cita a fonte.

---

## Mudança 1: a receita sai das prioridades e vira guarda permanente em §Limites

**Fonte:** ordens 006, 007, 008, 009 e 010 (cadeia de receita); ordem 013 (CBHPM); recibo
`loinc-2-83` no ledger (LOINC); `docs/research/VITALI_CATALOGOS_ESTADO_REAL.md`.

**O que foi medido:**

* A cadeia guia TISS válida → guia declarada pronta → lote → fechamento percorre o caminho
  real (`services/batch_lifecycle`), e o faturamento fica gravado em `billing_tissbatch`.
  Ciclo de vida da guia: `draft → pending → submitted`. Declarar a guia pronta e enviá-la
  são atos auditados. Lote com rascunho não fecha (409 `batch_has_draft_guides`), e o
  `submit` recusa rascunho (400 `guide_not_ready`, ordem 010, issue #213).
* Guia gerada automaticamente por evento clínico (`from_lab_order`, `from_admission`,
  `bill_surgical_materials`) nasce `draft`, travada por teste: ninguém a conferiu.
* LOINC 2.83: 112.405 linhas em staging. CBHPM 2022: 4.881 procedimentos em staging, com o
  porte gravado como **classe publicada** e `valor() = 0` enquanto não houver contrato.

**Texto atual (v5, §Prioridades, item 2):**

> **Receita destravada antes de escopo novo.** O caminho guia TISS válida → lote →
> faturamento tem precedência sobre qualquer módulo adicional. Os catálogos públicos
> **estão carregados** em staging desde 04/08 [...] Dois bloqueadores sobram [...]:
> **CBHPM está em zero e é catálogo licenciado** [...] e **LOINC tem 6 linhas** [...]

**Texto do rascunho (v6, §Prioridades, item 2; substituído pelo aval, ver abaixo):**

> 2. **A receita não regride.** A cadeia guia TISS válida → guia declarada pronta → lote →
>    fechamento está provada pelo caminho real desde 13/09 (ordens 006 a 010). Daqui em
>    diante, a prioridade é mantê-la de pé: mudança que toque guia, lote, glosa ou catálogo
>    de faturamento prova que a cadeia continua fechando (`verify_revenue_chain`), e guia
>    derivada de evento clínico continua nascendo rascunho. Os catálogos que faltavam estão
>    em staging (LOINC 2.83 e CBHPM 2022), carregados **por mão humana e com recibo**. Todo
>    ambiente novo ainda nasce vazio, e a carga ainda não é reproduzível a partir do
>    repositório. **A CBHPM classifica, não precifica**: `porte` é classe publicada, e o
>    valor só vem de tabela contratada. Quem encontrar `valor() = 0` pergunta qual contrato
>    vale, e não "conserta" o número.

**Decisão do Capitão (25/09):** a receita **sai do posto 2**. Nenhum item novo entra no lugar:
as prioridades seguintes sobem. O texto acima foi para §Limites como o primeiro item, com o
rótulo **"Guarda permanente: a receita não regride"**, e absorveu a regra de licença abaixo.
O texto exato está no INTENT v6.

**Pendência de licença, que continua do Capitão:** a CBHPM é © Editora Manole / AMB. O
Imediato autorizou importar em staging, mas não cobrar pelo uso. A emenda só registra o
limite, que já existe:

> (acréscimo a §Limites) **CBHPM: importada, não comercializada.** Cobrar por ela depende de
> decisão de licença do Capitão.

---

## Mudança 2: a série de auditoria entra na prioridade de compliance (5 na v5, 4 na v6), com a retenção de 20 anos

**Fonte:** ordens 016, 017, 018, 019, 020 e 021; `docs/adr/ADR-0001-retencao-auditoria-20-anos.md`;
decisão do Capitão na Ponte (`01M325GP8W497HQWJ3GY55JPP9`, escolha `vinte_anos`, 22/09).

**O que foi medido:**

* Toda rota `GET` que lê dado de paciente ou dado pessoal sensível deixa trilha, ou está
  isenta com motivo escrito no código. Guarda final: 154 views, 74 exigem trilha, 321 rotas
  `GET`, **0 sem cobertura**. A cobertura se mede pelo **roteador do Django**
  (`apps/core/audit_coverage.py`), nunca por `grep`.
* Em quatro ordens seguidas, três vezes o defeito estava no **instrumento de medição**, e
  não no código medido. Cada um virou guarda com teste: enumeração pelo roteador, profundidade
  de travessia que não pode esconder view, rota em vez de classe, e o teste de MRO
  (`AuditReadMixin` tem de ser a primeira base).
* `core_auditlog` virou particionada por mês e por tenant (020). O expurgo exige recibo de
  exportação fria verificado, e **não existe caminho de código que apague sem ele**.
* Retenção de **20 anos (240 meses)** por tenant, com expurgo **desligado de fábrica** (021).
  A 021 também descobriu que a 020 havia entregue o mecanismo sem ninguém chamá-lo, e o
  consertou: a partição agora nasce no deploy e no Beat diário.

**Texto atual (v5, §Prioridades, item 5):**

> 5. **Compliance como gate, não como sprint futura.** LGPD, TISS/TUSS (RN 501/2022 ANS), CFM
>    1.821/2007 e ANVISA são critério de aceite, não item de backlog.

**Texto proposto (v6, §Prioridades, item 5):**

> 5. **Compliance como gate, não como sprint futura.** LGPD, TISS/TUSS (RN 501/2022 ANS), CFM
>    1.821/2007 e ANVISA são critério de aceite, não item de backlog. Isso vale em concreto
>    para a trilha de auditoria:
>    * **Leitura de dado de paciente ou de dado pessoal sensível deixa trilha, por rota.**
>      View nova que lê esse dado entra coberta ou isenta com motivo escrito. A guarda
>      (`audit_coverage`) reprova o resto. A cobertura se mede pelo roteador, nunca por
>      contagem de texto.
>    * **A trilha é guardada por 20 anos** (240 meses), igual ao prontuário: Res. CFM
>      1.821/2007, art. 8, e Lei 13.787/2018, art. 6. Decisão do Capitão em 22/09/2026,
>      registrada no ADR-0001. O prazo é configurável por tenant, e o **expurgo nasce
>      desligado**: ligar é ato deliberado por clínica, visível no banco.
>    * **Nada da trilha se apaga sem exportação fria provada.** O `DROP` de partição exige
>      recibo verificado, e o formato exportado é estável (texto delimitado ou JSONL, nunca
>      dump binário), porque precisa abrir daqui a vinte anos.
>    * **Aceite de mecanismo exige prova no caminho real, não na fixture.** Teste que
>      constrói à mão a condição que o sistema nunca produz mede a si mesmo (lição da 021).

**O que a emenda não decide, e fica registrado para ninguém tratar como esquecido:**

* O destino frio S3 Glacier (São Paulo, Object Lock em modo compliance) foi decidido pelo
  Capitão, mas não está construído. Existe só `LocalDiskColdStorageBackend`. É ordem
  própria, e depende de autorização do Imediato para `boto3` e MinIO na lab.
* A sorologia de doador de sangue (`BloodDonor`, `BloodBagSerology`) fica fora do grafo de
  `Patient` e por isso é invisível à guarda. Está na fila como ordem própria.

---

## Mudança 3: a regra da forge entra em §Limites

**Fonte:** regra do Imediato em 17/09/2026, depois do incidente em que o compose de
`master`, subido na forge para rodar a suíte, publicou redis **sem senha**, postgres e django
em `0.0.0.0` na LAN por 1h46. O firewall da forge não protegia, porque porta publicada por
Docker passa pelo hook `forward` e não pelo `input`. A forge guarda a passphrase da cripta
do NetForge, o e-CPF A1 do Capitão e a credencial do túnel Cloudflare.

**Texto proposto (v6, §Limites, item novo depois de "Orçamento de infra"):**

> - **A forge não roda compose do Vitali.** Nem para rodar a suíte, nem "só um minuto".
>   Teste roda no CI ou na lab. Ordem que precisa de banco usa contêiner efêmero sem porta
>   publicada, ou prova pelo CI. A forge guarda segredo que não é do Vitali, e porta
>   publicada por Docker passa por fora do firewall dela. Regra do Imediato, 17/09/2026.

---

## Cabeçalho (v6)

Texto do rascunho, que o INTENT v6 aplicou já ajustado ao aval (receita em §Limites e renumeração):

> Histórico: v1 redigida em 11/09; v2 carimbada no mesmo dia; v3 corrigiu a Prioridade 2, que
> afirmava um fato falso sobre os catálogos; v4 corrigiu a nota de status da própria direção;
> v5 (12/09) pôs o offsite fora de escopo até a produção (ordem 004); **v6 marcou a Prioridade 2 como cumprida (ordens 006 a 010), levou a série de
> auditoria e a retenção de 20 anos para a Prioridade 5 (ordens 016 a 021, ADR-0001) e pôs a
> regra da forge em §Limites.**

(v4 e v5 vêm do `git log` de `.maestro/INTENT.md`: `aa6636b` e `0e76f50`. O cabeçalho da v5 parou de contar o histórico na v3.)

## O que não muda

Problema, Público, Resultado, a Prioridade 1 (isolamento entre tenants) e §Fora de escopo
continuam com o texto da v5. Recuperação e Interceptação mantêm o texto e só mudam de número.
A ordem 004 (offsite) continua adiada por decisão do Capitão em 12/09, e o texto da v5 sobre
ela segue correto.

## Como foi carimbado

1. Os textos, já ajustados ao aval, foram aplicados em `.maestro/INTENT.md`.
2. `maestro intent --bump`: v5 → v6.
3. Este arquivo **fica** no repositório como registro da emenda, com status de aprovada.
   Ele não concorre com o INTENT, porque declara na primeira linha que a direção é a v6.

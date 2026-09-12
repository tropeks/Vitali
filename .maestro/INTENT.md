<!-- maestro-intent v1
version: 5
ts: 2026-09-12T10:25:25-03:00
head: 5b7ff005cfa84e7b1506e71d336b1dce59e44a07
author_session: desconhecido
hash: a6120b3c
-->
# Direção — vitali

> Redigida a partir de `README.md`, `docs/PROJECT_BRIEF.md`, `docs/VISION-AI-NATIVE.md`,
> `docs/AI-NATIVE-WEDGES.md` e `CLAUDE.md`, e corrigida contra o que foi medido no banco.
> Reduzida ao que decide uma ordem. **Carimbada pelo Capitão** — `maestro intent --bump` é
> dele, não do executor. Histórico: v1 redigida em 11/09; v2 carimbada no mesmo dia; v3
> corrigiu a Prioridade 2, que afirmava um fato falso sobre os catálogos.

## Problema

Clínica e hospital particular de pequeno e médio porte (10–200 leitos) estão presos entre
três opções ruins: os big-players (Tasy, MV, TOTVS Saúde) custam R$50–200k/mês de licença;
o open-source (OpenEMR, Bahmni) é grátis mas cru — exige time técnico dedicado, tem UX
deficiente e nenhuma compliance brasileira pronta; e as soluções locais menores são
limitadas, sem IA, sem interoperabilidade e com lock-in dos dados.

O resultado prático é o que o Vitali ataca: planilha, sistema fragmentado, faturamento TISS
manual que gera glosa, e zero inteligência sobre o próprio dado. E, mais fundo, um sistema
que só **registra** o que já aconteceu — anota a dose errada, anota a guia que vai ser
glosada, anota a ruptura de estoque — em vez de interceptar o erro antes que ele alcance o
paciente, o caixa ou a prateleira.

## Público

**Primário:** clínicas e hospitais particulares brasileiros de 10–200 leitos que atendem
convênio + particular. O Brasil é o mercado inicial porque a compliance é a barreira —
TISS/TUSS e LGPD são o fosso, não um detalhe de implementação.

**Secundário (expansão):** mercados emergentes com o mesmo dilema (LATAM, África, Sudeste
Asiático) e clínicas especializadas (oftalmologia, ortopedia, dermatologia).

Quem usa, e a dor que decide a feature: **administrador/dono** (glosa e cegueira
financeira), **médico** (burocracia e risco de erro), **recepcionista** (agenda caótica e
no-show), **farmacêutico** (estoque no braço), **paciente** (não consegue marcar).

## Resultado

Tudo que os big-players oferecem, a um preço que cabe no orçamento de um hospital menor,
com IA como diferencial real — não um "Tasy mais barato", um "Tasy mais inteligente e
acessível".

O alvo é verificável, não retórico: 1–3 clínicas piloto operando sem downtime crítico;
depois 10+ clínicas pagantes com redução medida de glosa (meta −30%) e NPS > 8 entre os
usuários clínicos; em 12 meses, BI e DICOM/PACS operacionais, segundo mercado aberto e
break-even.

Toda funcionalidade de IA segue o mesmo padrão — **Observe → Preveja → Intercepte →
Aprenda** — com motor determinístico autoritativo (o LLM só explica), alerta persistente,
flag por tenant desligada por padrão e flywheel de `AuditLog` (alerta → override →
desfecho).

## Prioridades

1. **Isolamento entre tenants antes de qualquer feature.** Schema-per-tenant é o produto,
   não a infra: um vazamento entre clínicas encerra o negócio. Mudança em auth, tenant,
   permissão ou migration passa por especialista e teste — é o que o `.maestro.yaml` já
   declara.
2. **Receita destravada antes de escopo novo.** O caminho guia TISS válida → lote →
   faturamento tem precedência sobre qualquer módulo adicional. Os catálogos públicos
   **estão carregados** em staging desde 04/08 — CID-10, TUSS, CNES, ANVISA, SIGTAP, CBO,
   CID-O e UCUM, com fonte e versão gravadas em `TerminologyImportLog` — mas **por mão
   humana, nunca por pipeline**: todo ambiente novo nasce vazio e a carga não é reproduzível
   a partir do repositório. Dois bloqueadores sobram, e são de natureza diferente:
   **CBHPM está em zero e é catálogo licenciado** (decisão de compra, não de engenharia), e
   **LOINC tem 6 linhas**, travado por cadastro gratuito
   (`docs/research/VITALI_CATALOGOS_ESTADO_REAL.md`).
3. **Recuperação provada, não documentada.** Backup que nunca foi restaurado não é backup.
   O drill (`scripts/restore_test.sh`) vale mais que mais um alerta.
4. **Interceptação sobre registro.** Entre melhorar um CRUD e fechar uma cunha de
   interceptação (dose, glosa, ruptura), a cunha ganha — é a tese do produto.
5. **Compliance como gate, não como sprint futura.** LGPD, TISS/TUSS (RN 501/2022 ANS), CFM
   1.821/2007 e ANVISA são critério de aceite, não item de backlog.

## Limites

- **Solo dev + IA.** Alavancagem máxima de open-source e framework opinado; o que não é
  automatizável não escala.
- **Orçamento de infra ~R$150–500/mês.** VPS e serviço self-hosted. Container desde o dia 1
  porque a portabilidade (VPS → nuvem) é obrigatória — nada pode depender do host.
- **Schema-per-tenant no PostgreSQL.** Não é escolha de performance, é exigência de LGPD.
- **Feature flag por tenant + billing modular desde a fundação.** O modelo de negócio é
  marketplace de módulos; qualquer feature nasce ligável e desligável por cliente.
- **Nenhum número clínico, contratual ou ANS inventado em código.** Dado de dose, contrato e
  terminologia entra por importação validada ou por humano qualificado — nunca por
  hardcode. Flag de IA nasce **OFF** e não processa dado de saúde sem DPA assinado
  (`AIDPAStatus`, verificado em runtime).
- **i18n é scaffolding, não entrega.** Hoje só pt-BR é servido (`docs/I18N.md`).
- **Sinal verde tem que significar verde.** Healthcheck, CI e alerta que vivem vermelhos
  ensinam a equipe a ignorar vermelho — e aí o vermelho real passa batido.
- **Backup: staging tem cifrado diário local + drill provado; offsite só a partir da
  produção, e em nuvem.** A lab é ambiente de teste — perda de dado ali não é catástrofe, e
  proteger contra ela custa mais atenção do que vale. Dentro da Vulcan não existe offsite de
  verdade: a R640 e o host VMware estão no mesmo rack (confirmado 12/09), então qualquer
  cópia entre nós protege contra perda de VM, nunca contra perda de sítio. O nível de
  proteção acompanha o que o dado vale, e hoje ele vale dado de teste.

## Fora de escopo

- Ser um EMR genérico global agora: FHIR é o padrão-alvo de interoperabilidade, mas a
  entrega é Brasil-first e o catálogo de tradução só se popula na Fase 3.
- Self-service completo de ativação de módulo: o piloto é serviço gerenciado — a equipe
  Vitali ativa módulo por API (`docs/PLAN_SPRINT11.md`).
- Visão analítica cruzando tenants (super-view admin entre clínicas): contraria o
  isolamento que é a razão do schema-per-tenant.
- Token A3 em hardware (PKCS#11) na assinatura digital: o fluxo espera A1 PKCS#12
  (`docs/ICP_BRASIL.md`).
- Substituir o julgamento clínico: toda cunha de IA é soft-stop com override auditado — o
  sistema intercepta e explica, quem decide é o profissional.
- Migrar para AWS/ECS neste horizonte: é destino declarado da arquitetura, não trabalho
  desta direção. Hoje o alvo de execução é Docker Compose na Vulcan.
- **Backup fora do host enquanto o Vitali não for produto.** O preparo existe e está no
  repo (`docs/BACKUPS.md` §Offsite, `backup.sh` parametrizado, `--from-s3` no drill),
  desligado e pronto: ligar é preencher cinco variáveis. É trabalho guardado para o dia da
  produção — não é dívida, e quem encontrar a seção não deve tratá-la como pendência
  esquecida. Ordem 004, encerrada como NÃO AGORA por decisão do Capitão em 12/09.

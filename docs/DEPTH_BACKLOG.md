# DEPTH BACKLOG — "onde cavar fundação maior"

> Auto-auditoria honesta 2026-07-27. Os núcleos dos épicos M3 (SAE/BCMA, ADT, Centro Cirúrgico) estão sólidos em
> **modelo/API/RBAC/serviços atômicos/append-only** e verificados funcionalmente — mas ~70% de profundidade vs enterprise
> (Tasy). Esta é a lista rankeada da "segunda metade" que separa *core funcional* de *profundo como se deve*. Revisitar
> quando o Romulo mandar cavar. NÃO é dívida de bug — é dívida de PROFUNDIDADE/escopo.

## P0 — Ponte clínico→financeiro (o elo que falta em TUDO)
- **Internação não gera diárias/taxas**: uma `Admission` ativa deveria emitir cobrança diária (diária de leito, taxa de
  unidade) → billing. Hoje o dado de estada morre sem virar receita.
- **Cirurgia não emite guia**: `SurgicalCase`/`SurgicalProcedure` (TUSS) deveriam gerar guia **TISS** (convênio) ou
  **BPA/APAC** (SUS). Procedimento executado ≠ faturado.
- **OPME/material não vira custo/glosa**: consumo de sala sem vínculo a faturamento.
- É *o* diferencial "bidirecionalidade" — sem isso, os módulos clínicos são ilhas.

## P1 — Catálogos são AMOSTRA, não conteúdo
- NANDA/NIC/NOC/TUSS/BedType semeados com 3–5 itens (taxonomia licenciada). Infra real, conteúdo simbólico. Produção
  exige import da taxonomia completa (licença + pipeline de import já existe — falta o conteúdo).

## P1 — Centro Cirúrgico: enforcement + peças que faltam
- **Checklist OMS não é enforcado** (é artefato registrado, cirurgia avança sem ele). "Cirurgia segura" de verdade =
  time-out obrigatório antes da incisão (travar `record_time(incisao)` sem sign-in/time-out confirmados).
- **Sem registro anestésico** (só `porte_anestesico` do catálogo CBHPM; falta ficha anestésica real).
- **OPME/materiais** (C6 — em andamento) + rastreabilidade de consumo (`StockMovement`→`SurgicalCase`).
- Agendamento sem checagem de disponibilidade de **cirurgião/equipe/equipamento** (só anti-double-booking de sala).
- Sem PACU/recuperação pós-anestésica, sem turnover de sala, board só por dia (não por turno).

## P2 — ADT: segunda metade
- **Alta planejada** (discharge planning) inexistente; sem previsão de alta dirigindo o censo.
- **Higienização não fecha o ciclo**: leito vai a `higienizacao` e ninguém devolve a `livre` (falta workflow de
  housekeeping / limpeza concluída).
- **Isolamento/precaução** (`Room` tem flags) não gatilha/valida alocação de leito.
- `Encounter.encounter_type` existe mas o **FHIR `encounter_mapper` não foi religado** pra emitir classe inpatient/emergency
  (o mapper documenta o gap; campo criado, downstream não conectado).
- Censo básico (taxa + LOS instantâneos); sem histórico/tendência de ocupação, sem giro de leito.

## P2 — SAE/BCMA
- Diagnósticos de enfermagem sem CDS (sugestão NANDA por sinais/vitais).
- Evoluções são texto livre; sem vínculo a deterioração/vitais.
- Aprazamento gera grade mas integração com a execução (MAR) é rasa.

## P1 — Operacional: a CI oficial nunca rodou nisso
- Toda a validação desta leva foi **mount-run isolado + smoke headless** (real, mas parcial). A branch
  `agent/professional-settlement` **não foi mergeada** → a suíte completa (2000+ testes), `mypy` full, `lint-imports` e o
  Playwright oficial NÃO rodaram no conjunto integrado. **Antes de declarar "sólido de verdade": merge → CI oficial**
  (ou rodar a suíte completa via mount-run).

## P3 — RBAC/compliance
- Permissões gateiam endpoints, mas sem escopo por unidade/sala nem "médico responsável" enforcado.
- Sem prova de imutabilidade audit-grade além dos append-only; sem conformance SBIS/NGS pros módulos novos.

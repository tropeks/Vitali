# DEPTH BACKLOG — "onde cavar fundação maior"

> Auto-auditoria honesta 2026-07-27, **revisada 2026-08-04**. Os núcleos dos épicos M3 (SAE/BCMA, ADT, Centro
> Cirúrgico) estão sólidos em **modelo/API/RBAC/serviços atômicos/append-only** e verificados funcionalmente. Esta é a
> lista rankeada da "segunda metade" que separa *core funcional* de *profundo como se deve*. NÃO é dívida de bug — é
> dívida de PROFUNDIDADE/escopo.
>
> **Aviso de leitura**: em 2026-08-04 a lista foi conferida contra o código e boa parte do P0/P1 já tinha sido
> construída depois da auditoria original. Os itens entregues estão marcados ✅ com a data, em vez de apagados — um
> backlog que descreve um mundo que não existe mais é pior que backlog nenhum.

## P0 — Ponte clínico→financeiro (o elo que falta em TUDO)
- ✅ **2026-07/08 — Internação gera diárias**: `AccommodationTuss` mapeia tipo de leito → TUSS de diária,
  `accrue_daily_charges` acumula com regra de pernoites, `generate_internacao_guide_for_admission` monta a guia.
  **2026-08-04 (B5)**: fechado o vazamento — a alta acumula antes de liberar o leito (sinal
  `admission_pre_bed_release`, para não violar `emr ↛ billing`) e a task diária `billing.accrue_active_admissions`
  varre as internações ativas em todos os tenants.
- ✅ **2026-07 — Cirurgia emite guia TISS**: `generate_sadt_guide_for_surgical_case`.
- ✅ **2026-07 — OPME/material vira cobrança**: `SurgicalMaterial` → `MaterialPriceItem` →
  `bill_surgical_materials_for_case`, com `GlosaSafetyAlert` quando o material não está em tabela.
- ⬜ **Taxas de internação** (sala, gases medicinais, taxa de unidade): só a diária de leito é cobrada. A tabela TUSS 18
  já está importada inteira (3.595 termos, inclui taxas e gases) — falta o modelo de lançamento.
- ⬜ **Cirurgia → SUS**: `SurgicalProcedure` só tem `tuss_code`, não tem `sigtap`. Uma cirurgia SUS não vira BPA/APAC nem
  procedimento principal de AIH. Ou adicionar o campo, ou fazer a cirurgia materializar `EncounterProcedure` SUS.
- ⬜ **`StockMovement` → billing**: zero acoplamento. Consumo de material fora do centro cirúrgico (enfermaria,
  emergência) e dispensação em internação não têm caminho de cobrança.
- ⬜ **Custo/margem**: billing não calcula custo de aquisição vs. faturado. Só existe P&L isolado em
  `apps/concession/services_pnl.py`.

## P1 — Catálogos são AMOSTRA, não conteúdo
- ✅ **2026-08-04 — Públicos importados de verdade**: CID-10 14.233, CNES 627.706, TUSS 54.139 (tabelas 22/18/20),
  ANVISA 10.276 produtos + 24.346 apresentações com EAN/preço CMED, SIGTAP 5.004, CBO 2.455, CID-O 816, UCUM 316.
  ETLs versionados em `scripts/catalogs/` com fonte e gotchas de cada um.
- ⬜ **LOINC**: bloqueado por **cadastro** (não licença) — `loinc.org` exige conta gratuita. Trava junto as unidades
  UCUM **compostas** (`mg/dL`, `10*3/uL`), que não existem no `ucum-essence.xml` e vêm no "example UCUM units" do LOINC.
- ⬜ **Licenciados sem fonte paga**: NANDA/NIC/NOC, Simpro/Brasíndice, CBHPM seguem simbólicos.
- ⚠️ **Seed planta dado fictício com código real**: `seed_demo_data` cria CNES/UCUM inventados (o CNES 2077469 como
  "Hospital das Clínicas", que na verdade é HOSP DOM ALVARENGA). Ao importar o catálogo real vira duplicata por código.
  As 4 duplicatas foram removidas do staging em 2026-08-04, mas **o seed não foi corrigido** — replanta se rodar.

## P1 — Centro Cirúrgico: enforcement + peças que faltam
- **Checklist OMS não é enforcado** (é artefato registrado, cirurgia avança sem ele). "Cirurgia segura" de verdade =
  time-out obrigatório antes da incisão (travar `record_time(incisao)` sem sign-in/time-out confirmados).
- **Sem registro anestésico** (só `porte_anestesico` do catálogo CBHPM; falta ficha anestésica real).
- **OPME/materiais** (C6 — em andamento) + rastreabilidade de consumo (`StockMovement`→`SurgicalCase`).
- Agendamento sem checagem de disponibilidade de **cirurgião/equipe/equipamento** (só anti-double-booking de sala).
- Sem PACU/recuperação pós-anestésica, sem turnover de sala, board só por dia (não por turno).

## P2 — ADT: segunda metade
- ✅ **2026-08 — Alta planejada**: `plan_discharge` + evento PLAN + board `/admissions/planned/`.
- ✅ **2026-08 — Higienização fecha o ciclo**: `release_from_housekeeping` + `BedStatusEvent` + permissão
  `beds.housekeeping`.
- ✅ **2026-08 — Isolamento gatilha alocação**: `Admission.isolation_precaution` validado contra `Room.isolation` em
  admit/transfer.
- ⬜ `Encounter.encounter_type` existe mas o **FHIR `encounter_mapper` não foi religado** pra emitir classe
  inpatient/emergency (o mapper documenta o gap; campo criado, downstream não conectado).
- ⬜ Censo básico (taxa + LOS instantâneos); sem histórico/tendência de ocupação, sem giro de leito.

## P2 — SAE/BCMA
- Diagnósticos de enfermagem sem CDS (sugestão NANDA por sinais/vitais).
- Evoluções são texto livre; sem vínculo a deterioração/vitais.
- Aprazamento gera grade mas integração com a execução (MAR) é rasa.

## P1 — Operacional: a CI oficial nunca rodou nisso
- ✅ **2026-08 — CI oficial verde e mandando**: suíte completa (3.347 testes), mypy full, lint-imports, Playwright e
  Docker build rodam a cada push em `master`.
- ⚠️ **Ambiente local mente nos DOIS sentidos** (aprendido na marra em 2026-08-04, custou horas):
  - rodar a suíte com `DJANGO_SETTINGS_MODULE=vitali.settings.production` (que é o que o container de dev usa) ativa
    `SECURE_SSL_REDIRECT` e transforma toda chamada de API em 301 → **1331 falhas falsas**. O CI usa
    `settings.development`, que é o default do `pyproject.toml`;
  - `docker run` sem `--security-opt apparmor=unconfined` faz `socket.socketpair()` estourar `PermissionError` e derruba
    os 16 testes de assinatura ICP-Brasil. O `docker-compose.yml` já roda unconfined; um `docker run` manual não herda;
  - `pytest ... | tail -N` devolve o exit code do `tail`, sempre 0 — nunca ler resultado de suíte através de pipe.
  - **Regra**: falha espalhada por módulos que você não tocou é quase sempre ambiente. Conferir `gh run list` antes de
    tratar como regressão.

## P3 — RBAC/compliance
- Permissões gateiam endpoints, mas sem escopo por unidade/sala nem "médico responsável" enforcado.
- Sem prova de imutabilidade audit-grade além dos append-only; sem conformance SBIS/NGS pros módulos novos.

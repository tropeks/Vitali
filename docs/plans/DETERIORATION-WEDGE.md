# Clinical-Deterioration Wedge — Plano (4º wedge AI-native)

> **Tese:** o crown-jewel do "OS clínico que PENSA" ([[VISION-AI-NATIVE]]) —
> **Observe→Predict→Intercept→Learn** nos **sinais vitais**: detectar a deterioração
> (sepse/choque/insuf. respiratória) **antes** da parada, escalando ao time, em vez de
> descobrir no código azul. Padrão idêntico aos 3 wedges, frente = **segurança clínica
> contínua**.

## Distinção crítica vs dose (verdade externa)
- O **NEWS2** (National Early Warning Score 2, Royal College of Physicians 2017) é um
  escore **público, padronizado e validado** — implementá-lo a partir da definição
  oficial (citando a RCP) **não é inventar número clínico**, ao contrário das doses do
  formulário (D-T1). É algoritmo determinístico fixo.
- O que **continua sendo decisão humana** (gate, não código): (a) **ligar a flag**
  `deterioration_safety` = governança clínica do estabelecimento; (b) o **protocolo de
  escalonamento** (quem é chamado em qual banda) — config, não inventar; (c) a **Escala
  SpO2** do NEWS2 (Escala 1 padrão; Escala 2 só p/ pacientes com alvo 88–92%, ex. DPOC)
  é uma marcação clínica POR PACIENTE — default Escala 1.

## Princípio de interceptação — ADVISE/ESCALONAMENTO, NUNCA BLOCK
Não existe "gate" de bloqueio: **nunca se bloqueia o registro de sinais vitais**. A
interceptação é **levantar um alerta de deterioração** (advise/escala) quando o NEWS2
cruza a banda padrão — surfaçado num painel clínico + no atendimento. Determinístico
autoritativo; LLM só explica/prioriza.

## ⚠️ Pré-requisitos de schema (pro eng-review travar)
`emr.VitalSigns` hoje tem PAS, FC, temperatura, SpO2 — mas **faltam 3 dos 7 params do NEWS2**:
- `respiratory_rate` (o param mais preditivo), `on_supplemental_oxygen` (ar vs O2),
  `consciousness` (ACVPU: Alert/Confusion/Voice/Pain/Unresponsive). Adicionar (nullable;
  registrados pela enfermagem — dado real, não inventado).
- **`VitalSigns` é `OneToOneField` no `Encounter`** → **um único snapshot por atendimento**.
  Deterioração exige **série temporal**. **DECISÃO DO ENG-REVIEW:** manter OneToOne e
  escorar o snapshot (v1 mínimo) **ou** introduzir `VitalSignsReading` (série por
  encounter) p/ trend? NEWS2 é pontual, mas o valor preditivo vem da repetição.

## Arquitetura — espelha dose/glosa/estoque
| Camada | Deterioração |
|---|---|
| motor puro | **`NEWS2Calculator`** (`apps/emr/services/news2.py`): vitais → escore agregado + breakdown por param + banda (0=baixo / 1–4=baixo / 3 num único param=baixo-médio / 5–6=médio / ≥7=alto), conforme RCP. PURO, sem DB, citando a fonte. INERTE se faltam params essenciais. |
| orquestrador | **`DeteriorationService`** (resolve os vitais, persiste verdict, flywheel) |
| alerta | **`DeteriorationAlert`** (mirror dos outros: kind, severity advise/escalation, source=engine, status, ack) |
| flag | **`deterioration_safety`** (default OFF) |
| superfície | no save de `VitalSigns` (flag on) → computa NEWS2 → alerta se banda ≥ médio; painel de deterioração; **nunca bloqueia** |

## Sequência de PRs (a confirmar no eng-review)
- **D1 — campos NEWS2 + motor puro:** `VitalSigns` ganha `respiratory_rate`/
  `on_supplemental_oxygen`/`consciousness`; `NEWS2Calculator` puro + testes (vetores do
  documento RCP). Inerte se incompleto. Sem persistência/superfície.
- **D2 — alerta + orquestrador + flag:** `DeteriorationAlert` + `DeteriorationService`
  (computa no save dos vitais, advise/escalation por banda, flywheel AuditLog), flag OFF.
- **D3 — superfície:** painel de deterioração + alerta no atendimento + ack. Sem block.
- **D4 — flywheel:** rotular NEWS2 alto previsto vs desfecho real (transferência UTI /
  chamada de time de resposta rápida) — exige dado de desfecho; pode ser mais leve/adiado.

## ✅ LOCKED (eng-review Gemini, 48s)
- **Schema:** `VitalSigns.encounter` `OneToOneField → ForeignKey` (Django só dropa o
  UNIQUE em `encounter_id` → vira série temporal, **zero data-migration**). OneToOne era
  blocker (enfermaria mede vitais a cada 4–8h; snapshot único apaga histórico). +3 campos:
  `respiratory_rate` (int, null), `on_supplemental_oxygen` (bool, null), `consciousness`
  (char A/C/V/P/U, null). ⚠️ checar usos de `encounter.vital_signs` (reverse vira manager).
- **Motor ESTRITO:** os **7 params obrigatórios** (FR, SpO2, O2-suplementar, PAS, FC, temp,
  ACVPU). Se QUALQUER um for None → retorna `None`/INCOMPLETE. **Sem imputação** — assumir
  "0/normal" num param faltante rebaixa um High pra Low (ex.: FR não logada mas era 28=+3).
- **SpO2 Escala 2:** `use_spo2_scale_2 = BooleanField(default=False)` no **Patient**
  (safe-by-default; só toggla por ação médica explícita — Escala 2 errada mascara hipóxia).
- **Trigger:** `transaction.on_commit(lambda: DeteriorationService.process(vitals_id))`
  no save (signal/serviço) — **nunca** bloqueia a transação de registro do vital.
- **De-dup:** alerta **OPEN/não-ack** → atualiza payload SE novo score > score alertado
  (não cria novo). Alerta **ACK/resolvido** → nova leitura que cruza banda média/alta
  **cria NOVO** alerta.
- **Human gate confirmado:** NEWS2 é padrão público RCP → digitalizar a fórmula NÃO é
  inventar algoritmo. Gate = flag `deterioration_safety` OFF + config de quem é paginado
  em qual banda (roteamento, não a matemática).

### Tabela NEWS2 a implementar (RCP — exata, conferida)
| Param | Pontos |
|---|---|
| **FR** (rpm) | ≤8→3 · 9–11→1 · 12–20→0 · 21–24→2 · ≥25→3 |
| **SpO2 Escala 1** (%) | ≤91→3 · 92–93→2 · 94–95→1 · ≥96→0 |
| **SpO2 Escala 2** (%) | ≤83→3 · 84–85→2 · 86–87→1 · 88–92→0 · (no ar ≥93→0); **em O2:** 93–94→1 · 95–96→2 · ≥97→3 |
| **O2 suplementar** | ar→0 · oxigênio→2 |
| **PAS** (mmHg) | ≤90→3 · 91–100→2 · 101–110→1 · 111–219→0 · ≥220→3 |
| **FC** (bpm) | ≤40→3 · 41–50→1 · 51–90→0 · 91–110→1 · 111–130→2 · ≥131→3 |
| **Temp** (°C) | ≤35.0→3 · 35.1–36.0→1 · 36.1–38.0→0 · 38.1–39.0→1 · ≥39.1→2 |
| **ACVPU** | Alert→0 · Confusion/Voice/Pain/Unresponsive→3 |

**Bandas agregadas:** 0→baixo · 1–4→baixo · **um único param=3**→baixo-médio (revisão urgente)
· 5–6→médio (resposta urgente) · ≥7→alto (resposta de emergência).

## Decisões a travar (eng-review) — RESOLVIDAS acima
- OneToOne vs `VitalSignsReading` série temporal (e migração do bmi/snapshot atual).
- Banda que dispara alerta (≥5 médio? ≥7 alto? single-param-3?) — padrão NEWS2.
- Escala SpO2 1 vs 2 (flag por paciente; default 1).
- Trigger: signal no save de VitalSigns vs serviço explícito (evitar trabalho no signal; on_commit como dose).
- Inércia: faltando params essenciais (ex. sem FR/consciência) → não escorar (não inventar "normal").

## Fora de escopo (v1)
ML/predição de série temporal, qSOFA/SIRS além do NEWS2, telemetria contínua de
monitor, integração com device. Só NEWS2 determinístico pontual + escalonamento advise.

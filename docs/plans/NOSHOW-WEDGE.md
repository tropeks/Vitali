# No-Show Prediction Wedge — Plano (6º wedge AI-native)

> **Tese:** 6º wedge do padrão **Observe→Predict→Intercept→Learn** ([[VISION-AI-NATIVE]]),
> espinha **operacional/receita**: prever qual agendamento vai **faltar** e interceptar
> **antes** do horário vazio — sugerir confirmação ativa / preencher da lista de espera.
> **Distinção estratégica:** é o ÚNICO wedge que entra em produção **sem dado curado** —
> o risco é **derivado** do histórico do próprio paciente (como o estoque deriva a
> velocidade do `StockMovement`), não inventado.

## O que já existe (não reinventar)
- **`emr.Appointment`**: `status` (scheduled/confirmed/waiting/in_progress/completed/
  cancelled/**no_show**), `start_time` (agendado), `created_at` (→ antecedência =
  start_time − created_at), `type` (consulta/retorno/exame/...), `source`
  (recepcao/whatsapp/web/telefone), `whatsapp_confirmed` (bool), `started_at`.
- **`emr.WaitlistEntry`**: lista de espera com `offered_slot`, notify + expiry
  (`tasks_waitlist.py`) — a interceptação "preencher o buraco" já tem trilho.
- **WhatsApp**: `ScheduledReminder` + envio — o trilho de "confirmar ativamente" existe.

→ O histórico de faltas do paciente é **derivado** (`status="no_show"` vs `completed`),
não há dado externo a curar. Só limiares de banda são config (defaults inertes).

## Princípio de interceptação — ADVISE/OPERACIONAL, NUNCA BLOCK
Não bloqueia agendamento nem check-in. Levanta um **score de risco** por agendamento
futuro + **ação sugerida** (confirmar via WhatsApp / overbook / oferecer à lista de
espera) num painel da recepção. Determinístico e transparente; sem ML em v1 (o ML é o
enhancement futuro alimentado pelo flywheel). **v1 SUGERE a ação; não dispara WhatsApp
automaticamente** (envio é outward-facing — auto-ação fica pra depois).

## Honestidade — derivado, não inventado
- Score = **fração histórica de faltas do paciente** (Laplace-smoothed), ajustada por
  features observadas (sem `whatsapp_confirmed`; antecedência alta; faltas recentes
  consecutivas; canal/tipo). Transparente — cada componente explicável.
- **INERTE** se o paciente tem < N agendamentos terminais no histórico (sem base → não
  prevê; não chuta um número). Análogo ao inert<3 do estoque. Paciente novo → sem score.
- Limiares de banda (baixo/médio/alto) = config do estabelecimento, defaults sensatos.

## Arquitetura — espelha estoque (predição derivada de histórico)
| Camada | No-show |
|---|---|
| motor puro | **`NoShowScorer`** (`apps/emr/services/no_show_checker.py`): dado o histórico terminal do paciente + features do agendamento futuro (`now` injetado) → score 0..1 + banda + breakdown dos componentes. PURO, sem DB. INERTE se histórico < min. |
| orquestrador | **`NoShowService`**: resolve histórico por paciente em **batch (sem N+1)**, computa, persiste `NoShowRisk`. Flag `no_show_prediction` OFF. |
| persistência | **`NoShowRisk`** (mirror do `StockAlert`): appointment FK, score, banda, breakdown, suggested_action, status, computed_at — flywheel-friendly (não cache efêmero). |
| superfície | painel "faltas prováveis" pra recepção + indicador na lista de agenda + ação sugerida. Proativo; nunca bloqueia. |
| flywheel | job: predição (banda) vs desfecho real (`no_show` vs `completed`) → true/false positive. |

## Sequência de PRs (a confirmar no eng-review)
- **N1 — motor + modelo + flag:** `NoShowScorer` puro (fração smoothed + modifiers +
  bandas; inert < min-sample) + `NoShowRisk` model + flag `no_show_prediction` OFF + testes.
- **N2 — orquestrador + job + flywheel:** `NoShowService` (batch history, persiste) +
  comando/job proativo (recalcula janela de agendamentos futuros) + grading flywheel.
- **N3 — superfície:** painel de risco + indicador na agenda + ação sugerida (frontend).

## ✅ LOCKED (eng-review independente)
- **Fórmula (odds multiplicativo, NÃO pontos aditivos — evita o bug de saturação/cap):**
  `base = (no_shows + 2) / (terminal + 10)` [prior Beta(2,8) → média 0.20 = baseline do
  estabelecimento, peso 10 pseudo-obs]; `odds = base/(1−base) × Π(modificadores)`;
  `score = odds/(1+odds)` (limitado a (0,1) por construção). **Decimal-only.**
- **Modificadores (multiplicam o ODDS, todos ≥1.0; cada um vira linha no breakdown):**
  sem-confirmação-após-lembrete ×1.6 · lead ≥30d ×1.4 · ≥2 faltas consecutivas prévias
  ×2.0 · canal self-serve (web/whatsapp) ×1.2 · tipo=retorno ×1.15.
- **Bandas:** baixo <0.25 · médio <0.50 · alto ≥0.50 (config do estabelecimento; estes os defaults).
- **Inércia min-sample:** `terminal (completed+no_show) < 5` → **INERTE, não grava linha**
  (paciente novo fica inerte; o prior 20% está no score mas só é surfaçado com ≥5 terminais
  próprios). Inerte = ausência de linha = "sem opinião" (não "baixo risco").
- **Cadência:** job proativo noturno sobre janela `status in (scheduled,confirmed,waiting)`
  e `start_time ∈ [now, now+7d]`; NUNCA computa no render (render lê `NoShowRisk`).
- **Sem N+1 (3 queries fixas):** janela (`select_related patient,professional`) + UMA
  agregação lifetime `values('patient_id').annotate(Count, Count(filter=Q(no_show)))` +
  UMA query ordenada `(patient_id,start_time,status)` p/ o slice por-agendamento e a corrida
  consecutiva. Zero hit por agendamento. O motor puro recebe contagens já fatiadas.
- **Persistência:** modelo `NoShowRisk` (appointment FK **unique**, `score` Decimal, `band`,
  `breakdown` JSON, `suggested_action`, `status` open/acknowledged/resolved, `outcome`
  pending/true_positive/false_positive/false_negative/true_negative, `engine_version`,
  `computed_at`, `graded_at`); `update_or_create` keyed em appointment; preserva ack se a
  banda não mudou.
- **Posture:** advise-only v1 — surface `suggested_action`; **NÃO** auto-envia WhatsApp,
  **NÃO** auto-oferta waitlist, **NÃO** auto-overbook; nunca bloqueia booking/check-in.
  Flag `no_show_prediction` OFF → no-op total.
- **Flywheel:** gradar só agendamentos que viraram `completed`/`no_show` (cancelled
  **excluído** da gradação); médio+alto = predito-positivo, baixo = predito-negativo →
  outcome 4-way; idempotente; 1 AuditLog por gradação.
- **Anti-leakage (travas de correção):** histórico estritamente `start_time < appt.start_time`;
  `cancelled` fora do numerador E do denominador; terminal = só completed+no_show;
  `lead_time` tz-aware, clamp ≥0; modificador sem-confirmação só dispara se o lembrete foi
  enviado (`whatsapp_reminder_sent`); o motor recebe contagens pré-fatiadas e o orquestrador
  só lhe entrega agendamentos FUTUROS (teste explícito em N1).
- **Sequência:** N1 (motor + `NoShowRisk` + flag + testes) · N2 (orquestrador 3-queries +
  job + flywheel) · N3 (superfície). Maior risco: leakage temporal no slice consecutivo.

## Decisões a travar (eng-review) — RESOLVIDAS acima
- Modelo de score: fórmula determinística transparente (quais features, como combinar,
  smoothing) vs ML (fora de v1). **Lock esperado:** determinística + explicável.
- Min-sample de inércia (N agendamentos terminais) antes de pontuar.
- Quando computa: job proativo (mirror estoque) vs on-demand no render. Evitar recompute
  por render; batch sem N+1 (agregar histórico por paciente numa query).
- `NoShowRisk` novo modelo vs anotar Appointment (preferência: modelo, p/ flywheel).
- Ação sugerida só SURFACE em v1 (não auto-enviar WhatsApp/auto-ofertar waitlist).
- Grading: comparar banda prevista vs desfecho após `start_time` passar.

## ✅ SHIPPED (todos merged em master, flag `no_show_prediction` OFF)
- **N1 #98** — motor `apps/emr/services/no_show_checker.py` (odds multiplicativo,
  inert<5) + `NoShowRisk` model + flag.
- **N2 #99** — `NoShowService` (evaluate_window 2-queries sem N+1 + leakage guards;
  grade_predictions 4-way) + comandos `evaluate_no_show`/`grade_no_show_predictions`
  + tasks celery noturnas (migração beat 0023).
- **N3** — superfície: `GET /no-show-risk/` + ack + painel `/faltas` + nav "Faltas";
  índice `AI-NATIVE-WEDGES.md` vira 6 wedges.

**To go live:** ligar a flag + rodar o beat noturno. **Sem dado curado** — risco
derivado do histórico; inerte por paciente até ≥5 agendamentos terminais.

## Fora de escopo (v1)
ML/gradient-boosted no-show model, auto-envio de confirmação, auto-overbook, predição de
cancelamento tardio, fatores externos (clima/feriado). Só score determinístico derivado
do histórico + ação sugerida, advise, flag OFF.

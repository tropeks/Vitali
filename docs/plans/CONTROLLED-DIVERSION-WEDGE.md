# Controlled-Substance Diversion Wedge — Plano (7º wedge AI-native)

> **Tese:** 7º wedge do padrão **Observe→Predict→Intercept→Learn** ([[VISION-AI-NATIVE]]),
> frente **compliance + segurança**: detectar padrões anômalos de dispensação de
> **medicamento controlado** (Portaria 344/SNGPC) — refill cedo demais, doctor-shopping,
> escalada de quantidade — e **avisar** o farmacêutico/compliance, sem bloquear a
> dispensa legítima. Risco DERIVADO do histórico de dispensações (não inventado).

## O que já existe (não reinventar)
- **`pharmacy.Drug.controlled_class`** (none/A1/A2/A3/B1/B2/C1–C5) + `is_controlled`.
- **`pharmacy.Dispensation`**: `prescription`, `prescription_item`, `patient`,
  `dispensed_by` (User), `dispensed_at` (auto); quantidade = soma de
  `DispensationLot.quantity`. `Prescription.prescriber` (Professional).
- **`DispenseView` JÁ tem gates de controlado:** exige `pharmacy.dispense_controlled` +
  `notes` obrigatórias (`apps/pharmacy/views.py:458-473`). **Este wedge NÃO altera esses
  gates** — adiciona uma camada determinística de MONITORAMENTO (advise) em cima.
- `apps/emr/templates/pdf/prescription_controlled.html` (receituário especial).

→ O histórico controlado do paciente é **derivado** das dispensações; sem dado externo
a curar (só limiares são config, inertes/defaults Portaria-344-informados, não autoritativos).

## Princípio de interceptação — ADVISE/COMPLIANCE, NUNCA BLOCK
**Nunca bloqueia a dispensa de controlado** — o farmacêutico tem autoridade legal e o
gate de permissão+notas já governa o ato; bloquear por suspeita negaria a um paciente
seu medicamento legítimo (falso-positivo perigoso). O wedge **registra um alerta** +
surfaça num painel de compliance para revisão. Determinístico autoritativo; sem ML v1.

## Sinais determinísticos (todos DERIVADOS do histórico)
1. **refill_too_soon (overlap):** nova dispensação do MESMO controlado ao MESMO paciente
   antes do fim da cobertura da dispensação anterior. Cobertura = `dispensed_at` +
   dias-de-suprimento, onde dias = `quantidade ÷ (frequency_per_day × dose_amount)` da
   prescrição. 100% derivado. (Se faltar freq/dose → não calcula esse sinal, não chuta.)
2. **multiple_prescribers (doctor-shopping):** mesmo paciente + mesmo controlado (ou
   classe) com dispensações ligadas a ≥K prescritores distintos numa janela. K + janela
   = config (default K=3, 90d — sensato, documentado, NÃO autoritativo).
3. **quantity_escalation:** dispensações sucessivas do mesmo controlado ao paciente com
   quantidade estritamente crescente em ≥3 fills. Derivado, sem config.

## Arquitetura — espelha estoque/no-show (derivado de histórico)
| Camada | Controlados |
|---|---|
| motor puro | **`ControlledDiversionChecker`** (`apps/pharmacy/services/controlled_checker.py`): dado o histórico controlado do paciente (dispensações prévias: drug, qty, dias-supply, prescriber, data) + a dispensação atual → lista de sinais + severidade. PURO, sem DB, `now` injetado. INERTE se sem histórico/dados. |
| orquestrador | **`ControlledSafetyService`**: no dispense (e/ou job), resolve histórico controlado do paciente (sem N+1), roda checker, persiste `ControlledAlert` (advise). Flag `controlled_safety` OFF. |
| persistência | **`ControlledAlert`** (mirror StockAlert): dispensation/patient/drug FK, signal kind, severity advise, detail JSON, status, outcome — flywheel-friendly. |
| superfície | painel de compliance (alertas de controlado em aberto) + ack. Nunca bloqueia. |
| flywheel | rotular sinal vs revisão humana (true_positive/false_positive) no ack. |

## Sequência de PRs (a confirmar no eng-review)
- **C1 — motor + modelo + flag:** `ControlledDiversionChecker` puro (3 sinais, inert sem
  dados) + `ControlledAlert` model + flag `controlled_safety` OFF + testes.
- **C2 — orquestrador + hook no dispense:** `ControlledSafetyService` (resolve histórico
  controlado sem N+1, persiste advise) chamado no `DispenseView` APÓS a dispensa
  (on_commit; nunca bloqueia) + flywheel + testes.
- **C3 — superfície:** painel de compliance + ack endpoint + frontend.

## ✅ LOCKED (eng-review independente — 2 correções vinculantes ao plano)
- **CORREÇÃO 1 — matar a fórmula `qty/(freq×dose)`:** dimensionalmente quebrada
  (`dose_unit` é só massa via `DOSE_UNIT_CHOICES`; quantidade dispensada é contável "un")
  → produziria days_supply confiante-mas-errado e falso refill. **v1 usa
  `min_refill_interval_days`** (campo por-Drug, `null`→inerte, SEM default inventado),
  excluindo splits da MESMA prescrição (partial fill ≠ refill).
- **CORREÇÃO 2 — hook:** `DispenseView` NÃO tem on_commit hoje. C2 adiciona um
  `post_save` em `Dispensation` → `transaction.on_commit` (cobre todos os caminhos de
  criação). Roda DEPOIS do 201; nunca toca o sucesso/latência da dispensa.
- **Posture:** ADVISE-only, nunca bloqueia. Gates existentes (perm+notas) intactos.
- **Sinais v1 (todos prior-only `dispensed_at <`, tenant-scoped, inertes sem dados):**
  - **refill_too_soon** — mesmo `drug_id`, mesmo paciente, re-dispensa dentro de
    `Drug.min_refill_interval_days`; exclui splits da mesma `prescription`. NULL→inerte.
  - **multiple_prescribers** — ≥ **K=3** prescritores distintos, janela **90d**,
    **por controlled_class** (não por drug — doctor-shopping troca de marca na classe).
    K/janela = constantes operacionais documentadas, NÃO regra ANVISA (≠ NEWS2 público).
  - **quantity_escalation** — ≥3 fills sucessivos do mesmo `drug_id`, quantidade
    (`SUM(DispensationLot.quantity)` por dispensação) estritamente crescente. Puro-derivado.
- **Compute:** event-driven on_commit; **sem job noturno** (diversão é reativa).
- **Sem N+1:** 2 queries `values_list` — (1) dispensações prévias do paciente filtradas por
  `controlled_class` + `dispensed_at<` carregando drug+prescriber; (2) `Sum(lot.quantity)`
  por dispensação. Folded em Python. Usa índice `(patient, dispensed_at)`. `now` injetado.
- **Persistência:** `ControlledAlert(dispensation FK, patient, drug, signal_kind, severity=advise,
  detail JSON, status, outcome, engine_version, ack fields, graded_at)`; **key
  (dispensation, signal_kind)**; override-preservation se detail inalterado; **sem
  resolve-stale** (sinal é fato pontual). Uma dispensa pode levantar os 3 (linhas separadas).
- **Imutabilidade:** `Dispensation` não tem status/cancel; deleção de StockMovement proibida
  → toda dispensação é evento real, SEM filtro de "cancelled" (≠ no-show).
- **Sem cross-class:** cada sinal fica no seu agrupamento (classe p/ prescribers, drug p/
  refill+escalation). Honestidade: escalation=derivado; refill-interval=config inerte (sem
  default honesto); K/janela=defaults heurísticos rotulados não-autoritativos.

## Decisões a travar (eng-review) — RESOLVIDAS acima
- Block vs advise (lean: **advise only**, nunca bloqueia controlado).
- Dias-de-suprimento: derivação `qty/(freq×dose)`, tratamento de unidade/None (não chutar).
- Sinais: quais em v1; quais limiares são config (K, janela) vs puramente derivados.
- Onde computa: no dispense (evento, on_commit) vs job proativo. Lean: no dispense.
- Sem N+1: histórico controlado do paciente em query(s) limitada(s).
- Honestidade: limiares config, inertes/defaults Portaria-344-informados não autoritativos.

## ✅ SHIPPED (todos merged em master, flag `controlled_safety` OFF)
- **C1 #102** — motor `controlled_checker.py` (3 sinais, inert) + `ControlledAlert` +
  `Drug.min_refill_interval_days` + flag.
- **C2 #103** — `ControlledSafetyService` (2-query history, override-preserve) +
  `Dispensation` post_save→on_commit (advise, nunca bloqueia) + flywheel.
- **C3** — superfície: `GET /pharmacy/controlled/alerts/` + ack + painel
  `/farmacia/controlados` + nav; `AI-NATIVE-WEDGES.md` vira 7 wedges.

**To go live:** ligar flag (+ opcional `min_refill_interval_days` por droga p/ o sinal
de refill). Sinais derivam do histórico; K=3/90d são defaults operacionais, não regra ANVISA.

## Fora de escopo (v1)
Geração/transmissão de arquivo SNGPC, integração ANVISA, ML de detecção de fraude,
cross-establishment (um tenant só). Só sinais determinísticos derivados + advise, flag OFF.

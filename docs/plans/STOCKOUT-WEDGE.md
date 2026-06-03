# Stockout-Prediction Wedge — Plano (3º wedge AI-native)

> **Tese:** 3º wedge do padrão **Observe→Predict→Intercept→Learn** ([[VISION-AI-NATIVE]]),
> espinha operacional de **suprimentos**: prever a **ruptura de estoque** (item vai
> zerar antes da reposição) e interceptar **antes** — não só listar o que já está baixo
> (o `StockAlertsView` atual = registro reativo). E o espelho: **validade** — lote que
> vence antes do consumo projetado = desperdício.

## Por que estoque, por que agora (office-hours)
- **Demanda real:** ruptura de medicamento/material para atendimento (a "dor do
  estabelecimento" + risco assistencial); e perda por validade é dinheiro no lixo.
- **Status quo:** incumbentes têm relatório de "estoque baixo hoje". Não preveem o
  **dia da ruptura** dado o consumo, nem alertam o lote que vai vencer encalhado.
- **Dado já existe (sem gate de verdade externa, como glosa):** `StockMovement` traz
  o histórico de consumo; `StockItem`/`DispensationLot` o saldo e a validade. A
  velocidade de consumo é **derivada**, não inventada. Só `lead_time`/`safety_stock`/
  `reorder_point` são config do estabelecimento (defaults inertes até preenchidos).
- **Flywheel:** cada predição de ruptura vs. ruptura real (saldo chegou a 0) = exemplo
  rotulado; idem validade prevista vs. perda real.

## Arquitetura — espelha dose/glosa (padrão provado)
| Camada | Estoque |
|---|---|
| motor puro determinístico | **`StockoutChecker`** (`apps/pharmacy/services/stockout_checker.py`): dado saldo, velocidade de consumo (média móvel), lead time → dias-até-ruptura; e validade do lote vs. consumo projetado |
| orquestrador | **`StockoutService`** (resolve histórico via StockMovement, persiste verdict, flywheel) |
| alerta | **`StockAlert`** (mirror do `GlosaSafetyAlert`: kind=stockout_risk\|expiry_waste, severity advise, source=engine, ack) — ou estender o StockAlertsView |
| flag | **`stockout_safety`** (default OFF) |
| gate/superfície | proativo (job/endpoint que recalcula) + **no `DispenseView`**: avisar se a dispensa empurra o item abaixo do ponto seguro / acelera a ruptura |

Princípio: **advise** (operacional, nunca bloqueia dispensa de medicamento — bloquear
suprimento em saúde é perigoso). Determinístico autoritativo; LLM só prioriza/explica.

## Sequência de PRs (a confirmar no eng-review)
- **S1 — motor + campos + flywheel (backend):** `StockItem`/Drug ganham `lead_time_days`,
  `safety_stock`, `reorder_point` (nullable → inerte). `StockoutChecker` (velocidade =
  consumo médio/dia numa janela; dias-até-ruptura = saldo/velocidade; risco se <
  lead_time+buffer). `StockAlert(stockout_risk, advise)`. Flag OFF.
- **S2 — validade/desperdício:** lote (`DispensationLot`/StockItem expiry) que vence
  antes do consumo projetado → `expiry_waste` advise. (Pode entrar no S1.)
- **S3 — superfície:** estender `StockAlertsView` pra preditivo + sugerir reposição
  (PurchaseOrder draft); frontend de painel de risco. Gate no DispenseView (advise).
- **S4 — flywheel:** registrar predição vs ruptura/perda real (job) pra acurácia.

## ✅ LOCKED (eng-review Gemini)
- **Velocidade:** SMA 30 dias, **só `movement_type="dispense"`**. **INERTE** se velocidade=0
  OU < 3 eventos de dispensa na janela (evita falso "ruptura iminente" por consumo
  esporádico; divisão-por-zero impossível pois v=0 → inerte). Item sem histórico → inerte.
- **SEM gate no `DispenseView`** (rejeitado — quem dispensa não compra nem pode parar a
  dispensa clínica; alerta lá = fadiga pura). Wedge é **só proativo**: dashboard de risco
  pro gestor de suprimentos.
- **Campos em `Drug` e `Material`** (NÃO em `StockItem`, que é lote físico): `lead_time_days`,
  `safety_stock`, `reorder_point`, todos `null=True` → **inerte** sem config (nada inventado).
  (`Drug`/`Material` são per-tenant; confirmar. Se fossem shared → tabela `InventoryPolicy`.)
- **`StockAlert` persistente** (mirror do `GlosaSafetyAlert`): `kind` (stockout_risk|expiry_waste),
  `predicted_date`, `status` (open|acked|resolved), `engine_version`, severity **advise**, ack.
  NÃO usar o cache Redis efêmero do `StockAlertsView` (não dá flywheel).
- **Validade (FEFO):** empilhar `StockItem` por `expiry_date` ASC, rodar a velocidade contra
  a pilha; se consumir o lote ultrapassa o `expiry_date`, o resto é desperdício previsto →
  `expiry_waste` advise.
- **Flywheel (job noturno):** pra cada predição vencida — saldo ≤ 0 → `true_positive`;
  houve `movement_type=purchase_order_receiving` entre a predição e a data-alvo →
  `intercepted` (o sistema funcionou, NÃO é falso-positivo); senão e saldo > 0 → `false_positive`.

## Sequência LOCKED
- **S1:** campos de config em `Drug`/`Material` (null/inerte) + `StockoutChecker` puro
  (velocidade injetada pelo orquestrador; regras de inércia) + testes. Sem persistência ainda.
- **S2:** modelo `StockAlert` persistente + lógica de validade/desperdício (FEFO).
- **S3:** superfície dashboard (proativo only; `StockAlertsView` retorna união cache-legado
  + `StockAlert`) + sugestão de reposição (PurchaseOrder draft). Sem gate no dispense.
- **S4:** job noturno de flywheel (intercepted vs false_positive vs true_positive).

### S4 — notas de implementação (shipped)
- **Onde:** `StockoutService.grade_predictions(*, now)` (lógica), comando
  `manage.py grade_stockout_predictions [--schema]` (gatilho manual, thin →
  service, espelha `evaluate_stockout`), task `pharmacy.grade_stockout_predictions`
  (fan-out por tenant) + `StockAlert.outcome`/`graded_at` + migração 0011.
- **Ordem LOCKED (confirmada):** `true_positive` (saldo ≤ 0) é checado ANTES de
  `intercepted` — um produto que recebeu PO mas mesmo assim zerou é ruptura real
  (o recebimento não bastou). Senão `intercepted`; senão `false_positive`.
- **Janela do recebimento:** `(created_at, predicted_date]` — recebimento DEPOIS
  do alerta e ATÉ o dia previsto (fim-do-dia inclusivo).
- **Saldo/recebimento (sem N+1):** saldo = SUM(StockItem.quantity) por produto,
  UMA query por kind (drug/material) somada em memória; recebimentos UMA query
  por kind (`stock_item__drug/material`). Loop por alerta só faz lookup em dict.
- **expiry_waste fora de escopo no S4:** só `stockout_risk` é gradado; alertas de
  validade permanecem `outcome=pending`/ungraded (gradar desperdício = trabalho
  futuro, exige comparar lote previsto-vencido vs. baixa real `expired_write_off`).
- **Independente da flag:** o job só GRADA alertas já existentes (nunca cria);
  se `stockout_safety` está/esteve OFF não há alertas pendentes → no-op. Roda
  sempre, sem gate de flag — mais simples e seguro.
- **celery-beat:** registrado (migração 0012) seguindo o padrão existente de
  `apps/ai` (DatabaseScheduler + PeriodicTask via `get_or_create`, dep em
  `django_celery_beat`); roda nightly 03:00 UTC. Cron equivalente manual:
  `0 3 * * * manage.py grade_stockout_predictions --schema <schema>`.

## Decisões a travar (eng-review) — RESOLVIDAS acima
- Janela e método da velocidade (média móvel simples? sazonalidade fora de escopo v1).
- StockAlert novo vs estender o alerta existente do StockAlertsView.
- Gate: só proativo (job/endpoint) ou também no DispenseView? (advise, nunca block.)
- Multi-tenant; StockMovement query única por item (sem N+1, como glosa auth).
- Sem inventar lead_time/safety_stock — config do estabelecimento, default inerte.

## Fora de escopo (v1)
Previsão sazonal/ML, otimização de compra, integração com fornecedor. Apenas
determinístico (velocidade × lead time) + validade, advise, flag OFF.

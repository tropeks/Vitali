# Vitali — Camada de Serviço: Contrato de Fronteira de Domínio

> **Princípio de referência:** P4 de `ARCH_TARGET_VISION.md` — "Zero import cruzado entre
> apps de domínio; contratos de evento/serviço como única porta de entrada de cada domínio.
> É o que torna extrair barato."
>
> **Enforcement:** import-linter (P1-01, 2026-06-13) rodando no step `backend-lint` do CI
> e duplicado como teste pytest em
> `backend/apps/core/tests/test_import_contracts.py`.
>
> **Documento vivo:** atualizar quando a dívida de um app for quitada ou quando novos apps
> forem adicionados. Nunca alterar a lista de exceções sem um ADR documentado.

---

## 1. Princípio P4 — Costuras Explícitas

O Vitali é um **monólito modular**: 16 apps de domínio Django convivem no mesmo processo,
mas devem se comunicar como se fossem serviços distintos. A única porta de entrada de cada
domínio é a sua **camada de serviço** (`apps.X.services` ou `apps.X.gateway` quando se
trata de protocolo externo):

```
apps.emr          ←→  (nunca diretamente)  ←→  apps.billing
apps.emr.services ←→  apps.core  ←→  apps.billing.services
```

**Regras:**

1. **Zero import cruzado** entre os 16 apps de domínio (listados abaixo) — qualquer
   acesso deve passar por `apps.core` ou por uma chamada explícita à camada de serviço do
   app alvo.
2. **`apps.core` é o hub permitido** — pode importar de qualquer domínio (e é o único que
   pode), mas os domínios não importam uns dos outros diretamente.
3. **Exceções existentes são baseline congelado** — os pares na seção "Dívida atual" foram
   grandfathered em P1-01 (2026-06-13) e estão listados no `ignore_imports` do
   `backend/.importlinter`. Nenhum par novo pode ser adicionado sem ADR.
4. **`gateway.py`** é uma forma válida de porta para integração com protocolo externo (LLM,
   Evolution API) — expõe abstração, não modelos.

---

## 2. Estado atual por app de domínio

Os 16 apps cobertos pelo contrato de independência (`[importlinter:contract:domain-independence]`):

| App | Porta hoje | O que expõe | Observação |
|---|---|---|---|
| `apps.ai` | `services.py` + `services_cid10.py` + `services_scribe.py` + `gateway.py` | `TUSSCoder`, `GlosaPredictor`, helpers de config por tenant; `LLMGateway` (abstração LLM) | `gateway.py` = abstração do LLM (não models); múltiplos módulos de serviço bem definidos |
| `apps.analytics` | **Expõe models/views diretamente — dívida** | `views.py`, `serializers.py`, `urls.py` sem camada de serviço | Sem `services/` ou `services.py`; normalizar |
| `apps.billing` | `services/` (diretório) | `asaas.py`, `glosa_checker.py`, `glosa_safety.py`, `xml_engine.py`, `retorno_parser.py`, `pix_signals.py`, `tasks.py` | Camada de serviço presente e granular |
| `apps.emr` | `services/` (diretório) | `appointment_creation.py`, `encounter_signing.py`, `prescription_safety_gate.py`, `prescription_safety.py`, `patient_registration.py`, `allergy_safety.py`, `dose_safety.py`, `deterioration.py`, `news2.py`, `no_show.py`, `no_show_checker.py`, `whisper.py`, `prescription_pdf.py` | App central; camada de serviço ampla e especializada |
| `apps.fhir` | `services/` (diretório) | Mappers FHIR: `allergy_mapper.py`, `condition_mapper.py`, `encounter_mapper.py`, `medication_request_mapper.py`, `observation_mapper.py`, `patient_mapper.py`, `practitioner_mapper.py`, `service_request_mapper.py` | Camada de serviço bem estruturada (padrão mapper) |
| `apps.hr` | `services.py` | `EmployeeOnboardingService` (orquestrador transacional) | Arquivo único; padrão de service-layer correto (orchestrator) |
| `apps.imaging` | `services/` (diretório) | `orthanc_client.py`, `orthanc_sync.py` | Camada de serviço presente; integra com Orthanc/PACS |
| `apps.mobile` | `services/` (diretório) | `push.py` (push notifications) | Camada de serviço presente |
| `apps.patient_portal` | **Expõe models/views diretamente — dívida** | `views.py`, `serializers.py`, `models.py`, `urls.py` sem camada de serviço | Sem `services/` ou `services.py`; candidato BFP — normalizar antes da extração |
| `apps.pharmacy` | `services/` (diretório) | `allergy_checker.py`, `controlled_checker.py`, `controlled_safety.py`, `dose_checker.py`, `stockout_checker.py`, `stockout_safety.py` | Camada de serviço bem estruturada (padrão checker/safety) |
| `apps.pharmacy_ai` | `services/` (diretório) | `forecast.py` | Camada de serviço presente |
| `apps.signatures` | `services/` (diretório) | `chain.py`, `icp_brasil.py` | Camada de serviço presente (ICP-Brasil + cadeia de assinaturas) |
| `apps.smart_scheduling` | `services/` (diretório) | `ranker.py` | Camada de serviço presente |
| `apps.telemedicine` | **Expõe models/views diretamente — dívida** | `views.py`, `serializers.py`, `models.py`, `urls.py` sem camada de serviço | Sem `services/` ou `services.py`; normalizar |
| `apps.triage` | `services/` (diretório) | `evaluator.py`, `question_bank.py` | Camada de serviço presente |
| `apps.whatsapp` | `services/` (diretório) + `gateway.py` + `slot_service.py` | `opt_in.py`; `WhatsAppGateway`/`EvolutionAPIGateway` (abstração canal); `get_available_slots()` | `gateway.py` = abstração do canal (não models); `slot_service.py` = lógica de slot geração |

**Hub permitido (não domínio):**

| App | Porta hoje | Observação |
|---|---|---|
| `apps.core` | `services/` (`dpa.py`, `email.py`) | Hub da arquitetura; pode importar de domínios; domínios NÃO importam `core` diretamente (usam injeção ou `apps.core.models` via ORM) |

---

## 3. Dívida atual — cross-imports (baseline congelado)

Os pares abaixo são **exceções grandfathered** ao princípio P4, registradas no
`ignore_imports` do `backend/.importlinter` em P1-01 (2026-06-13). Cada par representa
acoplamento direto que **deve ser refatorado** para uma chamada à camada de serviço do app
alvo ou para uma abstração em `apps.core`.

**Proibido adicionar novos pares sem ADR documentado.**

### 3.1 Cross-domain direto (21 pares)

| Importador | Importado | Ação de convergência |
|---|---|---|
| `apps.ai.**` | `apps.emr.**` | Substituir import direto por `apps.emr.services.*` |
| `apps.analytics.**` | `apps.ai.**` | Substituir import direto por `apps.ai.services.*` |
| `apps.analytics.**` | `apps.billing.**` | Substituir import direto por `apps.billing.services.*` |
| `apps.analytics.**` | `apps.emr.**` | Substituir import direto por `apps.emr.services.*` |
| `apps.billing.**` | `apps.ai.**` | Substituir import direto por `apps.ai.services.*` |
| `apps.billing.**` | `apps.emr.**` | Substituir import direto por `apps.emr.services.*` |
| `apps.emr.**` | `apps.ai.**` | Substituir import direto por `apps.ai.services.*` ou `gateway` |
| `apps.emr.**` | `apps.pharmacy.**` | Substituir import direto por `apps.pharmacy.services.*` |
| `apps.emr.**` | `apps.whatsapp.**` | Substituir import direto por `apps.whatsapp.services.*` ou `gateway` |
| `apps.fhir.**` | `apps.emr.**` | Substituir import direto por `apps.emr.services.*` |
| `apps.fhir.**` | `apps.pharmacy.**` | Substituir import direto por `apps.pharmacy.services.*` |
| `apps.hr.**` | `apps.emr.**` | Substituir import direto por `apps.emr.services.*` |
| `apps.hr.**` | `apps.whatsapp.**` | Substituir import direto por `apps.whatsapp.services.*` ou `gateway` |
| `apps.imaging.**` | `apps.emr.**` | Substituir import direto por `apps.emr.services.*` |
| `apps.patient_portal.**` | `apps.emr.**` | Substituir import direto por `apps.emr.services.*` (prioridade BFP) |
| `apps.pharmacy.**` | `apps.emr.**` | Substituir import direto por `apps.emr.services.*` |
| `apps.pharmacy_ai.**` | `apps.pharmacy.**` | Substituir import direto por `apps.pharmacy.services.*` |
| `apps.smart_scheduling.**` | `apps.emr.**` | Substituir import direto por `apps.emr.services.*` |
| `apps.telemedicine.**` | `apps.emr.**` | Substituir import direto por `apps.emr.services.*` |
| `apps.triage.**` | `apps.emr.**` | Substituir import direto por `apps.emr.services.*` |
| `apps.whatsapp.**` | `apps.emr.**` | Substituir import direto por `apps.emr.services.*` |

### 3.2 Bordas core → domínio (4 pares, mascarados para evitar violações transitivas)

O import-linter usa `apps.core` como hub (domínios → core é permitido). Entretanto, o
próprio core importa alguns models de domínio em `core.signals`, `core.views_onboarding` e
`core.views_platform`, criando caminhos transitivos `domainA → core → domainB` que seriam
relatados como violações entre apps não relacionados. Esses caminhos são mascarados:

| Mascarado | Razão |
|---|---|
| `apps.core.** -> apps.emr.**` | `core.signals`/`core.views_*` importam models de emr |
| `apps.core.** -> apps.billing.**` | `core.views_platform` importa models de billing |
| `apps.core.** -> apps.pharmacy.**` | `core.signals`/`core.views_*` importam models de pharmacy |
| `apps.core.** -> apps.hr.**` | `core.views_onboarding` importa models de hr |

Esses caminhos em `apps.core` devem ser migrados para acesso via services a prazo, mas não
disparam a regra de independência entre domínios (core é o hub permitido).

---

## 4. Enforcement

O contrato P4 é verificável em máquina via dois mecanismos complementares:

### 4.1 import-linter no CI (step `backend-lint`)

Arquivo de configuração: `backend/.importlinter`

```
[importlinter:contract:domain-independence]
name = Domain apps must not import from each other (cross-domain coupling)
type = independence
modules = apps.emr, apps.billing, apps.pharmacy, apps.ai, apps.whatsapp,
          apps.hr, apps.signatures, apps.fhir, apps.imaging, apps.telemedicine,
          apps.patient_portal, apps.pharmacy_ai, apps.smart_scheduling,
          apps.triage, apps.mobile, apps.analytics
```

Qualquer import novo entre domínios que **não** esteja na lista `ignore_imports` causa
falha imediata do step `backend-lint`. A lista de exceções é o **baseline congelado** —
não deve crescer.

### 4.2 Teste pytest (gate de regressão)

Arquivo: `backend/apps/core/tests/test_import_contracts.py`

Executa a mesma verificação do import-linter como teste pytest, garantindo que o contrato
seja validado também no passo `pytest` do CI, independentemente da ordem dos steps.

### 4.3 Política de exceções

- **Adicionar** um par ao `ignore_imports` requer ADR documentado explicando por que a
  refatoração não é viável naquele momento e qual é o plano de quitação.
- **Remover** pares do `ignore_imports` é o objetivo — cada remoção significa que a dívida
  foi quitada (import eliminado ou substituído por chamada de serviço).

---

## 5. Roadmap de convergência

### 5.1 Apps sem camada de serviço (prioridade de normalização)

Os seguintes apps expõem models/views diretamente, sem `services/` ou `services.py`:

| App | Situação | Prioridade |
|---|---|---|
| `apps.analytics` | Sem services; acesso via views/serializers | Média — analytics é consumidor, raramente chamado por outros |
| `apps.patient_portal` | Sem services; candidato BFP | **Alta** — é a 1ª extração planejada (BFP); deve ter interface de serviço clara antes de extrair |
| `apps.telemedicine` | Sem services; acoplado a emr via dívida | Alta — tem 1 par de dívida (`telemedicine → emr`); criar services.py e eliminar o par |

**Ação recomendada para cada um:**
1. Criar `services.py` (ou `services/`) com funções/classes que encapsulam a lógica de
   negócio hoje espalhada em `views.py`.
2. Migrar os imports de dívida correspondentes para chamadas à nova camada de serviço.
3. Remover o par do `ignore_imports` (redução da dívida mensurável).

### 5.2 Redução incremental da dívida

Ordem sugerida de quitação (menor impacto → maior):

1. **`apps.telemedicine → apps.emr`** — 1 par, app pequeno, criar services.py é trivial.
2. **`apps.triage → apps.emr`** — 1 par, triage já tem services/; refatorar o import.
3. **`apps.smart_scheduling → apps.emr`** — 1 par, já tem services/; refatorar o import.
4. **`apps.pharmacy_ai → apps.pharmacy`** — 1 par, pharmacy_ai já tem services/; refatorar.
5. **`apps.imaging → apps.emr`** — 1 par, imaging já tem services/; refatorar.
6. **`apps.patient_portal → apps.emr`** — 1 par, prioridade BFP; criar services.py.
7. **`apps.fhir → apps.emr` + `apps.fhir → apps.pharmacy`** — 2 pares, padrão mapper.
8. **`apps.hr → apps.emr` + `apps.hr → apps.whatsapp`** — 2 pares, hr tem services.py.
9. **`apps.whatsapp → apps.emr`** — 1 par; whatsapp já tem gateway + services/.
10. **`apps.analytics → *` (3 pares)** — analytics sem services/; criar serviços de leitura.
11. **`apps.emr → *` (3 pares: ai, pharmacy, whatsapp)** — emr é o app central; refatorar por último.
12. **`apps.billing → *` + `apps.ai → *`** — billing e ai têm acoplamento múltiplo; por último.

Cada quitação = 1 par removido do `ignore_imports` + commit com mensagem
`refactor: eliminate <app_a>→<app_b> cross-import (service-layer convergence)`.

---

## 6. Referências

- `backend/.importlinter` — contrato executável (fonte única da verdade das exceções)
- `backend/apps/core/tests/test_import_contracts.py` — teste pytest correspondente
- `docs/ARCH_TARGET_VISION.md` — princípio P4 (seção 5) e critério de extração (seção 3)
- `docs/ARCHITECTURE.md` — ADR-001 (Modular Monolith), contexto geral de arquitetura

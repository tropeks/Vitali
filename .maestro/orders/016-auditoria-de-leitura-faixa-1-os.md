<!-- maestro-order v1
id: 016
ts: 2026-09-17T06:50:30-03:00
epoch: 1789638630
head: 4724d1c0b54cd1f03223b6944a2fa34e94cc3abd
branch: order/016-auditoria-leitura-phi
intent_version: 5
intent_hash: a6120b3c
author_session: desconhecido
-->
# Ordem 016 — Auditoria de leitura faixa 1: os viewsets que tocam paciente deixam trilha



## A medição — e ela me corrigiu duas vezes

**Primeira correção: o número.** Contar viewsets por expressão regular deu 71, depois
75, depois 41, conforme a janela do casamento — perdia herança quebrada em várias
linhas e perdia `ManyToManyField`. Perguntando ao **roteador do Django**:

```
154 views registradas    59 com trilha    95 sem
```

O 59 bate com o que o PR #211 afirmava. Este é o número real; os meus anteriores não
eram.

**Segunda correção: a classificação.** Buscar "alcança `emr.Patient`?" no grafo de
models devolveu **47 candidatos — 46 eram ruído**, chegando lá por
`created_by → core.User → patient_portal.PatientPortalAccess → Patient`. Por essa
lógica todo model com autor é PHI. Quem cria um registro não é o paciente do registro:
a aresta existe no grafo e não existe no significado.

Proibida a travessia por `core.User`/`Tenant`/`Role` e limitando a **2 saltos**,
sobraram **15**, das quais `UserDetailView` é a mesma aresta vista do outro lado (o
model *é* `User`) — isenta, com motivo escrito.

## Faixa 1 — 14 views

Três delas eu não teria achado lendo nomes:

| view | alcança paciente por |
|---|---|
| `TISSBatchViewSet` | `guides` — **ManyToMany**, que meu primeiro classificador ignorava |
| `StockMovementViewSet` | `surgical_case → SurgicalCase → patient` |
| `InpatientFeeViewSet` | `admission → Admission → patient` |

`LabTest` ficou **fora**: lendo o model, é catálogo de exames (código, nome, categoria,
tipo de resultado), não resultado de paciente. `MessageLog` entrou: tem
`contact → WhatsAppContact → patient` e `content_preview` com 200 caracteres da mensagem.

`AuditReadMixin` entra como **primeira base** — precisa interceptar `retrieve`/`list`
antes do `ModelViewSet`, senão o `super()` do mixin nunca é alcançado.

## O entregável durável é o teste, não as 14 edições

`apps/core/audit_coverage.py` + `test_auditoria_leitura_cobertura.py`: enumera pelo
roteador, classifica pelo grafo, e **reprova quando nasce view clínica sem trilha**,
listando o caminho de cada uma. Sem ele a cobertura cai sozinha — foi assim que chegou
a 59 de 154.

Dois cuidados contra aprovação por vacuidade:

* **piso de enumeração** — se um refactor quebrar a travessia do roteador, a lista
  encolhe e o teste passaria sem verificar nada; o piso acusa o colapso;
* **isenção exige motivo escrito**, testado por tamanho mínimo. Isenção sem motivo
  vira isenção por hábito.

## Prova

```
teste que falha antes    14 falhas, com o caminho de cada uma
suíte dos apps tocados   1.934 passam, 0 falham
gate local               ruff · format · mypy · lint-imports · makemigrations --check
```

**Cinco falhas que NÃO são desta ordem:** `test_drill_metric.py` reprova no meu
contêiner porque eu monto só `backend/` e o teste resolve a raiz do repo como `/`, onde
`scripts/drill_metric.sh` não existe. Com o repo inteiro montado, passam. Não toquei
nesse arquivo.

## Faixa 3 — o que deliberadamente NÃO recebe trilha

Catálogo e operacional: `DrugInteraction`, `AllergenClass`, `ImagingModality`,
`CostCenter`, estoque de farmácia, financeiro sem vínculo a guia. Auditar leitura de
catálogo público enche o `AuditLog` de ruído e ensina a ignorá-lo — o mesmo defeito de
alerta que o INTENT §Limites proíbe. O motivo está no `audit_coverage.py`, não numa
decisão perdida em histórico.


## Contrato de execução
- Trabalhe APENAS no branch `order/016-auditoria-leitura-phi`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-16 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v5 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 016` (você não fecha a própria ordem).

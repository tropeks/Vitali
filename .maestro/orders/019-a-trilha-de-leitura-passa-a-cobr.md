<!-- maestro-order v1
id: 019
ts: 2026-09-18T05:26:33-03:00
epoch: 1789719993
head: 94378831c8a36c246711a9fa7acafdab4d609e22
branch: order/019-trilha-por-rota
intent_version: 5
intent_hash: a6120b3c
author_session: desconhecido
-->
# Ordem 019 — A trilha de leitura passa a cobrir a rota, nao a classe: lista sem filtro e as leituras de prontuario que entram por action

> **Direção:** INTENT v5, **Prioridade 5** (compliance como gate) e **§Limites — "Sinal
> verde tem que significar verde. Healthcheck, CI e alerta que vivem vermelhos ensinam a
> equipe a ignorar vermelho."** Aqui o defeito é a outra face: um verde que não significa
> verde. Fecha a série 016–018.

## A medição mudou a pergunta

A ordem foi pedida como "ligar trilha em lista sem filtro, pesando trilha contra ruído".
Medindo os dois lados, apareceu um problema maior que o pedido, e ele muda o que a 019
tem de fazer.

**O guarda responde na granularidade da CLASSE; o mixin age na granularidade da ROTA.**
`audit_coverage.views_registradas()` decide `tem_trilha` com `issubclass(cls,
AuditReadMixin)`. O mixin, porém, só intercepta `retrieve` e `list`. Enumerando as rotas
`GET` pelo roteador, nas views que o guarda dá como cobertas:

```
338 rotas GET em views COM trilha
308 cobertas pelo mixin (list/retrieve)
 30 NAO cobertas — 15 actions distintas
```

Sete dessas quinze leem prontuário, e hoje **não deixam rastro nenhum** enquanto o teste
da 016 as reporta verdes:

| action | o que devolve |
|---|---|
| `PatientViewSet.medical_history` | o histórico médico — é o prontuário, literalmente |
| `PatientViewSet.allergies` | alergias do paciente |
| `PatientViewSet.timeline` | a linha do tempo clínica |
| `PatientViewSet.insurance` | convênio e carteirinha |
| `EncounterViewSet.procedures` | procedimentos do atendimento |
| `SurgicalCaseViewSet.timeline` | tempos e eventos da cirurgia |
| `TISSBatchViewSet.download` | **baixa o XML do lote**, com as guias dos pacientes |

`download` é a leitura mais forte que existe — o dado sai do sistema em arquivo — e é a
que menos rastro deixa. A Res. CFM 1.821/2007 pede rastreabilidade do ACESSO ao
prontuário; `medical_history` sem trilha é exatamente o buraco que a 016 dizia ter
fechado.

## O peso, medido dos dois lados

**O ruído mora nas actions coletivas, não na lista.** A varredura do `frontend/` mostrou
que as telas que pollam batem em action custom, não em `list`:

```
/waiting-room       2 listas cruas a cada 30s  -> ~240 linhas/hora/aba
                    (waiting-room + appointments/today)
                    10h x 3 recepcoes ~ 7.200 linhas/dia
/pronto-socorro     emergency-encounters/board a cada 30s, 24/7
                    ~120 linhas/hora/aba ~ 2.900 linhas/dia por tela de parede
```

Auditar as seis actions **coletivas** (`census`, `planned`, `today`, `board` do PS,
`board` do centro cirúrgico, `dre`) custaria na ordem de **10 mil linhas por dia por
tenant**. E o custo é permanente:

* `apps.core` está em `SHARED_APPS` → `core_auditlog` vive no schema `public`, **uma
  tabela para todos os tenants**: o volume soma entre clínicas, não divide;
* **não existe expurgo de `AuditLog`** — procurei; só `AIScribeSession` tem retenção;
* a tabela tem **8 índices**: cada linha custa oito escritas de índice;
* medido em staging: **869 bytes por linha** — e ali o `user_agent` tem 13 caracteres
  porque quem chama é cliente de API. Com navegador real passa de 200.

A ~1 KB por linha, dez mil linhas/dia dão **~3,6 GB por ano por tenant**, para sempre,
de painel de parede repintando a cada 30 segundos. É o defeito de alerta que o INTENT
§Limites proíbe: enche o `AuditLog` de ruído e ensina a ignorá-lo.

**A lista, ao contrário, é barata.** As chamadas cruas de `list` que a varredura achou
são de montagem de tela (`/rh/*` — sete call sites de `hr/employees`; `/billing/glosas`,
`/settlements`, `/receivables`, `/payables`; `/farmacia/stock/items`; as nove em cascata
de `/concessao/logistica`), **nenhuma em polling**. O custo é da ordem de uma linha por
abertura de tela — limitado pela atenção humana, não por `setInterval`.

**E o benefício do desenho atual é, medido, zero.** Em 57 dias de staging o
`core_auditlog` tem 603 linhas, das quais **`view_record_list` = 0**. O ramo "registro
quando há busca dirigida" nunca disparou, porque a UI nunca passou filtro. A trilha de
leitura que existe hoje é só `retrieve` (51 linhas: Encounter 30, Patient 21).

## O corte, e ele é declarado no código

**Recebem trilha:**

1. **`list` sempre**, nas views onde o dado é de paciente ou pessoal sensível —
   `AUDIT_LIST_ALWAYS = True` por viewset, opt-in.
2. **As sete actions de detalhe** da tabela acima. São leitura de prontuário de UMA
   pessoa, disparadas por decisão humana, e o volume acompanha a atenção de quem lê.

**NÃO recebem, e o motivo fica escrito no código:**

3. **As seis actions coletivas** (`census`, `planned`, `today`, `board`×2, `dre`):
   painel de trabalho que repinta sozinho. Uma linha por repintura não diz quem foi
   procurar o quê — diz que a tela estava aberta. É ruído com aparência de trilha.
4. **As duas de catálogo de opções** (`sadt_atendimento_options`,
   `tipo_faturamento_options`): não há dado de ninguém ali.

## O entregável durável: o guarda muda de granularidade

Sem isto, a 019 conserta quinze rotas e deixa a décima sexta nascer sem trilha amanhã.

`audit_coverage` deixa de responder "esta CLASSE herda o mixin?" e passa a responder
**"esta ROTA `GET` deixa trilha?"** — enumerando pelo roteador, como a 016 já faz para
as views. Toda rota `GET` de uma view que alcança `Patient` ou está em
`MODELS_SENSIVEIS` precisa estar num dos dois lados: coberta, ou declarada isenta **com
motivo escrito**, no mesmo contrato que `ISENTAS` e `MODELS_SEM_DADO_SENSIVEL` já têm.

O teste da 016 continua valendo e não pode afrouxar; o piso de enumeração ganha o
equivalente por rota.

## Fora desta ordem

Retenção/expurgo e particionamento do `core_auditlog`, e a discussão de ele viver no
schema `public` compartilhado — são reais, apareceram nesta medição, e são grandes
demais para entrar aqui. **Ordem própria, e vale abrir antes de a primeira clínica
pagante entrar.**

Também fora: consertar o `frontend` (o `census` duplicado em `/internacao`, a agenda
inteira baixada em `/appointments`, o retry de 401 que repete a request). São desperdício
real, medido na varredura, mas são ordem de frontend.

Nenhuma migration, nenhuma mudança de model, nenhuma mudança de permissão.

## Contrato de execução
- Trabalhe APENAS no branch `order/019-trilha-por-rota`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-19 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v5 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 019` (você não fecha a própria ordem).
accepted_at: 2026-09-18T17:20:31-03:00
accepted_session: desconhecido
accepted_tree: 9f4d7621c9577eab27b7fc20747dc8a9cd385cc9
accepted_intent: 5

<!-- maestro-order v1
id: 018
ts: 2026-09-17T13:16:27-03:00
epoch: 1789661787
head: 7176a4787a9dc880ed629e3e4a032f1e8357fbb7
branch: order/018-hr-filtro-employee
intent_version: 5
intent_hash: a6120b3c
author_session: desconhecido
-->
# Ordem 018 — O RH ganha filtro por funcionario, e a trilha de lista volta a valer

> **Direção:** INTENT v5, **Prioridade 5 — compliance como gate, não como sprint
> futura.** Continuação direta da ordem 017 (faixa 2 da auditoria de leitura, PR #222,
> mesclada em onda0 `7176a47`).

## O que a 017 deixou em aberto, e por quê

A 017 pôs `AUDIT_LIST_PARAMS = ()` em `LeaveRequestViewSet`,
`OccupationalHealthExamViewSet` e `DependentViewSet`. Não foi desleixo: `?employee=` e
`?search=` **não filtram** nessas três — nenhuma tem `get_queryset`, nem
`filterset_fields`, nem `search_fields`, e `DjangoFilterBackend` não está nos
`DEFAULT_FILTER_BACKENDS` (só `SearchFilter` e `OrderingFilter`).

`AuditReadMixin.list()` dispara pela **presença** do parâmetro, não pelo efeito dele.
Registrar um critério inerte faria uma leitura de **todo mundo** parecer dirigida a uma
pessoa — trilha que subestima a exposição, que é o sentido que engana auditoria. Melhor
não registrar do que registrar errado.

Esta ordem tira a escolha entre as duas coisas ruins: **faz o parâmetro ser verdade, e
aí a trilha volta.**

## Três fatos medidos antes de escrever isto

1. **Nenhum chamador passa `?employee=` hoje.** `grep` por `employee=` em `frontend/`
   não devolve nada. Ligar o filtro não quebra chamador nenhum.
2. **As telas de RH buscam sem filtro.** `frontend/app/(dashboard)/rh/afastamentos/page.tsx:63`
   chama `/api/v1/hr/leave-requests/` cru. Ou seja: **cada abertura da tela de
   afastamentos lê o afastamento médico de todo o quadro da clínica** — e, depois da
   017, sem deixar trilha, porque lista sem filtro não registra.
3. `TimeEntryViewSet` já faz o filtro certo (`get_queryset` com
   `.filter(employee_id=...)` para quem tem `hr.manage`), e por isso foi a única que
   manteve `AUDIT_LIST_PARAMS`. É o padrão a seguir — **menos** o escopo-próprio, que
   ali existe porque o ponto é do próprio funcionário e estas três são só de gestor.

## O trabalho

**1. `?employee=` filtra de verdade nas três.** Mesmo padrão do `TimeEntryViewSet`.
As três estão atrás de `HRManagePermissionMixin`, então não há decisão de autorização
aqui — o filtro só estreita o que o gestor já podia ver.

**2. `AUDIT_LIST_PARAMS = ("employee",)` volta nas três.** Sem `"search"`: continua
inerte, porque nenhuma declara `search_fields`.

**3. `AUDIT_LIST_PARAMS` ganha anotação em `apps/core/mixins.py` — esta ordem
autoriza.** Hoje o atributo não tem tipo, o mypy infere `tuple[str, str]` do valor
default, e todo override de aridade diferente vira erro `[assignment]`: a 017 pagou
isso com quatro `# type: ignore`. `AUDIT_LIST_PARAMS: tuple[str, ...] = ("patient",
"search")` apaga os quatro. **O valor default não muda e nenhum comportamento muda** —
é anotação, não lógica. Qualquer outra mudança no mixin continua fora.

## O entregável durável é o teste que amarra as duas coisas

Parâmetro declarado na trilha e parâmetro que filtra viraram a mesma coisa nesta ordem,
e é isso que precisa ficar amarrado por teste — senão a 017 se repete daqui a seis meses
com outro nome de campo.

Para **cada uma das quatro** views de RH com trilha, um teste de API que, com dois
funcionários e registros de ambos:

* `GET ...?employee=<A>` devolve **só** os registros de A — se o parâmetro for ignorado,
  o teste falha;
* a mesma chamada grava **uma** linha de `AuditLog` com `action=view_record_list` e o
  critério em `new_data`;
* `GET` sem parâmetro **não** grava linha de lista (o comportamento que a 017 fixou).

Um teste que só verifique que o endpoint aceita o parâmetro não serve — foi exatamente
isso que deixou passar o critério inerte.

## Fora desta ordem, e não é esquecimento

**A lista sem filtro continua sem trilha nenhuma, e agora tem gatilho concreto.** O fato
2 acima mostra que a tela de afastamentos lê o quadro inteiro a cada abertura. Fechar
isso é uma linha opcional no `AuditReadMixin` (`AUDIT_LIST_ALWAYS`, default `False`,
faixa 1 intocada) mais a decisão de em quais views ligar — e essa decisão precisa pesar
o volume de trilha contra o ruído, que é a razão pela qual a faixa 1 não registra lista
crua. **Ordem própria, e é a mais importante das três pendências da 017.**

`?search=` e `search_fields` também ficam fora: decidir por quais campos se busca num
model de afastamento médico é decisão de produto, não de implementação.

Nenhuma migration, nenhuma mudança de model, nenhuma mudança de permissão.

## Contrato de execução
- Trabalhe APENAS no branch `order/018-hr-filtro-employee`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-18 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v5 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 018` (você não fecha a própria ordem).

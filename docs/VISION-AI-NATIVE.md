# Vitali — Visão AI-Native

> **Status:** Aprovado (office-hours, fundador) | **Data:** 2026-06 | **Tese:** O software hospitalar deixa de ser um arquivo passivo e passa a ser inteligência ativa que **intercepta o erro antes que ele aconteça.**

---

## 1. A revolução — a crença contrária

Todo incumbente do mercado — Tasy, MV, TOTVS Saúde — é, no fundo, um **CRUD de 20 anos**. São sistemas de *registro*: eles anotam o que aconteceu. A prescrição foi feita, a dose foi administrada, a guia foi glosada. Tudo virou linha em tabela. O melhor que esses sistemas oferecem é um **relatório do que deu errado ontem.**

A crença contrária do Vitali é simples e radical:

> O software hospitalar não deve ser um cartório do passado. Deve ser uma inteligência que **age no presente** — que olha para a ação que está prestes a acontecer e diz, na hora, "**pare: isto vai machucar o paciente, agora.**"

Não é "relatório do que deu errado ontem". É **interceptação no momento do erro**. Essa diferença não é de feature — é de **categoria**. Um sistema de registro nunca evita um dano; só o documenta depois. Um sistema que intercepta evita o dano antes de existir.

---

## 2. A cunha de entrada (landing wedge): interceptação de erro de DOSE

A porta de entrada do Vitali no mercado é uma só, estreita e mortal: **erro de dose de medicamento, ciente do paciente.**

O sistema **conhece a dose correta para aquele paciente específico** — peso, idade, função renal — e **intercepta o desvio em cada portão da jornada do medicamento**:

```
PRESCRIÇÃO  ──►  FARMÁCIA  ──►  ADMINISTRAÇÃO À BEIRA-LEITO
   (gate 1)       (gate 2)            (gate 3)
```

Começamos pelos **injetáveis** — a classe de maior risco e maior letalidade. É onde um erro mata mais rápido e onde a interceptação vale mais.

**Exemplo concreto.** Um médico erra a vírgula e prescreve **10× a dose** correta:

- **Gate 1 — Prescrição:** o sistema bloqueia na hora. "Esta dose é 10× a faixa segura para um paciente de 62 kg com clearance reduzido. Confirmar?"
- **Gate 2 — Farmácia:** se passou (override consciente), a farmácia **rechecа** contra o mesmo cérebro de dose antes de dispensar.
- **Gate 3 — Administração:** à beira-leito, no momento de injetar, o enfermeiro recebe o alerta final.

Três portões, um único cérebro de dose. O erro tem que furar **os três** para chegar ao paciente — e cada portão aprende com o que passou.

---

## 3. Por que os incumbentes não conseguem copiar — o fosso é arquitetural, não de velocidade

A objeção óbvia: "a Philips/MV não pode simplesmente adicionar isso?" Não — e não por falta de dinheiro ou de engenheiros. É **estrutural**:

1. **O núcleo deles é um armazém de registros de 20 anos.** O coração do Tasy/MV/TOTVS foi construído para *gravar* estado, não para *raciocinar em tempo real* sobre cada dose. Reescrever esse núcleo para pensar a cada prescrição quebra tudo o que está em produção em centenas de hospitais. Não é um sprint — é um transplante de coluna vertebral.

2. **Os módulos deles são silos separados — às vezes de fornecedores diferentes.** Prescrição, farmácia e enfermagem frequentemente são sistemas distintos, integrados na unha por interfaces frágeis. Eles **não conseguem fechar o loop** ao longo de toda a jornada do medicamento porque não controlam os três portões. Um sistema AI-native construído do zero controla — porque nasceu como um único loop, não como três produtos colados.

3. **Interceptar NO MOMENTO DA AÇÃO exige IA na espinha do workflow, não um relatório acoplado.** A inteligência tem que estar *dentro* do clique que assina a prescrição, *dentro* do scan da farmácia, *dentro* do bipe da beira-leito. Bolt-on report nenhum faz isso. Quem quer interceptar tem que ter a IA na coluna vertebral — e isso só se constrói desde o primeiro dia.

O fosso, portanto, não é "chegamos antes". É **"eles teriam que se tornar outra empresa para nos alcançar."**

---

## 4. O data flywheel — o fosso que compõe juros

A interceptação é a porta. O **flywheel de dados** é o que torna o Vitali indefensável com o tempo.

Cada interação vira um **exemplo de treino rotulado**:

- Cada **alerta** disparado.
- Cada **override do médico** ("não, esta dose está correta para este caso oncológico") — que é um rótulo *negativo* valiosíssimo, dado por um especialista, de graça.
- Cada **desfecho** do paciente.

Com isso, o modelo de dose-segura **melhora toda semana** — e melhora **por população, por clínica**. A pediatria de uma clínica afina diferente da nefrologia de outra. O volume de eventos clínicos rotulados que um concorrente precisaria para igualar leva **anos** — e, crucialmente, **não pode ser alugado da OpenAI nem da Anthropic.** Nenhum LLM de prateleira tem os overrides dos *seus* médicos sobre os *seus* pacientes.

> A IA aqui não é uma feature a adicionar. É um **flywheel de dados a compor.** Quanto mais o produto é usado, mais defensável ele fica.

---

## 5. Os 4 princípios AI-native (o padrão que replica para TODO módulo)

Estes quatro princípios são a assinatura arquitetural do Vitali. Valem para a dose hoje e para qualquer módulo amanhã.

1. **A inteligência é a espinha, não um botão.** Todo workflow nasce de um *loop*, não de uma tela esperando input. O sistema não pergunta "o que você quer fazer?" — ele já está observando e prestes a agir.

2. **Observe → Preveja → Intercepte → Aprenda.** Todo módulo fecha esse ciclo. Dose hoje; glosa/negativa de pagamento, ruptura de estoque e no-show depois — **o mesmo padrão**, sempre.

3. **Dados compõem.** Cada decisão, cada override, cada desfecho realimenta o modelo. O produto fica mais defensável **com o uso**, não com o tempo de prateleira.

4. **Aja no momento, não no relatório.** O valor está em interceptar **antes** do dano/perda — não em documentar **depois**. Se a informação chega no relatório de fim de mês, já é tarde.

---

## 6. "Boil the ocean", do jeito certo

A tentação é construir tudo de uma vez. O erro é construir tudo *raso*. A disciplina do Vitali:

- **Aterrissar ESTREITO:** segurança de dose em injetáveis. Ser **obsessivamente bom** nisso — melhor que qualquer um no mundo.
- **Provar o padrão de loop fechado:** observe → preveja → intercepte → aprenda, funcionando de ponta a ponta, com o flywheel girando.
- **Replicar LARGO:** o **mesmo motor** observe-preveja-intercepte-aprenda aplicado a glosa, estoque, agenda, triagem.

Construímos o oceano inteiro — mas **cada gota é inteligente.** Isso **não** é "um Tasy com mais módulos". É uma **categoria nova**: o **sistema operacional clínico que PENSA.**

---

## 7. North Star

> **Vitali é a inteligência ativa que intercepta o erro clínico antes que ele alcance o paciente — e que fica mais inteligente a cada decisão que vê.**

### A semente já existe

O `AISafetyAlert` (a rede de segurança de prescrição entregue no Sprint 15 — `PrescriptionSafetyChecker`, ver `docs/PLAN_SPRINT15.md` S-063 e `docs/EPICS_AND_ROADMAP.md` E-013/F-12) é **a semente desta cunha.** Hoje é uma checagem de LLM de prateleira (commodity), disparada por signal e registrada em `AISafetyAlert` com `override_reason` e `outcome`. O caminho à frente é **aprofundá-la** na espinha real de **interceptação de dose em tempo real, que aprende** — os três portões da seção 2, alimentados pelo flywheel da seção 4.

A estrutura para o flywheel já está lá: `AISafetyAlert` já captura o alerta, o override e o desfecho. Falta transformar a captura em **aprendizado** — e a checagem genérica em **conhecimento de dose por paciente, por população.**

---

*Documento de visão. Próximo: [EPICS_AND_ROADMAP.md](./EPICS_AND_ROADMAP.md) → seção "AI-Native Reframe".*

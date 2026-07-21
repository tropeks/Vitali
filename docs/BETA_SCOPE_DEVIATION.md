# Vitali — Desvio entre o escopo acordado e o beta

> **Data da auditoria:** 2026-07-21
>
> **Ambiente:** `https://vitali-demo.qtec.me`
>
> **Natureza:** auditoria de produto; "contrato" neste documento significa o acordo de
> escopo registrado no Project Brief, roadmaps e planos aprovados, não um instrumento
> jurídico.

## 1. Resumo executivo

O beta não representa hoje todo o MVP acordado. O repositório contém grande parte das
funcionalidades, mas o tenant Clínica Demo foi colocado no ar sem um plano/módulos
coerente, sem várias ativações operacionais e sem os dados ou serviços externos exigidos
pelas funcionalidades diferenciadoras.

Na prática, o beta demonstra bem **Core + EMR** e parte de **Farmácia/RH**. Ele não
demonstra de ponta a ponta **Faturamento TISS/TUSS, WhatsApp e TUSS Auto por IA**, todos
P0 no escopo do MVP. Os wedges AI-native também estão construídos, porém não estão no ar.

Este é principalmente um desvio de **empacotamento, provisionamento e go-live**, embora
existam também lacunas reais de frontend/API.

## 2. Fontes do escopo acordado

Foram consideradas fontes normativas internas:

- `docs/PROJECT_BRIEF.md`: visão validada e módulos do MVP Phase 1;
- `README.md`: funcionalidades declaradas como entregues e regras de ativação;
- `docs/EPICS_AND_ROADMAP.md`: épicos, reorientação AI-native e itens engavetados;
- `docs/AI-NATIVE-WEDGES.md`: fonte de verdade dos sete wedges e seus gates;
- `docs/PLAN_SPRINT33.md`: definição de GA e critérios de go-live do piloto;
- planos de sprint aprovados e decisões duráveis registradas para o projeto.

O MVP Phase 1 acordado possui seis blocos P0:

1. Core;
2. EMR;
3. Faturamento TISS/TUSS;
4. Farmácia/Estoque;
5. WhatsApp Patient Engagement;
6. TUSS Auto por IA.

## 3. Método e evidências

A auditoria combinou:

- navegação real, autenticada e não autenticada, no beta;
- captura de erros JavaScript e respostas HTTP `4xx/5xx`;
- execução da suíte Playwright existente contra o domínio público;
- inspeção dos módulos gravados na sessão do admin demo;
- comparação das telas com APIs, feature flags e documentos do repositório.

Resultado automatizado:

- 3/3 testes de autenticação passaram;
- 4/4 jornadas habilitadas passaram;
- 1 teste de conclusão de convite foi ignorado corretamente por depender de
  `E2E_MODE` e banco `_test`;
- jornada clínica completa passou: paciente → agenda → espera → atendimento →
  prontuário → assinatura → timeline;
- upload de formulário, contratação de médico e criação de convite passaram.

Os testes criaram somente registros identificáveis como E2E no tenant Clínica Demo.

## 4. Matriz do desvio do MVP

| Bloco acordado | Existe no código | Exposto no beta | Operacional no beta | Desvio observado |
|---|---:|---:|---:|---|
| Core — pacientes, agenda, usuários, tenant | Sim | Sim | Sim | Fluxos principais passaram. |
| EMR — encontro, evolução, prescrição, assinatura | Sim | Sim | Sim | Jornada crítica passou; é a parte mais representativa do beta. |
| Faturamento TISS/TUSS | Sim | Menu visível | Não | Todas as rotas `/billing/*` redirecionam para `/dashboard`; `billing` não consta no cookie `active_modules` do admin demo. |
| Farmácia/Estoque | Sim | Sim | Parcial | Telas e upload funcionam, mas `pharmacy` não consta no cookie `active_modules`; estado de habilitação diverge entre superfícies. |
| WhatsApp Patient Engagement | Sim | Configuração visível | Não | `/api/v1/whatsapp/health/` retorna `401`; o serviço Evolution API foi reportado reiniciando. |
| TUSS Auto por IA | Sim | Configuração genérica | Não comprovado | `ai_tuss` consta ativo, mas não foi possível demonstrar sugestão real de ponta a ponta; depende também de chave, DPA e dados TUSS. |

### Estado de módulos observado na sessão

O cookie do admin demo declarou somente:

```text
emr
ai_scribe
ai_tuss
ai_prescription_safety
ai_cid10
```

Ao mesmo tempo, a navegação mostrou Farmácia, RH e Faturamento. Isso revela duas fontes
de verdade divergentes: o menu consulta `/api/v1/features/`, enquanto layouts como o de
faturamento consultam `vitali_user.active_modules`. O resultado é uma feature anunciada
no menu que redireciona silenciosamente quando aberta.

## 5. Funcionalidades construídas, mas não colocadas no ar

Os sete wedges constam como entregues no master, todos `OFF` por padrão:

| Wedge | Situação necessária para operar | Situação do beta |
|---|---|---|
| Dose safety | Flag + formulário validado por farmacêutico | Formulário de teste foi importado; validação humana e ativação não comprovadas. |
| Glosa interception | Faturamento + flag + dados TUSS/contratuais | Bloqueado pela ausência do módulo de faturamento operacional. |
| Stockout prediction | Flag + parâmetros de suprimento + histórico | Tela existe; ativação e histórico suficientes não comprovados. |
| Deterioração NEWS2 | Flag + protocolo clínico de escalonamento | Tela existe, mas ativação/governança não comprovadas. |
| Alergia e interação | Flag + tabelas curadas | Configuração existe; interceptação real não comprovada. |
| No-show prediction | Flag + Celery Beat saudável + histórico mínimo | Tela existe; `celery-beat` foi reportado unhealthy. |
| Controlados/diversion | Flag + operação e dados históricos | Tela de controlados existe; wedge não demonstrado. |

As features `ai_scribe`, `ai_tuss`, `ai_prescription_safety` e `ai_cid10` aparecerem no
cookie não basta para considerá-las operacionais. A própria documentação exige flags
globais, configuração por tenant, DPA assinado e, conforme o caso, chave de provedor e
dados humanos validados.

## 6. Lacunas funcionais confirmadas

### 6.1 Privacidade/LGPD sem backend correspondente

A tela `/configuracoes/privacidade` chama
`/api/v1/tenant/privacy-settings/`, rota que não existe no backend. O carregamento recebe
`404` e o salvamento não pode funcionar.

### 6.2 WhatsApp chama health check sem autenticação válida

A tela `/configuracoes/whatsapp` usa `fetch` direto para
`/api/v1/whatsapp/health/`. O endpoint exige autenticação e retorna `401`. A tela deve usar
o cliente autenticado comum, além de depender de uma instância Evolution saudável.

### 6.3 Telas de plataforma expostas no tenant errado

As páginas `/platform/monitor`, `/platform/tenants` e `/platform/wedge-value` puderam ser
abertas pelo admin da clínica, mas suas APIs só estão roteadas no schema público e
retornaram `404` no domínio da Clínica Demo.

O `bootstrap_beta` cria o admin da clínica com `create_superuser`. Isso conflita com a
política documentada em `apps.core.permissions`: superuser deve ser reservado ao operador
da plataforma, nunca ao usuário do tenant. Essa escolha explica a mistura de superfícies
de clínica e plataforma.

### 6.4 Ausência de assinatura/plano do tenant

O frontend chamava `/api/v1/core/subscription/`, embora a rota real seja
`/api/v1/subscription/`, e recebia `404`. Além desse erro de integração, o tenant não
possuía o plano/módulos necessários para representar o MVP acordado.

### 6.5 Provisionamento ainda não satisfaz a definição de GA

O Sprint 33 define GA como clínica provisionada com plano/módulos ativos, faturamento
TISS rodando, Wave 1 de wedges ligada, métricas visíveis, smoke e rollback. O bootstrap
atual cria tenants, domínios, papéis e admin, mas não cria/associa plano, subscription,
feature flags, DPA, dados iniciais nem valida integrações. Portanto, “stack no ar” não
equivale à saída de GA acordada.

## 7. Itens que não devem ser classificados como desvio do MVP Phase 1

Para evitar inflação de escopo, os seguintes itens não são falta do MVP Phase 1:

- DICOM/PACS e BI completo: Phase 2;
- portal do paciente, telemedicina, smart scheduling e AI Farmácia: Phase 3;
- app mobile, telemedicina WebRTC e Superset: explicitamente engavetados/depriorizados;
- internacionalização completa: evolução posterior, não bloqueio do piloto atual.

Esses itens podem existir parcialmente no código sem obrigação de estarem demonstráveis
neste beta.

## 8. Prioridade de correção

### P0 — fazer o beta representar o MVP acordado

1. Corrigir `bootstrap_beta` para criar admin de clínica sem `is_superuser`.
2. Criar plano/subscription da Clínica Demo e ativar explicitamente `emr`, `billing`,
   `pharmacy`, `whatsapp` e os módulos necessários de RH/analytics.
3. Unificar a fonte de verdade de módulos usada por cookie, menu, layouts e backend.
4. Fazer o smoke completo incluir guia TISS/lote e sugestão TUSS real.
5. Estabilizar Evolution API e autenticação do health check.

### P1 — remover funcionalidades falsas ou quebradas

1. Implementar a API de privacy settings ou retirar a tela até existir contrato de API.
2. Separar conta/domínio de operador da plataforma da conta/domínio da clínica.
3. Tratar “sem assinatura” sem erro de console e com ação operacional clara.
4. Mostrar estados explícitos “módulo não contratado”, “integração não configurada” e
   “aguardando dado validado”, em vez de redirecionar ou exibir telas vazias.

### P2 — ativar os diferenciais de forma segura

1. Confirmar DPA e provedores de IA.
2. Ligar primeiro os wedges sem dependência de verdade externa, conforme runbook.
3. Carregar e validar formulário, TUSS/contratos e parâmetros de suprimento.
4. Tornar Celery Beat saudável e verificar jobs de no-show/stockout.
5. Instrumentar as métricas de sucesso previstas no Sprint 33.

## 9. Critério de encerramento deste desvio

O desvio pode ser considerado encerrado quando um usuário da Clínica Demo, sem acesso de
superuser de plataforma, conseguir executar no beta:

1. login e gestão básica da clínica;
2. paciente → agenda → atendimento → prescrição/assinatura;
3. estoque/dispensação;
4. guia TISS → lote → validação/glosa;
5. configuração e health check do WhatsApp;
6. uma sugestão TUSS real;
7. pelo menos a Wave 1 de wedges acordada, com flags, jobs e métricas verificados;
8. smoke documentado sem `401`, `404`, redirecionamentos silenciosos ou erros de console
   nas superfícies que fazem parte do plano ativo.

## 10. Remediação implementada em código

> **Estado:** implementada e testada localmente em 2026-07-21; ainda requer build/deploy
> e rerun do bootstrap no ambiente beta para validação externa.

- `bootstrap_beta` agora cria o admin clínico sem `is_superuser`, repara o admin legado,
  garante membership, plano, subscription, módulos e flags de forma idempotente;
- pacote beta padrão reconciliado com `emr`, `billing`, `pharmacy`, `whatsapp`, `ai_tuss`,
  `analytics` e `rh`; wedges continuam OFF salvo seleção operacional explícita;
- menu e gates de rota passaram a consultar `/api/v1/features/` como fonte canônica,
  com cache isolado por usuário e comportamento fail-closed;
- faturamento deixou de usar o snapshot de módulos gravado no cookie de login;
- proxy server-side de assinatura corrigida para a rota real `/api/v1/subscription/` e
  ausência esperada de assinatura normalizada para estado vazio sem erro no navegador;
- criada API autenticada e tenant-scoped de privacy settings, reutilizando os campos de
  DPO e o fluxo auditado de assinatura DPA existentes;
- chamadas da configuração WhatsApp passaram a usar o cliente autenticado comum.

Verificações desta remediação:

- backend direcionado: 8 testes passaram;
- frontend direcionado: 10 testes passaram;
- TypeScript e ESLint direcionado: passaram;
- Ruff check/format: passaram sem cache local.

### Pendências operacionais após o código

1. construir/publicar as imagens e fazer deploy no beta;
2. executar `bootstrap_beta` novamente para reconciliar o tenant existente;
3. estabilizar e validar a Evolution API;
4. confirmar chaves globais dos provedores de IA;
5. assinar o DPA pelo fluxo apropriado;
6. obter validação farmacêutica e carregar somente dados clínicos aprovados;
7. ativar wedges por runbook e validar Celery Beat/jobs;
8. repetir a auditoria externa e o smoke expandido.

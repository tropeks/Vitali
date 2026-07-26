# Vitali — Arquitetura de Informação & Navegação (IA)

> **Status: DECISÃO DE DESIGN — a seguir no dev.** Deriva de `CANONICAL_FEATURE_MAP.md` (draft v0.2, pós-revisão
> adversarial Codex). Mockups visuais: Artifact "Vitali — Mapa de Navegação & Layouts"
> (https://claude.ai/code/artifact/f6e7aa8c-5ce5-41bb-a110-ea8a6d036c4b). Quando o código divergir daqui,
> atualizar este doc com justificativa — não decidir IA no achismo.

## 1. Decisão de padrão de navegação

O menu lateral (`DashboardShell` sidebar) é a **espinha certa**, mas a lista plana atual de ~16 itens **não
escala** e mistura clínico + back-office + admin no mesmo nível. Evoluir para um **shell híbrido**:

| Peça | Decisão |
|---|---|
| **Sidebar** | Mantido como lançador de módulos, mas **agrupado por domínio, colapsável** — não lista plana. |
| **Workspace do paciente** | O trabalho clínico vive **dentro** do paciente/encontro, com **abas de atividade próprias** (Evolução, Prescrição, SAE, Sinais, Resultados, Alta) + **storyboard** lateral (resumo do paciente). Separado do lançador global. (padrão Epic/Tasy) |
| **Command palette** | Busca global **"Ir para…" (⌘K)** — pular pra paciente / exame / guia / feature. Essencial em HIS denso. |
| **Presets por persona** | Médico / Enfermagem / Recepção / Faturamento / Farmácia / Gestão reordenam e colapsam grupos. O sidebar já filtra por módulo (tier) + permissão; presets são a camada de UX por cima. |
| **Painel de Setor** | Superfície do **supervisor/coordenador**, escopo por unidade — onde escala/dimensionamento/requisição vivem (ver §3). |

Rejeitados como base: sidebar plano (não escala), top-nav puro (topo lota), command-first sozinho (é complemento).

## 2. Grupos do sidebar (IA proposta)

Ordem e agrupamento do `NAV_ITEMS`, com gating por módulo/permissão/persona:

1. **Atendimento** (clínico) — Pacientes, Agenda, Sala de espera, Deterioração, Faltas · *(o Prontuário abre o workspace do paciente, §4)*
2. **Apoio Diagnóstico** — Laboratório, Vitali Imagem
3. **Pessoas & Operações** — RH central (cargos, lotação, afastamentos, dependentes, ponto/ASO) · **Painel de Setor** (escala, dimensionamento, trocas/folgas, requisição por setor, indicadores)
4. **Financeiro** — Faturamento (guias/glosas/pacotes/repasse), Análise/BI, **Financeiro (contas a pagar/receber, DRE, conciliação)**
5. **Suprimentos & Farmácia** — Farmácia, Estoque, Compras
6. **Concessão** `TIER diagnostic_concession` — Ativos, Contratos, Logística, Manutenção, P&L
7. **Administração** — Organização, Identidade (MPI), Aprovações, Configurações
8. **Plataforma** (superuser/dono do SaaS) — Tenants, Planos, **Toggle de módulo/tier**, Governança de terminologia, Monitor

## 3. Onde a Escala mora (correção de ownership)

**Escala/plantão NÃO é RH central — é do supervisor/coordenador de setor** (enfermeiro-chefe / coordenador
médico), escopo **unidade**. RH central **consome** (ponto, banco de horas, adicional noturno, repasse), não
origina. Modelo **híbrido** (ver `CANONICAL_FEATURE_MAP.md` §E): setor cria/publica/aprova, coordenação aprova
regras/dimensionamento, central pode balancear flutuantes, RH downstream, funcionário em self-service; RBAC por
área (`roster.manage`), não `hr.manage` global.

Hoje está **errado**: `/rh/escalas` gated `adminOnly` + `HRAccessPermission`; `DutyRoster→Facility` e `slot.unit`
opcional (sem escopo setorial real); sem swap/open-shift/publicação; plantão noturno 19h–07h nem é representável
(`end_time>start_time`). → mover para **Painel de Setor** com escopo e permissão próprios.

## 4. Workspace do paciente (abas)

Ao abrir um paciente/encontro, a navegação global some e entra o **contexto clínico**:
- **Storyboard** (rail): nome/idade/MRN, alergias (destaque), sinais vitais recentes, NEWS2, problemas.
- **Abas de atividade**: Evolução (SOAP) · Prescrição (CPOE) · SAE · Sinais · Resultados · **Reconciliação** · Alta.
- Botão "voltar aos módulos" para o lançador global.

## 5. Mapa feature → menu (resumo; detalhe no Artifact e no feature-map)

Movimentos que a revisão adversarial destravou (features que **já existem** mas estavam escondidas ou no lugar errado):

| Feature | Hoje | Ação |
|---|---|---|
| Escala/plantões | `/rh/escalas` (RH-admin) | ➜ **Painel de Setor** (`roster.manage`, escopo unidade) |
| Requisição de insumos por setor | fluxo dentro da Concessão | ➜ generalizar p/ Painel de Setor + almoxarifado |
| Reconciliação medicamentosa | backend existe, sem UI exposta | ➜ aba no workspace do paciente |
| Pacotes · repasse a terceiros · CBHPM | backend existe, marcado "falta" no doc antigo | ➜ expor em Financeiro |
| Financeiro (contas a pagar/receber, DRE, conciliação) | backend substancial, sem entrada no menu | ➜ item "Financeiro" |
| Plataforma (toggle de tier, terminologia) | acessível só por URL | ➜ seção **Plataforma** dedicada (superuser) |

## 6. Visibilidade do menu = RBAC (não achismo)

O que aparece no menu é decidido por **três gates**, nesta ordem, e **todos são UX — a segurança real é o
`permission_classes` do backend** (defense in depth; nunca esconder menu como controle de acesso):

1. **Módulo/Tier** — `useActiveModules()` (FeatureFlag por tenant). Item some se o tenant não tem o módulo.
2. **Permissão RBAC** — `item.permissions[]` × `user.permissions` (`.some`). **Este é o gate correto e deve ser o dominante.**
3. **Persona (preset)** — camada SOFT que reordena/colapsa grupos dentro do que 1+2 já liberam; **nunca amplia acesso**.

**Correções (entram na S-IA1):**
- **Aposentar o `adminOnly`** (que olha `role_name`) e trocar por permissão real por item. `role_name` é sinal
  user-settable — o backend já foi endurecido pra NÃO confiar nele (A01/CSO, `HRAccessPermission`); o front tem que seguir.
- **Catálogo canônico de permissões** (fonte única) — hoje as strings (`emr.read`, `hr.manage`, `workflow.request`…)
  estão espalhadas. Criar um registro para mapear nav↔permissão e Role↔permissões sem ambiguidade.
- **Mapear cada item de menu → permissão(ões)**: ex. Escala → `roster.manage`; Financeiro → `billing.read`;
  Plataforma → `is_platform_admin`/superuser (gate no client também, não só backend).
- **Fail-safe correto**: enquanto carrega, `module` é fail-open (evita flicker) mas **permissão nunca deve ser
  fail-open** — na dúvida, não mostrar. Backend continua sendo a barreira dura.

## 7. Backlog de implementação (ondas — curso corrigido)

- **S-IA1 · Nav shell + RBAC + expor o que já existe** (frontend): `DashboardShell` agrupado colapsável;
  **visibilidade RBAC-por-permissão (§6): aposentar `adminOnly`, mapear item→permissão, catálogo canônico,
  seção Plataforma gated por superuser**; adicionar ao menu os módulos já construídos que têm página (e listar
  os backend-only p/ a S-IA1b). *Barato, alto valor — corrige o "reconstruímos o que já existia" + o gate por role_name.*
- **S-IA2 · Escala → Painel de Setor** (backend+frontend): permissão `roster.manage`, escopo por unidade
  (object-level), suporte a plantão que cruza meia-noite, swap/folga self-service; mover a rota. *Fecha a pergunta original.*
- **S-IA3 · Command palette (⌘K)** + presets por persona.
- **S-IA4 · Workspace do paciente** (storyboard + abas) — reorganiza `/encounters/[id]`.

> Régua de estado: enquanto o feature-map não migrar para maturidade-por-camada, usar tem/parcial/falta com a
> ressalva code-verified. Toda feature nova declara `persona × escopo` + RBAC + onde entra nesta IA.

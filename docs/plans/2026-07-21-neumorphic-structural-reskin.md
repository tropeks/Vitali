# Plano: Reskin Neumórfico Estrutural (fase pós-triagem)

**Data:** 2026-07-21 · **Autor:** Claude (sessão fanout) · **Status:** em execução
**Contexto:** auditoria de 21/07 — 41/59 páginas têm classes neumórficas, mas via literais copy-paste em 48 arquivos; zero token layer; `DashboardShell` (chrome de 100% das páginas autenticadas) segue flat; sem primitivas Button/Badge; 18 páginas intocadas; DESIGN.md (flat) não marcado superseded vs `docs/FRONTEND_GUIDELINES.md` (neumórfico, golden standard de fato).

**Princípios:** tarefas bite-sized com verificação própria; YAGNI (nada de theming dark/multi-brand agora); nunca quebrar `tsc`/`next lint`/`next build`; migração aditiva (tokens primeiro, consumo depois); um subagente por tarefa com brief fechado; revisão por wave.

**Fonte da verdade dos valores:** `docs/FRONTEND_GUIDELINES.md` (cores `#DFE5EB/#EBF0F5/#F4F7FA/#E8EDF2`, tinta `#24292F/#57606A/#8C959F`, brand `#0066A1→#005282` + edge `#3385b5`, sombras inset/btn/panel/elevated).

## Fase 1 — Token layer (aditiva, zero mudança visual)
- **T1.1** `tailwind.config.ts`: `theme.extend.colors.neu.*` (app, outer, panel, panelAlt, input, ink, inkSoft, inkMuted, brand, brandDeep, brandEdge, success, danger) + `theme.extend.boxShadow` (`neu-inset`, `neu-btn`, `neu-btn-primary`, `neu-btn-primary-hover`, `neu-panel`, `neu-elevated`, `neu-modal`).
- **T1.2** `globals.css` `@layer components`: `.neu-input`, `.neu-label`, `.neu-btn-primary`, `.neu-btn-secondary`, `.neu-panel` — composições exatas dos snippets do guidelines. Wire do body: `bg` → token `neu-app` (`#DFE5EB`) **somente** no layout autenticado (não tocar portal/login nesta fase).
- **Verificação:** `npx tsc --noEmit` + `npx next lint` + `npx next build` verdes; diff visual esperado: apenas o fundo do app autenticado.
- **Modelo:** Fable (fundacional, poucas linhas, alto custo de errar).

## Fase 2 — DashboardShell (maior alavancagem)
- **T2.1** Converter `frontend/components/layout/DashboardShell.tsx` (sidebar, topbar, nav ativa, dropdown) para tokens/classes da Fase 1, seguindo §sidebar/§chrome do guidelines. Não mudar estrutura/aria/testids (E2E navega por ele).
- **Verificação:** build verde + screenshot comparativo via browser headless no staging pós-deploy; specs E2E `auth`/`clinical-journey` passam (rodam no CI do PR).
- **Modelo:** Fable.

## Fase 3 — Primitivas compartilhadas
- **T3.1** Criar `components/shared/Button.tsx` (variants primary/secondary/danger a partir de `.neu-btn-*`) e `components/shared/Badge.tsx`.
- **T3.2** Converter `StatusBadge.tsx` (semáforo de status — manter mapa semântico atual) e alinhar `TONE_CLASSES` de `lib/operational-ui.ts` aos tokens.
- **Verificação:** tsc/lint/build; grep: nenhum novo literal `#hex` introduzido.
- **Modelo:** Fable para T3.2 (semântica de status clínico); Sonnet para T3.1.

## Fase 4 — Migração mecânica literal→token (48 arquivos)
- **T4.x** Batches por diretório com conjuntos de arquivos DISJUNTOS (sem git nos agentes; só Edit — commits centralizados pelo orquestrador). Regra: substituir apenas literais que casem 1:1 com token; divergências (ex. `#1f2937` vs `#24292F`) normalizam para o token; nada de redesign.
- **Verificação por batch:** tsc + lint; grep de resíduo (`bg-\[#`, `shadow-\[`) decrescente; build no fim da fase.
- **Modelo:** Sonnet (effort low), ~4-6 agentes paralelos.

## Fase 5 — 18 páginas intocadas
- waiting-room, deterioracao, faltas, configuracoes/* (6), auth password (2), platform/monitor, profile/security, rh/funcionarios, wedges/telemetry, root page. Uma tarefa por página usando SOMENTE tokens/primitivas (Fases 1-3) e os padrões §forms/§tables/§toolbar do guidelines.
- **Verificação:** tsc/lint/build por wave + QA visual headless das rotas no staging.
- **Modelo:** Sonnet; páginas densas (waiting-room, deterioracao) → Opus.

## Fase 6 — Reconciliação documental
- **T6.1** Marcar `DESIGN.md` como SUPERSEDED (banner no topo apontando para FRONTEND_GUIDELINES.md + este plano), preservando o histórico.
- **T6.2** Landar `docs/design/design-ab-flat-vs-neumorphic.html` como decision record (link no banner).
- **Modelo:** Sonnet.

## Entrega
Cada fase = 1 PR (`feat/neu-tokens`, `feat/neu-shell`, `feat/neu-primitives`, `refactor/neu-token-migration`, `feat/neu-pages-wave{1,2}`, `docs/design-reconciliation`), CI verde + merge antes da fase seguinte (fases 4-5 podem paralelizar após a 3). Rollback = revert do PR da fase.

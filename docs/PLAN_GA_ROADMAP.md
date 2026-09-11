# Vitali — Roadmap to GA (Sprints 27–33)

> Gerado em 2026-06-12 a partir do estudo completo de docs + código (estado: Sprint 26 shipped, v1.0.0).
> **Como usar:** cada `PLAN_SPRINT{N}.md` é autocontido e dimensionado para UMA sessão de execução com Claude (Sonnet). Execute em ordem; não pule dependências. Antes de cada sprint, leia este arquivo + o plano do sprint + os arquivos citados na seção Context do plano.

## Definição de "produto final" (GA)

Primeira clínica piloto **pagante** operando em produção com:

1. Infra de produção sólida (TLS, backups offsite testados, secrets, monitoring, DR documentado)
2. Isolamento de tenant ENFORÇADO (`ENFORCE_TENANT_MEMBERSHIP=ON`)
3. **Receita provada:** guia TISS válida → lote → faturamento, com os catálogos governados
   carregados por caminho reproduzível
4. **Recuperação provada:** backup produzido, restaurado e conferido — não documentado
5. Compliance fechado para operação real (LGPD frontend, DPA, MFA enforced, assinatura ICP integrada)
6. Processo de onboarding de tenant repetível

> ### Emenda de 2026-09-11 — os 7 wedges saem da definição de GA
>
> **O que muda:** os 7 wedges AI-native LIGADOS eram o item 3 desta definição. Deixam de ser
> critério de GA e passam a **fase pós-GA, condicionada a "fatura e restaura provados"** —
> os novos itens 3 e 4 acima. As sprints S30 e S31 continuam onde estão; o que muda é que
> **elas não travam o GA**, e não começam antes de 3 e 4 estarem fechados.
>
> **Por quê:** `.maestro/INTENT.md` **v4**, §Prioridades, ordena receita (2) e recuperação
> provada (3) **antes** de interceptação (4). Onde o roadmap e a direção divergem, a direção
> manda. Um wedge que intercepta erro clínico sobre um sistema que não fatura e não sabe se
> consegue restaurar é demonstração, não produto — e é a parte mais fácil de mostrar e a mais
> cara de sustentar.
>
> **Medido, não suposto** (11/09): o pipeline de backup do staging **nunca produziu um
> backup** — `backup.sh` falha fechado por falta de `BACKUP_ENCRYPTION_KEY`, e o `crond` do
> container nem chegava a disparar no host antigo. E a Prioridade 2 segue aberta enquanto
> `CBHPMItem` estiver em zero, que é decisão de compra. Ver
> `docs/research/VITALI_CATALOGOS_ESTADO_REAL.md` e `.maestro/orders/001-*.md` §10.
>
> **Quem decidiu:** Imediato, em 11/09, com o Capitão informado por ele. Se o Capitão
> discordar, **reverte-se esta emenda, não o INTENT** — a direção é o documento superior; este
> é o que se ajusta a ela.

## Estado atual (resumo)

- **v1.0.0**, 26 sprints shipped. 17 apps Django / 78 modelos / 848+ testes. Next.js 15.5 / 53 páginas / 4 suítes E2E.
- 7 wedges AI **built, flags OFF** ("Built ≠ Live"): `dose_safety`, `glosa_safety`, `stockout_safety`, deterioration (NEWS2), no-show, allergy, controlled-diversion.
- Tenant isolation Model B completa (PRs #106–109); flag `ENFORCE_TENANT_MEMBERSHIP` default OFF.
- Staging na lab da Vulcan (`vitali.qtec.me` / `vitali-demo.qtec.me`, ordem 001, 11/09).
  **Não há deploy automático:** os três workflows só constroem e publicam imagem — o deploy
  é humano, por `docs/DEPLOY.md`. Produção ainda não provisionada.

## Sequência e dependências

```
S27 Ops Foundation ──────────────┐
S28 Enforcement & Security ──────┤
S29 Data Curation Tooling ───────┤
                                 ├──► S32 Compliance Pack GA
RECEITA PROVADA   (ordem 002) ───┤         │
RECUPERACAO PROVADA (chave de    │         ▼
   backup + drill) ──────────────┴──► S33 Pilot Onboarding & GTM ──► GA: piloto pagante live
                                           │
                                           ▼ (POS-GA, emenda 11/09)
                             S30 Wedges Wave 1 ──► S31 Wedges Wave 2
                                  [HUMANO: farmaceutico D-T1, import ANS, config supr.]
```

**O que mudou no diagrama (emenda 11/09):** S30 e S31 saíram do caminho crítico do GA e
foram para depois dele. Entraram no lugar as duas provas que o INTENT v4 põe antes de
interceptação: **receita provada** (ordem 002 — catálogos por caminho reproduzível) e
**recuperação provada** (chave de backup provisionada + drill executado). S29 continua onde
estava: ele constrói ferramenta de curadoria, que serve aos dois lados.

| Sprint | Tema | Dependências | Bloqueio humano? |
|--------|------|--------------|------------------|
| 27 | Production Ops Foundation | — | Credenciais S3/Cloudflare do Romulo |
| 28 | Tenant Enforcement + Security Hardening | — | Não |
| 29 | Data Curation Tooling | — | Não (constrói ferramentas; carga de dados é depois) |
| 30 | Wedge Go-Live Wave 1 | 27 (staging sólido) + **receita e recuperação provadas (emenda 11/09)** | Não — wedges 100% derivados de histórico |
| 31 | Wedge Go-Live Wave 2 | 29 + dados curados carregados | **SIM**: farmacêutico valida formulário (D-T1); import ANS |
| 32 | Compliance Pack GA | — (paralelo ok) | Revisão jurídica da privacy policy (recomendado) |
| 33 | Pilot Onboarding & GTM | 27–32 | Clínica piloto selecionada |

## Regras de execução (para a sessão Sonnet)

1. **Leia antes de editar.** Cada plano lista arquivos de contexto. O projeto tem CLAUDE.md com regras GitNexus (impact analysis antes de editar símbolos) — siga-as se o MCP gitnexus estiver disponível; senão, leia os callers manualmente antes de mudar assinaturas.
2. **Convenções do repo:** commits `feat(app): ...` / `fix(app): ...`; um PR por sprint (ou por item grande); testes pytest no backend (`pytest --reuse-db`), vitest + Playwright no frontend.
3. **Nunca invente números clínicos/contratuais/ANS.** É princípio de produto (ver `docs/AI-NATIVE-WEDGES.md`). Tooling carrega dados; humanos validam.
4. **Feature flags por tenant** (`FeatureFlag` model) — wedges ligam por tenant, nunca globalmente hardcoded.
5. **Multi-tenant:** migrations via `migrate_schemas`; tasks Celery iteram schemas (padrão do Sprint 26). Qualquer query nova em task periódica DEVE usar `schema_context`.
6. **Gates de CI:** mypy, ruff, pytest, vitest, Playwright E2E, `makemigrations --check --dry-run`, docker compose config — tudo blocking. Rode localmente antes do PR.
7. Ao final de cada sprint: atualizar `CHANGELOG.md`, marcar o plano como SHIPPED (editar o `PLAN_SPRINT{N}.md` com o que foi entregue de fato), salvar estado no supermemory.

## Fora do roadmap GA (Fase 3, pós-piloto)

- **Os 7 wedges AI-native LIGADOS (S30/S31)** — movidos para cá pela emenda de 11/09,
  condicionados a "fatura e restaura provados". Continuam sendo o diferencial do produto;
  deixam de ser critério de GA.
- i18n completo (scaffolding existe, catálogos vazios)
- App mobile React Native (backend primitives prontos)
- Telemedicina WebRTC (state machine pronta)
- Apache Superset BI embarcado
- Certificação formal SBIS/CFM (iniciar processo durante piloto)
- Per-item glosa labels (bloqueado por ANS TISS 4.02+)

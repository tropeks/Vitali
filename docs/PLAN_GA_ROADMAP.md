# Vitali — Roadmap to GA (Sprints 27–33)

> Gerado em 2026-06-12 a partir do estudo completo de docs + código (estado: Sprint 26 shipped, v1.0.0).
> **Como usar:** cada `PLAN_SPRINT{N}.md` é autocontido e dimensionado para UMA sessão de execução com Claude (Sonnet). Execute em ordem; não pule dependências. Antes de cada sprint, leia este arquivo + o plano do sprint + os arquivos citados na seção Context do plano.

## Definição de "produto final" (GA)

Primeira clínica piloto **pagante** operando em produção com:

1. Infra de produção sólida (TLS, backups offsite testados, secrets, monitoring, DR documentado)
2. Isolamento de tenant ENFORÇADO (`ENFORCE_TENANT_MEMBERSHIP=ON`)
3. Os 7 wedges AI-native LIGADOS (flags ON com dados validados — o diferencial do produto)
4. Compliance fechado para operação real (LGPD frontend, DPA, MFA enforced, assinatura ICP integrada)
5. Processo de onboarding de tenant repetível

## Estado atual (resumo)

- **v1.0.0**, 26 sprints shipped. 17 apps Django / 78 modelos / 848+ testes. Next.js 15.5 / 53 páginas / 4 suítes E2E.
- 7 wedges AI **built, flags OFF** ("Built ≠ Live"): `dose_safety`, `glosa_safety`, `stockout_safety`, deterioration (NEWS2), no-show, allergy, controlled-diversion.
- Tenant isolation Model B completa (PRs #106–109); flag `ENFORCE_TENANT_MEMBERSHIP` default OFF.
- Staging com deploy automático via GitHub Actions; produção ainda não provisionada.

## Sequência e dependências

```
S27 Ops Foundation ──────────────┐
S28 Enforcement & Security ──────┤
S29 Data Curation Tooling ───────┼──► S30 Wedges Wave 1 (sem dados curados)
                                 │        │
   [HUMANO: farmacêutico D-T1,   │        ▼
    import ANS, config supr.] ───┴──► S31 Wedges Wave 2 (com dados curados)
                                          │
S32 Compliance Pack GA ◄──────────────────┘ (paralelo possível com S30/S31)
                                          │
                                          ▼
S33 Pilot Onboarding & GTM ──► GA: piloto pagante live
```

| Sprint | Tema | Dependências | Bloqueio humano? |
|--------|------|--------------|------------------|
| 27 | Production Ops Foundation | — | Credenciais S3/Cloudflare do Romulo |
| 28 | Tenant Enforcement + Security Hardening | — | Não |
| 29 | Data Curation Tooling | — | Não (constrói ferramentas; carga de dados é depois) |
| 30 | Wedge Go-Live Wave 1 | 27 (staging sólido) | Não — wedges 100% derivados de histórico |
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

- i18n completo (scaffolding existe, catálogos vazios)
- App mobile React Native (backend primitives prontos)
- Telemedicina WebRTC (state machine pronta)
- Apache Superset BI embarcado
- Certificação formal SBIS/CFM (iniciar processo durante piloto)
- Per-item glosa labels (bloqueado por ANS TISS 4.02+)

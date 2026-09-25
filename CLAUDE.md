# gstack

Use the `/browse` skill from gstack for headless QA, dogfooding, and tasks where the visible browser doesn't matter. The `mcp__Claude_in_Chrome__*` tools are also allowed when you need to drive the user's actual logged-in Chrome (e.g. authenticated GitHub UI without re-importing cookies).

Available gstack skills:
- `/office-hours` — structured async Q&A / brainstorm session
- `/plan-ceo-review` — prepare a plan for CEO-level review
- `/plan-eng-review` — prepare a plan for engineering review
- `/plan-design-review` — prepare a plan for design review
- `/design-consultation` — get design feedback and recommendations
- `/review` — code review
- `/ship` — full ship workflow (review → QA → deploy)
- `/land-and-deploy` — land a PR and deploy it
- `/canary` — canary deployment workflow
- `/benchmark` — run performance benchmarks
- `/browse` — browse the web (use this instead of mcp__claude-in-chrome__*)
- `/qa` — full QA pass (with browsing)
- `/qa-only` — QA pass only (no deploy)
- `/design-review` — design review workflow
- `/setup-browser-cookies` — configure browser auth cookies
- `/setup-deploy` — configure deployment settings
- `/retro` — run a retrospective
- `/investigate` — investigate a bug or incident
- `/document-release` — document a release
- `/codex` — run codex tasks
- `/cso` — chief of staff operations
- `/careful` — careful/slow mode for high-risk changes
- `/freeze` — freeze deployments
- `/guard` — enable deployment guard
- `/unfreeze` — unfreeze deployments
- `/gstack-upgrade` — upgrade gstack to latest version

If gstack skills aren't working, run the following to build the binary and register skills:

```sh
cd .claude/skills/gstack && ./setup
```

## Health Stack

**A forge não roda compose do Vitali** (regra do Imediato, 17/09/2026). Nem para rodar a
suíte, nem "só um minuto": o compose publica portas que passam por fora do firewall da
forge, e ela guarda segredos que não são do Vitali. Os comandos de backend abaixo rodam
**no CI** (jobs `Backend — Lint & Types` e `Backend — Tests`, em push para `order/**` e em
PR contra `onda0-perimetro-multitenant`) ou **na lab**, pelo contexto docker `lab`, com
contêineres sem porta publicada. A receita da lab, e por que cada flag é obrigatória, está
em `docs/DEVELOPMENT.md` §Running tests.

Tools that `/health` runs:

- typecheck (backend): `mypy apps/ vitali/ --ignore-missing-imports` (CI ou lab)
- lint (backend): `ruff check apps/ vitali/` (CI ou lab)
- format-check (backend): `ruff format --check apps/ vitali/` (CI ou lab)
- test (backend): `pytest -v` (CI ou lab; na lab, com o overlay de `scripts/` e
  `COVERAGE_FILE=/tmp/.coverage`)
- typecheck (frontend): `cd frontend && npx tsc --noEmit`
- lint (frontend): `cd frontend && npx next lint`
- test (frontend): `cd frontend && npm test` (vitest; o CI tem portão nele desde a ordem 012)

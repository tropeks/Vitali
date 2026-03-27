# gstack

Use the `/browse` skill from gstack for all web browsing. Never use `mcp__claude-in-chrome__*` tools directly.

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

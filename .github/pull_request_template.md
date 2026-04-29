<!-- Keep this short. If it doesn't fit in the PR body, it's too big — split it. -->

## What

<!-- 1-2 sentences. What changed and why. Link the sprint story (S-NNN) if applicable. -->

## Test plan

<!-- How did you verify this? Check what applies. -->

- [ ] Backend tests pass in Docker: `docker compose exec -T django python manage.py test <app.tests.test_x>`
- [ ] Frontend type-check passes: `cd frontend && npm run type-check`
- [ ] Manual smoke test in browser (describe the happy path)
- [ ] Edge cases tested (list them)

<!-- Screenshots or short video for UI changes -->

## Migrations

<!-- Delete if no migrations. Otherwise: -->

- [ ] Migration runs cleanly: `docker compose exec -T django python manage.py migrate_schemas`
- [ ] Reversible (or documented why not)
- [ ] Safe under concurrent writes (or documented why it's OK to take a brief lock)

## Risk

<!-- What's the blast radius if this is wrong? Who/what gets affected? Delete if trivial. -->

## Checklist

- [ ] Per-story PR (one story, one PR — no sprint-end squashes)
- [ ] Feature flag for risky/incomplete work
- [ ] CI is green on this branch before requesting review

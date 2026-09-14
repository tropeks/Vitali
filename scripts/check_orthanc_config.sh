#!/usr/bin/env bash
# Vitali — Orthanc config regression guard (Onda 2 / item 2.9)
# ─────────────────────────────────────────────────────────────────────────────
# Static config check (no running stack / Docker daemon needed — just parses
# the YAML). Fails when a compose file defines an `orthanc` service but the
# `django` / `celery-worker` services in that SAME file do not set a non-empty
# ORTHANC_URL — the exact regression this item fixed: settings/base.py
# defaults ORTHANC_URL to "", and empty makes the whole imaging-ingestion
# feature (webhook + Celery poller) silently inert (apps/imaging/views.py,
# apps/imaging/tasks.py) even though the orthanc container is running.
#
# Usage:
#   bash scripts/check_orthanc_config.sh                       # checks docker-compose*.yml in repo root
#   bash scripts/check_orthanc_config.sh docker-compose.yml ... # or an explicit file list
#
# Exit code: 0 when every compose file that has an `orthanc` service also sets
# ORTHANC_URL on django/celery-worker; 1 otherwise (with a description of what's
# missing). Intended to run in CI/pre-deploy alongside `docker compose config`
# validation — see docs/DEPLOY.md and docs/research/VITALI_HUMAN_APPLIED_GATES.md
# for why this repo does not wire it into .github/workflows/ itself.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [[ $# -gt 0 ]]; then
  FILES=("$@")
else
  FILES=(docker-compose*.yml)
fi

python3 - "${FILES[@]}" <<'PYEOF'
import sys

try:
    import yaml
except ImportError:
    print("check_orthanc_config: PyYAML not installed — cannot validate.", file=sys.stderr)
    sys.exit(1)

CONSUMERS = ("django", "celery-worker")

failures = []
checked = 0

for path in sys.argv[1:]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except FileNotFoundError:
        continue
    except yaml.YAMLError as exc:
        # e.g. docker-compose.test.yml uses compose-only YAML tags (!reset)
        # that plain yaml.safe_load doesn't know — not this script's concern,
        # skip rather than crash the whole check over an unrelated file.
        print(f"check_orthanc_config: skipping {path} (not parseable as plain YAML: {exc})", file=sys.stderr)
        continue
    services = (data or {}).get("services") or {}
    if "orthanc" not in services:
        continue  # this compose file doesn't run Orthanc — nothing to gate.

    for name in CONSUMERS:
        svc = services.get(name)
        if svc is None:
            continue  # e.g. dev compose has no separate service by that name
        checked += 1
        env = svc.get("environment") or {}
        value = None
        if isinstance(env, dict):
            value = env.get("ORTHANC_URL")
        elif isinstance(env, list):
            for item in env:
                if isinstance(item, str) and item.startswith("ORTHANC_URL="):
                    value = item.split("=", 1)[1]
        if not value or not str(value).strip():
            failures.append(
                f"{path}: service '{name}' has an 'orthanc' service as a sibling "
                f"but no non-empty ORTHANC_URL in its environment block."
            )

if failures:
    print("check_orthanc_config: FAIL")
    for f in failures:
        print(f"  - {f}")
    print(
        "\nFix: add `ORTHANC_URL: http://orthanc:8042` (or the correct internal "
        "service address) to the environment: block of the affected service(s). "
        "See docs/IMAGING.md and docs/DEPLOY.md."
    )
    sys.exit(1)

print(f"check_orthanc_config: OK ({checked} service(s) checked across {len(sys.argv) - 1} file(s))")
PYEOF

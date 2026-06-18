#!/usr/bin/env bash
# scripts/migrate_schemas.sh
# Idempotent script to migrate all schemas

set -euo pipefail

compose_cmd=(docker compose -f docker-compose.yml)
if [ -f "docker-compose.override.yml" ]; then
    compose_cmd=(docker compose -f docker-compose.yml -f docker-compose.override.yml)
elif [ -f "docker-compose.prod.yml" ]; then
    compose_cmd=(docker compose -f docker-compose.yml -f docker-compose.prod.yml)
fi

echo "Migrating public schema..."
"${compose_cmd[@]}" exec -T django python manage.py migrate_schemas --schema=public

echo "Migrating all tenant schemas..."
"${compose_cmd[@]}" exec -T django python manage.py migrate_schemas --executor=multiprocessing

echo "All schemas migrated successfully."

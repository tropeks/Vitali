#!/usr/bin/env bash
set -euo pipefail
SRC=/home/rcosta00/dev/vitali-worker3
cd "$SRC"
tar czf /tmp/vitali-sync.tar.gz \
  --exclude='.git' --exclude='node_modules' --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='.shrimp' --exclude='staticfiles' --exclude='media' \
  backend docker-compose.yml docker-compose.override.yml docker-compose.test.yml
sudo pct push 100 /tmp/vitali-sync.tar.gz /tmp/vitali-sync.tar.gz >/dev/null
sudo pct exec 100 -- bash -c "cd /opt/vitali && tar xzf /tmp/vitali-sync.tar.gz"
sudo pct exec 100 -- bash -c "cd /opt/vitali && docker compose -p vitali \
  -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.test.yml \
  run --rm --no-deps -e DJANGO_SETTINGS_MODULE=vitali.settings.development \
  django pytest $* -p no:cacheprovider --no-cov -q"

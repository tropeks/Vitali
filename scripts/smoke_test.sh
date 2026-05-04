#!/usr/bin/env bash
# Vitali — Post-Deploy Smoke Test
# ─────────────────────────────────────────────────────────────────────────────
# Run after every deploy to verify the stack is healthy before marking the
# deploy as successful. Exits 0 on full pass, 1 with a descriptive message
# on any failure.
#
# Usage:
#   BASE_URL=https://staging.vitali.com.br COMPOSE_FILE=docker-compose.staging.yml bash scripts/smoke_test.sh
#   BASE_URL=http://localhost bash scripts/smoke_test.sh
#
# Required env vars:
#   BASE_URL          — scheme + host, no trailing slash
#   FRONTEND_URL      — optional frontend URL, defaults to BASE_URL
#   COMPOSE_FILE      — optional compose file, defaults to docker-compose.yml
#   COMPOSE_ENV_FILE  — optional compose env file

set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost}"
FRONTEND_URL="${FRONTEND_URL:-$BASE_URL}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
COMPOSE_ENV_FILE="${COMPOSE_ENV_FILE:-}"
PASS=0
FAIL=0
ERRORS=()

compose_cmd=(docker compose -f "$COMPOSE_FILE")
if [[ -n "$COMPOSE_ENV_FILE" ]]; then
  export STAGING_ENV_FILE="$COMPOSE_ENV_FILE"
  compose_cmd+=(--env-file "$COMPOSE_ENV_FILE")
fi

# ─── Helpers ─────────────────────────────────────────────────────────────────

check() {
  local name="$1"
  local result="$2"
  local expected="$3"
  if [[ "$result" == "$expected" ]]; then
    echo "  ✓ $name"
    PASS=$((PASS + 1))
  else
    echo "  ✗ $name (got: $result, expected: $expected)"
    FAIL=$((FAIL + 1))
    ERRORS+=("$name")
  fi
}

check_contains() {
  local name="$1"
  local result="$2"
  local needle="$3"
  if echo "$result" | grep -q "$needle"; then
    echo "  ✓ $name"
    PASS=$((PASS + 1))
  else
    echo "  ✗ $name (expected to contain: $needle)"
    FAIL=$((FAIL + 1))
    ERRORS+=("$name")
  fi
}

curl_status() {
  local timeout="$1"
  local status
  shift
  if status=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$timeout" "$@"); then
    echo "$status"
  else
    echo "000"
  fi
}

curl_status_retry() {
  local timeout="$1"
  local expected="$2"
  local attempts="$3"
  local delay="$4"
  local status
  shift 4

  for attempt in $(seq 1 "$attempts"); do
    status=$(curl_status "$timeout" "$@")
    if [[ "$status" == "$expected" ]]; then
      echo "$status"
      return 0
    fi
    if [[ "$attempt" -lt "$attempts" ]]; then
      sleep "$delay"
    fi
  done

  echo "$status"
}

curl_time() {
  local timeout="$1"
  local response_time
  shift
  if response_time=$(curl -s -o /dev/null -w "%{time_total}" --max-time "$timeout" "$@"); then
    echo "$response_time"
  else
    echo "999"
  fi
}

curl_headers() {
  local timeout="$1"
  shift
  curl -s -D - --max-time "$timeout" "$@" 2>/dev/null || true
}

# ─── Check 1: Health endpoint ─────────────────────────────────────────────────

echo ""
echo "=== Smoke Test: $BASE_URL ==="
echo ""
echo "1. Backend health..."
STATUS=$(curl_status_retry 5 200 12 3 "$BASE_URL/health/")
check "GET /health/ → 200" "$STATUS" "200"

RESPONSE_TIME=$(curl_time 5 "$BASE_URL/health/")
if awk "BEGIN { exit !($RESPONSE_TIME > 0.5) }"; then
  echo "  ⚠ /health/ response time ${RESPONSE_TIME}s > 500ms (DB may be slow)"
fi

# ─── Check 2: Auth endpoint (bad creds → 401, not 500) ───────────────────────

echo ""
echo "2. Auth endpoint..."
AUTH_STATUS=$(curl_status_retry 5 401 3 2 \
  -X POST "$BASE_URL/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"smoke@test.invalid","password":"notreal"}')
check "POST /api/v1/auth/login bad creds → 401" "$AUTH_STATUS" "401"

AUTH_CT=$(curl_headers 5 \
  -X POST "$BASE_URL/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"smoke@test.invalid","password":"notreal"}' | grep -i "content-type" | head -1 || true)
check_contains "auth response Content-Type is JSON" "$AUTH_CT" "application/json"

# ─── Check 3: OpenAPI schema ──────────────────────────────────────────────────

echo ""
echo "3. OpenAPI schema..."
SCHEMA_STATUS=$(curl_status_retry 30 200 3 2 "$BASE_URL/api/schema/")
check "GET /api/schema/ → 200" "$SCHEMA_STATUS" "200"

# ─── Check 4: Frontend ────────────────────────────────────────────────────────

echo ""
echo "4. Frontend..."
FRONTEND_STATUS=$(curl_status_retry 120 200 3 2 -L "$FRONTEND_URL/")
check "GET frontend / with redirects → 200" "$FRONTEND_STATUS" "200"

# ─── Check 5: Static files ────────────────────────────────────────────────────

echo ""
echo "5. Static files..."
STATIC_STATUS=$(curl_status_retry 5 200 3 2 "$BASE_URL/static/admin/css/base.css")
check "GET /static/admin/css/base.css → 200" "$STATIC_STATUS" "200"

# ─── Check 6: Celery task execution ───────────────────────────────────────────
# Relies on a management command that enqueues a no-op task and waits for it.
# Falls back to a Redis ping if the management command is unavailable.

echo ""
echo "6. Celery task execution..."
if command -v docker >/dev/null 2>&1 && [[ -f "$COMPOSE_FILE" ]]; then
  CELERY_RUNNING=$("${compose_cmd[@]}" ps --status running --services 2>/dev/null | grep -E '^celery-worker$' || true)
  if [[ -n "$CELERY_RUNNING" ]]; then
    # Enqueue from Django and wait for the worker result through the real broker.
    if "${compose_cmd[@]}" exec -T django python manage.py shell -c "
from celery import current_app
result = current_app.send_task('apps.core.tasks.smoke_ping')
print(result.get(timeout=10))
" 2>/dev/null | grep -q "pong"; then
      check "Celery task enqueue + execute" "pong" "pong"
    else
      CELERY_INSPECT=$("${compose_cmd[@]}" exec -T celery-worker celery -A vitali inspect ping --timeout 5 2>/dev/null || echo "unreachable")
      if echo "$CELERY_INSPECT" | grep -qi "pong\|ok"; then
        check "Celery worker responds to ping" "pong" "pong"
      else
        check "Celery worker responds to ping" "unreachable" "pong"
      fi
    fi
  else
    check "Celery worker running" "not-running" "running"
  fi
else
  echo "  - Celery check skipped (Docker Compose file not available)"
fi

# ─── Check 7: HTTPS redirect (only for non-localhost) ────────────────────────

echo ""
echo "7. HTTPS redirect..."
if [[ "$BASE_URL" == http://* ]] && [[ "$BASE_URL" != *localhost* ]]; then
  REDIRECT_STATUS=$(curl_status 5 --no-location "$BASE_URL/health/")
  check "HTTP → HTTPS redirect (301)" "$REDIRECT_STATUS" "301"
else
  echo "  - HTTPS redirect check skipped (localhost or already HTTPS)"
fi

# ─── Summary ──────────────────────────────────────────────────────────────────

echo ""
echo "─────────────────────────────────────"
echo "Results: $PASS passed, $FAIL failed"

if [[ $FAIL -gt 0 ]]; then
  echo ""
  echo "FAILED checks:"
  for err in "${ERRORS[@]}"; do
    echo "  - $err"
  done
  echo ""
  echo "Deploy smoke test FAILED. Check logs: docker compose logs --tail=50"
  exit 1
else
  echo ""
  echo "All smoke tests passed. Deploy looks healthy."
  exit 0
fi

#!/usr/bin/env bash
# Vitali — Post-Deploy Smoke Test
# ─────────────────────────────────────────────────────────────────────────────
# Run after every deploy to verify the stack is healthy before marking the
# deploy as successful. Exits 0 on full pass, 1 with a descriptive message
# on any failure.
#
# Usage:
#   BASE_URL=https://staging.vitali.com.br bash scripts/smoke_test.sh
#   BASE_URL=http://localhost bash scripts/smoke_test.sh
#
# Required env vars:
#   BASE_URL   — scheme + host, no trailing slash

set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost}"
PASS=0
FAIL=0
ERRORS=()

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

# ─── Check 1: Health endpoint ─────────────────────────────────────────────────

echo ""
echo "=== Smoke Test: $BASE_URL ==="
echo ""
echo "1. Backend health..."
STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$BASE_URL/health/")
check "GET /health/ → 200" "$STATUS" "200"

RESPONSE_TIME=$(curl -s -o /dev/null -w "%{time_total}" --max-time 5 "$BASE_URL/health/")
# Compare as integer milliseconds (bc for float comparison)
SLOW=$(echo "$RESPONSE_TIME > 0.5" | bc -l 2>/dev/null || echo "0")
if [[ "$SLOW" == "1" ]]; then
  echo "  ⚠ /health/ response time ${RESPONSE_TIME}s > 500ms (DB may be slow)"
fi

# ─── Check 2: Auth endpoint (bad creds → 401, not 500) ───────────────────────

echo ""
echo "2. Auth endpoint..."
AUTH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
  -X POST "$BASE_URL/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"smoke@test.invalid","password":"notreal"}')
check "POST /api/v1/auth/login bad creds → 401" "$AUTH_STATUS" "401"

AUTH_CT=$(curl -s -D - --max-time 5 \
  -X POST "$BASE_URL/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"smoke@test.invalid","password":"notreal"}' 2>/dev/null | grep -i "content-type" | head -1)
check_contains "auth response Content-Type is JSON" "$AUTH_CT" "application/json"

# ─── Check 3: OpenAPI schema ──────────────────────────────────────────────────

echo ""
echo "3. OpenAPI schema..."
SCHEMA_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$BASE_URL/api/schema/")
check "GET /api/schema/ → 200" "$SCHEMA_STATUS" "200"

# ─── Check 4: Frontend ────────────────────────────────────────────────────────

echo ""
echo "4. Frontend..."
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
FRONTEND_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "http://localhost:${FRONTEND_PORT}/")
check "GET frontend:${FRONTEND_PORT}/ → 200" "$FRONTEND_STATUS" "200"

# ─── Check 5: Static files ────────────────────────────────────────────────────

echo ""
echo "5. Static files..."
STATIC_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$BASE_URL/static/admin/css/base.css")
check "GET /static/admin/css/base.css → 200" "$STATIC_STATUS" "200"

# ─── Check 6: Celery task execution ───────────────────────────────────────────
# Relies on a management command that enqueues a no-op task and waits for it.
# Falls back to a Redis ping if the management command is unavailable.

echo ""
echo "6. Celery task execution..."
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "celery-worker"; then
  # Try to enqueue and confirm via Django management command
  if docker exec "$(docker ps --filter name=vitali-django -q | head -1)" \
      python manage.py shell -c "
from celery import current_app
result = current_app.send_task('apps.core.tasks.smoke_ping')
result.get(timeout=10)
print('ok')
" 2>/dev/null | grep -q "ok"; then
    check "Celery task enqueue + execute" "ok" "ok"
  else
    # Fallback: check Celery worker is registered
    CELERY_INSPECT=$(docker exec "$(docker ps --filter name=vitali-celery-worker -q | head -1)" \
      celery -A vitali inspect ping --timeout 5 2>/dev/null || echo "unreachable")
    if echo "$CELERY_INSPECT" | grep -qi "pong\|ok"; then
      check "Celery worker responds to ping" "pong" "pong"
    else
      check "Celery worker responds to ping" "unreachable" "pong"
    fi
  fi
else
  echo "  - Celery check skipped (not running in Docker context)"
fi

# ─── Check 7: HTTPS redirect (only for non-localhost) ────────────────────────

echo ""
echo "7. HTTPS redirect..."
if [[ "$BASE_URL" == http://* ]] && [[ "$BASE_URL" != *localhost* ]]; then
  REDIRECT_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 --no-location "$BASE_URL/health/")
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

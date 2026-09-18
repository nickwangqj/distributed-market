#!/usr/bin/env bash
# Smoke test — Phase 1 form.
#
# Asserts the venue is standing: every service is healthy, and the gateway reports ready, which
# it only does while it can reach both the engine and the ledger over the service network
# (.claude/docs/02-api-gateway.md §4). Later phases extend this to place crossing orders and
# assert a trade prints.
#
# Usage: scripts/smoke.sh [compose|kind]

set -euo pipefail

TARGET="${1:-compose}"
TIMEOUT_SECONDS="${SMOKE_TIMEOUT:-60}"

case "$TARGET" in
  compose)
    GATEWAY_URL="http://localhost:8080"
    MARKETDATA_URL="http://localhost:8081"
    ;;
  kind)
    echo "smoke: TARGET=kind is not implemented until Phase 2." >&2
    echo "See .claude/docs/10-implementation-progress.md" >&2
    exit 1
    ;;
  *)
    echo "smoke: unknown target '$TARGET' (expected compose or kind)" >&2
    exit 2
    ;;
esac

fail() { echo "  ✗ $*" >&2; exit 1; }
pass() { echo "  ✓ $*"; }

# Poll rather than sleep: no fixed delays anywhere in the suite
# (.claude/docs/09-testing-strategy.md §7).
wait_for() {
  local name="$1" url="$2" deadline=$((SECONDS + TIMEOUT_SECONDS))
  while (( SECONDS < deadline )); do
    if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
      pass "$name ready ($url)"
      return 0
    fi
    sleep 0.5
  done
  echo "--- last response from $url ---" >&2
  curl -sS --max-time 2 "$url" >&2 || true
  fail "$name did not become ready within ${TIMEOUT_SECONDS}s"
}

echo "smoke [$TARGET]: waiting for services"
wait_for "gateway"    "$GATEWAY_URL/readyz"
wait_for "marketdata" "$MARKETDATA_URL/readyz"

echo "smoke [$TARGET]: checking container health"
for service in engine ledger gateway marketdata; do
  state=$(docker compose ps --format '{{.Service}} {{.Health}}' | awk -v s="$service" '$1 == s {print $2}')
  [[ "$state" == "healthy" ]] || fail "$service container is '$state', expected healthy"
  pass "$service container healthy"
done

echo "smoke [$TARGET]: checking the gateway reaches its peers"
# A ready gateway has just proven engine and ledger are both reachable; make that explicit by
# stopping the ledger and asserting readiness actually flips.
docker compose stop ledger >/dev/null 2>&1
deadline=$((SECONDS + 15))
flipped=false
while (( SECONDS < deadline )); do
  if ! curl -fsS --max-time 2 "$GATEWAY_URL/readyz" >/dev/null 2>&1; then
    flipped=true
    break
  fi
  sleep 0.5
done
docker compose start ledger >/dev/null 2>&1
$flipped || fail "gateway stayed ready with the ledger stopped — the readiness check is not real"
pass "gateway goes unready when the ledger is down"
wait_for "gateway (recovered)" "$GATEWAY_URL/readyz"

echo "smoke [$TARGET]: versions"
show_version() {
  local url="$1"
  curl -fsS --max-time 2 "$url/version" \
    | python3 -c "$(printf '%s\n' \
        'import json, sys' \
        'd = json.load(sys.stdin)' \
        "print('  .', d['service'], d['version'], '- phase', d['phase'])")"
}
show_version "$GATEWAY_URL"
show_version "$MARKETDATA_URL"

echo "smoke [$TARGET]: PASS"

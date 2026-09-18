#!/usr/bin/env bash
# Smoke test — Phase 2 form.
#
# Asserts the venue is standing on whichever loop it is pointed at: every service healthy, the
# gateway ready (which it only is while it can reach both the engine and the ledger), and — on
# kind — the guarantees that only a real cluster can demonstrate.
#
# Later phases extend this to place crossing orders and assert a trade prints.
#
# Usage: scripts/smoke.sh [compose|kind]

set -euo pipefail

TARGET="${1:-compose}"
TIMEOUT_SECONDS="${SMOKE_TIMEOUT:-60}"
NAMESPACE=distributed-market

fail() { echo "  ✗ $*" >&2; exit 1; }
pass() { echo "  ✓ $*"; }

# macOS ships bash 3.2, so this script sticks to what 3.2 supports: no negative array
# indexing, no associative arrays, no ${var,,}.
case "$TARGET" in
  compose)
    GATEWAY_BASE="http://localhost:8080";  GATEWAY_HOST=""
    MARKETDATA_BASE="http://localhost:8081"; MARKETDATA_HOST=""
    ;;
  kind)
    # Host-based routing through ingress-nginx; no DNS entries needed, just a Host header.
    GATEWAY_BASE="http://localhost";  GATEWAY_HOST="gateway.dm.local"
    MARKETDATA_BASE="http://localhost"; MARKETDATA_HOST="marketdata.dm.local"
    ;;
  *)
    echo "smoke: unknown target '$TARGET' (expected compose or kind)" >&2
    exit 2
    ;;
esac

# `hit gateway /readyz` — GET one service's endpoint on whichever loop is selected.
hit() {
  local service="$1" path="$2" base host
  case "$service" in
    gateway)    base="$GATEWAY_BASE";    host="$GATEWAY_HOST" ;;
    marketdata) base="$MARKETDATA_BASE"; host="$MARKETDATA_HOST" ;;
    *) fail "hit: unknown service '$service'" ;;
  esac
  if [ -n "$host" ]; then
    curl -fsS --max-time 5 -H "Host: $host" "${base}${path}"
  else
    curl -fsS --max-time 5 "${base}${path}"
  fi
}

# Poll rather than sleep: no fixed delays anywhere in the suite
# (.claude/docs/09-testing-strategy.md §7).
wait_for() {
  local name="$1" service="$2" path="$3" deadline=$((SECONDS + TIMEOUT_SECONDS))
  while (( SECONDS < deadline )); do
    if hit "$service" "$path" >/dev/null 2>&1; then
      pass "$name ready"
      return 0
    fi
    sleep 0.5
  done
  fail "$name did not become ready within ${TIMEOUT_SECONDS}s"
}

echo "smoke [$TARGET]: waiting for services"
wait_for "gateway" gateway /readyz
wait_for "marketdata" marketdata /readyz

if [[ "$TARGET" == compose ]]; then
  echo "smoke [$TARGET]: checking container health"
  for service in engine ledger gateway marketdata; do
    state=$(docker compose ps --format '{{.Service}} {{.Health}}' | awk -v s="$service" '$1 == s {print $2}')
    [[ "$state" == "healthy" ]] || fail "$service container is '$state', expected healthy"
    pass "$service container healthy"
  done

  echo "smoke [$TARGET]: checking the gateway reaches its peers"
  docker compose stop ledger >/dev/null 2>&1
  deadline=$((SECONDS + 15)); flipped=false
  while (( SECONDS < deadline )); do
    if ! hit gateway /readyz >/dev/null 2>&1; then flipped=true; break; fi
    sleep 0.5
  done
  docker compose start ledger >/dev/null 2>&1
  $flipped || fail "gateway stayed ready with the ledger stopped — the readiness check is not real"
  pass "gateway goes unready when the ledger is down"
  wait_for "gateway (recovered)" gateway /readyz
fi

if [[ "$TARGET" == kind ]]; then
  echo "smoke [$TARGET]: checking pods"
  for workload in statefulset/engine deployment/ledger deployment/gateway deployment/marketdata; do
    kubectl -n "$NAMESPACE" rollout status "$workload" --timeout=60s >/dev/null \
      || fail "$workload is not rolled out"
    pass "$workload rolled out"
  done

  echo "smoke [$TARGET]: checking the engine's volume and lock"
  kubectl -n "$NAMESPACE" exec statefulset/engine -- \
    sh -c 'test -s /data/state/engine-heartbeat.json' \
    || fail "engine heartbeat file missing — the PVC is not mounted or not writable"
  pass "engine heartbeat written to its PVC"
  kubectl -n "$NAMESPACE" exec statefulset/engine -- sh -c 'test -s /data/.lock' \
    || fail "engine lock file missing"
  pass "engine holds the data-directory lock"

  echo "smoke [$TARGET]: checking engine and ledger are not publicly exposed"
  # Probe /version, not /healthz: ingress-nginx answers /healthz itself on every host, so a
  # health probe tests the controller rather than the routing. /version is only ever served by
  # our services, so a 404 there means no route reaches them.
  for host in engine ledger; do
    status=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 \
      -H "Host: ${host}.dm.local" "http://localhost/version")
    [ "$status" = "404" ] || fail "$host answered through the ingress (HTTP $status) — it must have no public route"
    pass "$host has no ingress route (404 from the default backend)"
  done
  ingresses=$(kubectl -n "$NAMESPACE" get ingress -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' | sort | tr '\n' ' ')
  [ "$ingresses" = "gateway marketdata " ] || fail "unexpected ingress set: '$ingresses'"
  pass "only gateway and marketdata have Ingress objects"

  if [ "${SMOKE_SKIP_SCALE:-}" != "1" ]; then
    echo "smoke [$TARGET]: checking the single-engine guarantee"
    "$(dirname "$0")/check-single-engine.sh" >/dev/null 2>&1 \
      || fail "a second engine pod was able to run — see scripts/check-single-engine.sh"
    pass "a second engine pod refuses to start (holds the flock, exits 1)"
  fi
fi

echo "smoke [$TARGET]: versions"
for service in gateway marketdata; do
  hit "$service" /version | python3 -c "$(printf '%s\n' \
      'import json, sys' \
      'd = json.load(sys.stdin)' \
      "print('  .', d['service'], d['version'], '- phase', d['phase'])")"
done

echo "smoke [$TARGET]: PASS"

#!/usr/bin/env bash
# Prove the single-engine invariant on a running cluster (.claude/docs/08-deployment.md §4).
#
# Scales the engine to 2 and asserts the second pod refuses to run. On a single-node cluster the
# RWO volume does NOT stop the second pod mounting — both pods are on the same node — so what is
# actually under test here is the advisory flock, the last of the four layers and the only one
# that still holds in this scenario.
#
# Restores replicas=1 on the way out, whatever happens.

set -uo pipefail

NAMESPACE=distributed-market
DEADLINE=$((SECONDS + 120))

restore() {
  kubectl -n "$NAMESPACE" scale statefulset/engine --replicas=1 >/dev/null 2>&1
  kubectl -n "$NAMESPACE" delete pod engine-1 --ignore-not-found --wait=false >/dev/null 2>&1
}
trap restore EXIT

echo "==> scaling engine to 2 replicas"
kubectl -n "$NAMESPACE" scale statefulset/engine --replicas=2 >/dev/null

while (( SECONDS < DEADLINE )); do
  exit_code=$(kubectl -n "$NAMESPACE" get pod engine-1 \
    -o jsonpath='{.status.containerStatuses[0].lastState.terminated.exitCode}' 2>/dev/null)
  if [ "${exit_code:-}" = "1" ]; then
    reason=$(kubectl -n "$NAMESPACE" logs engine-1 --previous 2>/dev/null | tail -1)
    echo "==> single-engine guarantee holds: engine-1 exited 1 and did not serve"
    echo "    $reason"
    # engine-0 must have been unaffected throughout.
    if ! kubectl -n "$NAMESPACE" get pod engine-0 \
        -o jsonpath='{.status.containerStatuses[0].ready}' 2>/dev/null | grep -qx true; then
      echo "==> FAIL: engine-0 is not ready — the second pod disturbed the first" >&2
      exit 1
    fi
    echo "    engine-0 stayed ready throughout"
    exit 0
  fi

  ready=$(kubectl -n "$NAMESPACE" get pod engine-1 \
    -o jsonpath='{.status.containerStatuses[0].ready}' 2>/dev/null)
  if [ "${ready:-}" = "true" ]; then
    echo "==> FAIL: a second engine pod is running and ready — the book can fork" >&2
    exit 1
  fi
  sleep 3
done

echo "==> FAIL: engine-1 neither started nor refused within the timeout" >&2
exit 1

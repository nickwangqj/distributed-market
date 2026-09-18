#!/usr/bin/env bash
# Report whether NetworkPolicy is actually enforced on this cluster.
#
# Some CNIs (notably older kindnet) accept NetworkPolicy objects and ignore them — a silent
# no-op where the manifests look like protection while providing none. This probe states the
# truth out loud rather than letting anyone assume it.
#
# The test is two-sided on purpose. A one-sided "the blocked pod could not connect" proves
# nothing: a pod that failed to start also cannot connect. So we run the same connection from a
# pod the policy ALLOWS and from one it DENIES, and only trust the result when they differ.

set -uo pipefail

NAMESPACE=distributed-market
IMAGE=busybox:1.36

probe() {
  local name="$1" labels="$2"
  kubectl -n "$NAMESPACE" delete pod "$name" --ignore-not-found --wait=true >/dev/null 2>&1
  kubectl -n "$NAMESPACE" run "$name" \
    --image="$IMAGE" --restart=Never --rm -i --quiet --timeout=90s \
    ${labels:+--labels="$labels"} \
    -- sh -c 'nc -z -w 3 engine 8080' >/dev/null 2>&1
}

# A pod wearing the gateway label is explicitly allowed by engine-internal-only.
if probe np-probe-allowed "app.kubernetes.io/name=gateway"; then
  allowed=reached
else
  allowed=blocked
fi

# A pod with no matching label is not in any `from` clause, so it should be denied.
if probe np-probe-denied ""; then
  denied=reached
else
  denied=blocked
fi

if [ "$allowed" = reached ] && [ "$denied" = blocked ]; then
  echo "==> NetworkPolicy: ENFORCED (allowed pod reached engine:8080, unlabelled pod was blocked)"
  exit 0
fi

if [ "$allowed" = reached ] && [ "$denied" = reached ]; then
  echo "==> NetworkPolicy: NOT ENFORCED (an unlabelled pod reached engine:8080)"
  echo "    This CNI ignores NetworkPolicy. The manifests are correct and will take effect on a"
  echo "    CNI that implements them. Until then, treat engine and ledger as reachable from"
  echo "    anywhere in this namespace."
  exit 1
fi

echo "==> NetworkPolicy: INCONCLUSIVE (allowed=$allowed denied=$denied)"
echo "    The allowed pod could not reach engine:8080 either, so this probe proves nothing —"
echo "    the test pods themselves may have failed to start."
exit 2

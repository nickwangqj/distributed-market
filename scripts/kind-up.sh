#!/usr/bin/env bash
# Create the local kind cluster, load the images, and apply the manifests.
#
# Idempotent: re-running reloads images and re-applies, which is the normal way to push a change
# to the outer loop.

set -euo pipefail

CLUSTER=distributed-market
CONTEXT="kind-${CLUSTER}"
NAMESPACE=distributed-market
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INGRESS_MANIFEST="${INGRESS_MANIFEST:-https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.11.3/deploy/static/provider/kind/deploy.yaml}"

say() { echo "==> $*"; }

if ! kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
  say "creating kind cluster '$CLUSTER'"
  kind create cluster --config "$REPO_ROOT/deploy/kind/cluster.yaml"
else
  say "kind cluster '$CLUSTER' already exists"
fi

kubectl config use-context "$CONTEXT" >/dev/null

say "loading images into the node (no registry involved)"
kind load docker-image --name "$CLUSTER" \
  dm-engine:latest dm-ledger:latest dm-gateway:latest dm-marketdata:latest

say "installing ingress-nginx"
if ! kubectl get ns ingress-nginx >/dev/null 2>&1; then
  kubectl apply -f "$INGRESS_MANIFEST"
fi
# Deployment-available is not enough: the validating webhook that gates Ingress creation runs
# in the controller pod and starts serving slightly later. Waiting on pod readiness is what
# stops `kubectl apply` failing with "connection refused" on the admission endpoint.
kubectl -n ingress-nginx wait --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller --timeout=180s

# The fixtures and the Secret must exist before the workloads that mount them, or every pod
# sits in FailedMount until they appear. The namespace has to come first in turn.
say "creating namespace, fixtures ConfigMap and API-key Secret"
kubectl apply -f "$REPO_ROOT/deploy/k8s/base/namespace.yaml"

if [[ ! -f "$REPO_ROOT/data/config/api_keys.json" ]]; then
  echo "data/config/api_keys.json is missing — run 'make keys' first" >&2
  exit 1
fi

# instruments.json and accounts.seed.json live under data/config/, outside the kustomize root,
# and api_keys.json is git-ignored — so both are created here rather than in a kustomization.
kubectl -n "$NAMESPACE" create configmap dm-fixtures \
  --from-file="$REPO_ROOT/data/config/instruments.json" \
  --from-file="$REPO_ROOT/data/config/accounts.seed.json" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n "$NAMESPACE" create secret generic dm-api-keys \
  --from-file="$REPO_ROOT/data/config/api_keys.json" \
  --dry-run=client -o yaml | kubectl apply -f -

say "applying manifests"
# The ingress-nginx admission webhook gates Ingress creation, and its Service endpoint becomes
# routable from the API server a moment *after* the controller pod reports ready — so a single
# apply can still fail with "connection refused" on the webhook. Apply is idempotent, so retry
# rather than sleeping a guessed amount.
apply_manifests() {
  local attempt
  for attempt in 1 2 3 4 5 6; do
    if kubectl apply -k "$REPO_ROOT/deploy/k8s/overlays/local"; then
      return 0
    fi
    echo "    apply attempt $attempt failed (likely the admission webhook); retrying"
    sleep 5
  done
  echo "manifests did not apply after 6 attempts" >&2
  return 1
}
apply_manifests

say "waiting for workloads"
kubectl -n "$NAMESPACE" rollout status statefulset/engine --timeout=180s
kubectl -n "$NAMESPACE" rollout status deployment/ledger --timeout=180s
kubectl -n "$NAMESPACE" rollout status deployment/gateway --timeout=180s
kubectl -n "$NAMESPACE" rollout status deployment/marketdata --timeout=180s

"$REPO_ROOT/scripts/check-networkpolicy.sh" || true

say "cluster ready"
echo "    gateway     curl -H 'Host: gateway.dm.local' http://localhost/healthz"
echo "    marketdata  curl -H 'Host: marketdata.dm.local' http://localhost/healthz"

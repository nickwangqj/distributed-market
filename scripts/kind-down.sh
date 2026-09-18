#!/usr/bin/env bash
# Delete the local kind cluster. The images stay in the Docker daemon.
set -euo pipefail
CLUSTER=distributed-market
if kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
  kind delete cluster --name "$CLUSTER"
else
  echo "kind cluster '$CLUSTER' does not exist"
fi

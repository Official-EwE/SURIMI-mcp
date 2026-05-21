#!/bin/bash
# Diagnostic dump for a stuck/failed surimi-mcp helm release.
#
# Usage:
#   ./debug-mcp.sh                        # auto-detect: latest surimi-mcp release
#   ./debug-mcp.sh <release-name>         # specific release
#
# Run from inside a pod that has kubectl + helm + the namespace's SA mounted.
# Works inside the surimi-terminal sidecar that this chart ships.

set -uo pipefail

REL="${1:-}"
if [ -z "$REL" ]; then
  REL=$(helm list -q 2>/dev/null | grep '^surimi-mcp' | tail -1 || true)
fi
if [ -z "$REL" ]; then
  echo "ERROR: no surimi-mcp helm release found. Pass a name explicitly."
  echo "  ./debug-mcp.sh <release-name>"
  echo
  echo "Available releases:"
  helm list -a 2>/dev/null
  exit 1
fi

sep() { printf '\n=== %s ===\n' "$*"; }

sep "release: $REL"
helm status "$REL" 2>&1 | head -30

sep "pods (any state)"
kubectl get pod -l app.kubernetes.io/instance="$REL" -o wide 2>&1

sep "describe each pod"
for p in $(kubectl get pod -l app.kubernetes.io/instance="$REL" -o name 2>/dev/null); do
  echo "--- $p ---"
  kubectl describe "$p" 2>&1 | tail -40
  echo
done

sep "mcp server logs (last 80 lines)"
kubectl logs -l app.kubernetes.io/instance="$REL" -c surimi-mcp --tail=80 2>&1 || \
  kubectl logs -l app.kubernetes.io/instance="$REL" --tail=80 2>&1

sep "load-data Job status"
kubectl get job "${REL}-load-data" 2>&1 || echo "(no load-data job - normal if postgresql.enabled=false)"

sep "load-data Job logs (last 150 lines)"
JOB_POD=$(kubectl get pod -l job-name="${REL}-load-data" -o name 2>/dev/null | head -1)
if [ -n "$JOB_POD" ]; then
  kubectl logs "$JOB_POD" -c load-csv --tail=150 2>&1 || true
  echo "--- previous attempt (if any) ---"
  kubectl logs "$JOB_POD" -c load-csv --previous --tail=80 2>&1 || true
else
  echo "(no load-data pod found)"
fi

sep "postgres pod logs (last 30 lines)"
kubectl logs "${REL}-postgresql-0" --tail=30 2>&1 || echo "(no bundled postgres or different name)"

sep "namespace events (most recent 25)"
kubectl get events --sort-by=.lastTimestamp 2>&1 | tail -25

sep "ingress + service"
kubectl get svc,ingress -l app.kubernetes.io/instance="$REL" 2>&1

sep "done"
echo "If you found the error, common fixes:"
echo "  - ImagePullBackOff      => image tag wrong or registry rate-limit; check helm get values \$REL"
echo "  - Pending (quota)       => initContainers missing requests.cpu/memory; check describe pod"
echo "  - load-csv connection   => postgres not ready yet; usually self-heals on Job retry"
echo "  - load-csv missing CSVs => Dockerfile data fetch failed at build time; check image build"
echo "  - SSE 200 but tools 0   => server.py started but could not reach DB; check env DATABASE_URL"

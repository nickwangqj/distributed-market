# Deployment

How the venue is packaged and run locally: four Docker images, a docker compose stack for fast
iteration, and a kind cluster running the real Kubernetes manifests.

Nothing here needs a cloud account or a container registry. Images are built locally and
side-loaded into the cluster.

```
deploy/
├── docker/
│   ├── Dockerfile.base         builder + runtime base, shared by all four services
│   ├── Dockerfile.engine       thin: FROM dm-base, sets the command
│   ├── Dockerfile.gateway
│   ├── Dockerfile.ledger
│   └── Dockerfile.marketdata
├── k8s/
│   ├── base/                   kustomize base — the manifests themselves
│   └── overlays/local/         kind-specific overrides (imagePullPolicy, tags)
└── kind/
    └── cluster.yaml            single-node cluster with 80/443 published to the host
```

`docker-compose.yml` lives at the repository root, where compose expects it.

---

## 1. Two loops, one set of images

Both loops run the *same images* and the *same smoke test*. They differ in what they can prove.

| | Inner loop — compose | Outer loop — kind |
|---|---|---|
| Command | `make up` | `make kind-up` |
| Cycle time | seconds | 1–2 minutes |
| Proves | service logic, wiring, the API contract | probes, volumes, the single-engine guarantee, ingress, NetworkPolicy |
| State | `./data` bind-mounted from the repo | PersistentVolumeClaims inside the cluster |
| Entry | `localhost:8080` / `localhost:8081` | `localhost:80` with a `Host` header |
| Smoke | `make smoke` | `make smoke TARGET=kind` |

Kubernetes is the deployment target and the only place the operational guarantees hold. Compose
is the fast path for writing the code that runs there. If a change passes under compose and
fails under kind, the difference is real and worth investigating.

---

## 2. Images

One base image carries everything; the four service images are a `FROM` and a `CMD`.

```
python:3.12-slim
      │
      ├── builder stage      pip install . into /opt/venv
      │
      └── dm-base            /opt/venv + non-root user + HEALTHCHECK
              │
              ├── dm-engine        CMD python -m engine.main
              ├── dm-gateway       CMD uvicorn gateway.main:app
              ├── dm-ledger        CMD uvicorn ledger.main:app
              └── dm-marketdata    CMD uvicorn marketdata.main:app
```

Why a shared base: one dependency install, one copy of `market_core`, four images that cannot
drift apart. `make build` builds `dm-base` first, then the four.

**Security posture**, identical in compose and Kubernetes:

| Property | How |
|----------|-----|
| Non-root | `uid=1001(dm)`, `runAsNonRoot: true` |
| Read-only root filesystem | `read_only: true` / `readOnlyRootFilesystem: true`, with a tmpfs `/tmp` |
| No capabilities | `capabilities: drop: ["ALL"]`, `allowPrivilegeEscalation: false` |
| Nothing writable but `/data` | the project is installed into site-packages, not editable |

The health check lives in the base image and uses `urllib` from the interpreter, because the
slim image ships no `curl`.

**The engine runs uvicorn itself** (`python -m engine.main`) rather than being launched by it,
because it needs control of startup (journal replay) and shutdown (drain, fsync, final
snapshot). The other three are plain `uvicorn` invocations.

---

## 3. The compose stack

```
make build   docker build dm-base, then docker compose build
make up      docker compose up -d --wait
make smoke   scripts/smoke.sh compose
make logs    docker compose logs -f
make down    docker compose down --remove-orphans
```

| Service | Published | Volumes |
|---------|-----------|---------|
| `engine` | — (internal) | `./data:/data` — owns journal, snapshots, state |
| `ledger` | — (internal) | `./data:/data` |
| `gateway` | `8080` | `./data/config:/data/config:ro` |
| `marketdata` | `8081` | `./data/config:/data/config:ro` |

`./data` is bind-mounted from the repository, so a journal written by a compose run is
inspectable with `jq` in your working tree.

**Startup ordering comes from health checks**, not sleeps: `depends_on: condition:
service_healthy` holds the gateway back until the engine and ledger answer `/healthz`.

Environment defaults are inline in `docker-compose.yml` using `${VAR:-default}`, so `make up`
works with no `.env` at all. Copy `.env.example` to `.env` to override. Keys mirror the
Kubernetes ConfigMap exactly, so the two stay interchangeable.

---

## 4. The kind cluster

```
make kind-up     scripts/kind-up.sh   (idempotent — re-run to push changes)
make kind-down   scripts/kind-down.sh
```

`kind-up.sh` does six things in this order, and the order matters:

1. **Create the cluster** from `deploy/kind/cluster.yaml` if it does not exist. The node is
   labelled `ingress-ready=true` and publishes host ports 80 and 443.
2. **Side-load the images** with `kind load docker-image`. No registry is involved, which is why
   the local overlay sets `imagePullPolicy: Never` — without it every pod sits in
   `ImagePullBackOff` trying to reach Docker Hub for an image that only exists on the node.
3. **Install ingress-nginx** and wait for the controller *pod* to be ready.
4. **Create the namespace, the fixtures ConfigMap, and the API-key Secret** — before the
   workloads that mount them, or every pod sits in `FailedMount` until they appear.
5. **Apply the manifests** with a bounded retry (see troubleshooting below).
6. **Probe NetworkPolicy enforcement** and report the result.

---

## 5. What runs in the cluster

| Object | Kind | Replicas | Why |
|--------|------|----------|-----|
| `engine` | StatefulSet | **1** | Owns the order book and the journal; must never run twice |
| `engine-data` | PVC (RWO) | — | A **single static claim**, not a volumeClaimTemplate — see below |
| `ledger` | Deployment (`Recreate`) | 1 | Owns balances; `Recreate` keeps two writers off its volume |
| `ledger-data` | PVC (RWO) | — | Separate volume: each service owns its files completely |
| `gateway` | Deployment | 2 | Stateless; any pod serves any request |
| `marketdata` | Deployment | 2 | Derived state only; two replicas so per-pod lag is visible early |
| `dm-config` | ConfigMap | — | Environment values, mirroring the compose `.env` keys |
| `dm-fixtures` | ConfigMap | — | `instruments.json`, `accounts.seed.json` |
| `dm-api-keys` | Secret | — | `api_keys.json`; mounted by the gateway only |
| `gateway`, `marketdata` | Ingress | — | The only two public surfaces |
| `engine-internal-only`, `ledger-internal-only` | NetworkPolicy | — | Engine and ledger reachable only from named peers |

### The single-engine guarantee

A second engine would silently fork the order book, so it is defended four times:

1. **StatefulSet with `replicas: 1`** — Kubernetes will not start `engine-0` twice.
2. **`podManagementPolicy: OrderedReady`** and a no-surge rollout — the old pod is gone before
   the new one starts.
3. **ReadWriteOnce PVC** — the volume can only be mounted by one *node* at a time.
4. **Advisory `flock` on `/data/.lock`** — the process exits non-zero rather than trading
   against a book it does not own.

**On a single-node cluster, layer 3 does nothing** — both pods land on the same node, where RWO
permits a shared mount. The flock is the only layer still standing, which is exactly why it
exists.

> **Do not use a `volumeClaimTemplate` for the engine.** A template gives every replica its own
> PVC, which disables layers 3 and 4 together: a second engine gets a private volume, so there is
> no mount conflict and no lock to contend for, and it comes up *healthy* with a private journal
> and a private book. This was built wrong the first time and caught by testing rather than by
> review. `scripts/check-single-engine.sh` scales the engine to 2 and asserts the second pod
> exits 1 while the first stays ready; it runs as part of `make smoke TARGET=kind`.

### Config and secrets

`dm-config` is declarative, in the kustomize base. `dm-fixtures` and `dm-api-keys` are created
imperatively by `kind-up.sh` instead, because their source files live under `data/config/` —
outside the kustomize root, which `kubectl apply -k` offers no way to relax — and
`api_keys.json` is git-ignored. Run `make keys` once to generate it.

The gateway mounts a **`projected` volume** that merges `dm-fixtures` and `dm-api-keys` into one
directory. A Secret cannot be `subPath`-mounted inside another volume mount, and `/data/config`
is already a ConfigMap mount; projection is what keeps the documented path
`data/config/api_keys.json` working. Only the gateway gets the Secret — the other three services
mount the fixtures alone.

---

## 6. How traffic flows

```
    curl -H 'Host: gateway.dm.local' http://localhost/v1/orders
              │
              ▼  host port 80 → kind node
    ┌───────────────────────┐
    │  ingress-nginx        │   routes by Host, not path, so the two public
    └──────┬─────────┬──────┘   surfaces keep separate path namespaces
           │         │
  gateway.dm.local   marketdata.dm.local
           │         │
           ▼         ▼
    ┌──────────┐  ┌──────────────┐
    │ gateway  │  │  marketdata  │   ← WebSocket terminates here, never on the gateway
    │ (2 pods) │  │   (2 pods)   │
    └────┬─────┘  └──────┬───────┘
         │               │
         │ reserve       │ event stream
         ▼               ▼
    ┌──────────┐    ┌──────────┐
    │  ledger  │◄───│  engine  │   no Ingress, no public route,
    │ (1 pod)  │    │ (1 pod)  │   NetworkPolicy limits callers
    └────┬─────┘    └────┬─────┘
         ▼               ▼
    ledger-data      engine-data     (ReadWriteOnce PVCs)
```

Host-based routing means **nothing needs to go in `/etc/hosts`** — pass the header instead:

```bash
curl -H 'Host: gateway.dm.local'    http://localhost/healthz
curl -H 'Host: marketdata.dm.local' http://localhost/version
```

An unknown host gets a 404 from the ingress default backend, which is how the smoke test proves
the engine and ledger have no public route.

### Probes

Liveness asks *is the process alive*; readiness asks *can it serve*, and is what gates traffic
and startup order.

| Service | Liveness | Readiness today | Readiness later |
|---------|----------|-----------------|-----------------|
| engine | `/healthz` | always ready (stub) | journal replay complete (Phase 7) |
| ledger | `/healthz` | always ready (stub) | caught up to the engine's `seq` (Phase 8) |
| gateway | `/healthz` | **engine and ledger both reachable** | plus the circuit breaker (Phase 9) |
| marketdata | `/healthz` | always ready (stub) | caught up and holding a snapshot (Phase 10) |

The gateway's readiness check is real already: it probes both peers concurrently and returns 503
with a reason when either is down. The engine and ledger carry a generous
`failureThreshold: 30` from the start, so the phases that make their readiness expensive need no
manifest change.

---

## 7. Testing the deployment

```bash
make smoke                # compose
make smoke TARGET=kind    # kind

scripts/check-networkpolicy.sh   # is NetworkPolicy actually enforced here?
scripts/check-single-engine.sh   # can a second engine run? (it must not)
```

`make smoke` asserts, on both loops, that every service is healthy and the gateway is ready —
which it only is while it can reach the engine and the ledger. On compose it additionally stops
the ledger and asserts readiness *flips*, because a health check that cannot fail is worse than
none. On kind it additionally checks the engine's PVC is mounted and written, that engine and
ledger have no ingress route, and that a second engine refuses to start.

**NetworkPolicy enforcement depends on the CNI**, so it is measured rather than assumed. The
probe is two-sided on purpose: a pod carrying the `gateway` label must reach `engine:8080` *and*
an unlabelled pod must not. A one-sided "it was blocked" proves nothing, since a pod that failed
to start also cannot connect. On kind 0.33 (kindnet) the policies are genuinely enforced.

The smoke test **polls rather than sleeps** — no fixed delays anywhere, which is what keeps it
usable in CI.

---

## 8. Troubleshooting

Every one of these was hit while building this; they are the failures you are most likely to see.

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ImagePullBackOff` on every pod | Images exist only on the node, not in a registry | The local overlay sets `imagePullPolicy: Never`; re-run `make kind-up` to side-load |
| `failed calling webhook ... connection refused` | ingress-nginx's admission webhook is routable slightly *after* its pod reports ready | `kind-up.sh` retries the apply; apply is idempotent, so retry beats a guessed sleep |
| Pods stuck in `FailedMount` | Fixtures created after the workloads | `kind-up.sh` creates namespace, ConfigMap and Secret first |
| `mount ... not a directory` for `api_keys.json` | Secret `subPath` inside another volume mount | Use the `projected` volume (already in `gateway.yaml`) |
| A second engine pod runs happily | `volumeClaimTemplate` gave it a private volume | Use the single static `engine-data` PVC |
| `data/config/api_keys.json is missing` | It is git-ignored by design | `make keys` |
| Smoke script dies with no output | macOS ships **bash 3.2** — no negative array indexing, no associative arrays, no `${var,,}` | Keep scripts 3.2-compatible |
| Ingress test passes when it should fail | ingress-nginx answers `/healthz` itself on every host | Probe `/version` instead |

Useful commands:

```bash
kubectl -n distributed-market get pods -o wide
kubectl -n distributed-market logs statefulset/engine -f
kubectl -n distributed-market describe pod -l app.kubernetes.io/name=gateway
kubectl -n distributed-market exec statefulset/engine -- cat /data/state/engine-heartbeat.json
kubectl kustomize deploy/k8s/overlays/local     # render manifests without applying
```

---

## 9. What changes in later phases

The deployment is built first, on purpose, so that everything after it fills in behaviour behind
a working cluster. Expected changes:

| Phase | Deployment delta |
|-------|------------------|
| Order book | `sortedcontainers` enters the engine image |
| Persistence | `DM_FSYNC_MODE`, `DM_SNAPSHOT_EVERY` become load-bearing; PVC holds real journals |
| Engine | Readiness means replay complete; `preStop` and grace period for clean drain |
| Ledger | Readiness means caught up to the engine; depends on engine readiness on a cold start |
| Gateway | Secret actually consumed; Ingress `/v1/*` live; readiness reflects the circuit breaker; HPA |
| Market data | Ingress `/ws` with WebSocket upgrade — the `proxy-read-timeout: 3600` annotation is already there, because an ingress default of 60 s silently kills idle-but-healthy connections |
| CI | The pipeline builds the same images the Makefile does; no separate build path |

The rule from here on: a change is not done until `make smoke` passes on **both** loops.

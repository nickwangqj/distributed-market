# distributed-market

A distributed foreign-exchange trading venue for **USD/CAD**, built as four Python services in
containers on Kubernetes. Persistence is plain JSON files rather than a database, and the whole
venue is meant to run on a laptop.

> **Status: under construction.** The design is complete and the deployment is built and proven,
> but **no trading logic exists yet** — the four services are health-probe stubs. This README
> describes only what works today. See *What exists today* below for the exact boundary.

## What exists today

- **Four containerized services** — `engine`, `ledger`, `gateway`, `marketdata` — deployed two
  ways: a docker compose stack for fast iteration, and a kind cluster running the real
  Kubernetes manifests. They currently serve health probes and nothing else.
- **`market_core`**, the shared domain library: order and event types, integer money arithmetic,
  the instrument config loader, the error taxonomy, and ULID generation. Fully implemented and
  tested; nothing consumes it at runtime yet.
- **The single-engine guarantee**, enforced and tested end to end: a second engine pod cannot
  run, verified on a live cluster.
- **A test suite** — 102 tests covering `market_core`, plus a smoke test that runs against both
  deployment loops.

Not built yet: the order book, the matching engine, balances and reservations, the REST order
API, and the market-data feed.

## Architecture

```
                    ┌──────────────┐
   REST ───────────►│ API Gateway  │───── health probes ─────►┌───────────────┐
                    │   (2 pods)   │                          │ Account       │
                    └──────┬───────┘                          │ Ledger        │
                           │ health probes                    │  (1 pod)      │
                           ▼                                  └───────┬───────┘
                    ┌──────────────┐                                  │
                    │  Matching    │                                  │
                    │  Engine      │                          ┌───────────────┐
                    │  (1 pod)     │                          │ Market Data   │◄── HTTP
                    └──────┬───────┘                          │  (2 pods)     │
                           │                                  └───────────────┘
                           ▼
                    ┌──────────────┐
                    │  JSON files  │  (PVC — currently a heartbeat and a lock file)
                    └──────────────┘
```

One authoritative engine will own the order book; everything around it is stateless or derived.
That topology is already deployed — what is missing is the behaviour inside each box.

| Service | Replicas | State | Does today |
|---------|----------|-------|------------|
| `gateway` | 2 | none | Reports ready only while the engine and ledger are both reachable |
| `engine` | **1** | owns its volume | Holds the data-directory lock, writes a heartbeat file |
| `ledger` | 1 | owns its volume | Health probes |
| `marketdata` | 2 | none | Health probes |

## Repository layout

```
src/
  market_core/     shared domain library — types, money, events, errors  (implemented)
  service_common/  settings, JSON logging, health-app factory            (implemented)
  engine/          matching engine service                               (stub)
  ledger/          account ledger service                                (stub)
  gateway/         public REST API                                       (stub)
  marketdata/      market data service                                   (stub)
data/              persistence root — journal, snapshots, state, config
deploy/            Dockerfiles, Kubernetes manifests, kind config — see deploy/README.md
scripts/           smoke test, cluster lifecycle, verification probes
tests/
```

## Prerequisites

| Tool | Version | Needed for |
|------|---------|-----------|
| Python | 3.11+ | tests and tooling (3.12 in the container images) |
| Docker | any recent | building images; the compose loop |
| [kind](https://kind.sigs.k8s.io/) | 0.30+ | the local Kubernetes cluster |
| `kubectl` | 1.30+ | talking to that cluster |
| `make` | GNU make | everything below |

No cloud account and no container registry are required — images are built locally and
side-loaded into the cluster.

## Getting started

```bash
git clone <this repo> && cd distributed-market

make venv            # create .venv and install the project with dev extras
source .venv/bin/activate
make lint typecheck  # ruff + mypy (strict)
make test            # 102 tests, about a second
```

`make help` lists every target.

### Configuration you need locally

`data/config/api_keys.json` holds API-key hashes and is **git-ignored**. Generate it from the
seeded accounts:

```bash
make keys      # writes data/config/api_keys.json for sk_test_alice / sk_test_bob
```

`data/config/instruments.json` and `data/config/accounts.seed.json` are committed and need no
setup. Everything else under `data/` is generated at runtime and ignored by git.

### Inner loop — docker compose (seconds)

```bash
make build           # build the base image and all four service images
make up              # start the four services
make smoke           # assert the venue is standing
make logs            # tail all services
make down
```

### Outer loop — kind (1–2 minutes)

The real deployment target: probes, volumes, ingress, NetworkPolicy, and the single-engine
guarantee.

```bash
make kind-up               # create cluster, install ingress-nginx, load images, apply manifests
kubectl -n distributed-market get pods
make smoke TARGET=kind
make kind-down
```

Routing is host-based, so there is nothing to add to `/etc/hosts` — pass the header instead:

```bash
curl -H 'Host: gateway.dm.local'    http://localhost/healthz
curl -H 'Host: marketdata.dm.local' http://localhost/version
```

**[`deploy/README.md`](deploy/README.md)** explains how the images, compose stack, kind cluster,
and Kubernetes manifests fit together — including how traffic reaches the services, how the
single-engine guarantee is enforced, and the failure modes you are most likely to hit.

## What the services expose

Every service serves the same three endpoints, on port 8080. There are no other routes yet.

| Endpoint | Returns |
|----------|---------|
| `GET /healthz` | Liveness — is the process up |
| `GET /readyz` | Readiness — can it serve; 503 with a reason when it cannot |
| `GET /version` | Service name, version, and the phase it is built to |

Under compose the gateway is on `localhost:8080` and market data on `localhost:8081`.

The gateway's readiness check is real: it probes the engine and the ledger concurrently and goes
unready when either is down. `make smoke` proves this by stopping the ledger and asserting
readiness actually flips — a health check that cannot fail is worse than none.

## `market_core`

The shared library every service will build on. Pure domain logic: no I/O beyond reading a
config file, no framework imports.

| Module | Provides |
|--------|----------|
| `enums` | `Side`, `OrderType`, `TimeInForce`, `OrderStatus`, `CancelReason` |
| `units` | Integer money arithmetic, the notional rounding rule, wire parsing and formatting |
| `orders` | The immutable `Order` record and its lifecycle transitions |
| `events` | The six engine event records and their journal round trip |
| `instruments` | Instrument config loading, quantity/price/band validation |
| `errors` | The error taxonomy and its HTTP mapping |
| `ids` | ULID generation, injectable id generators |
| `clock` | Injectable time, so nothing depends on the wall clock |

```python
from market_core import Side, notional_cad

notional_cad(100, 137_500, Side.BUY)   # 138 — the taker pays the extra half cent
notional_cad(100, 137_500, Side.SELL)  # 137 — the taker forgoes it
```

## Testing

```bash
make test        # unit and property tests
make smoke       # compose deployment
make smoke TARGET=kind
```

Property tests use Hypothesis over randomized inputs. What is asserted today:

- Notional rounding is never more than half a cent from exact, and the two sides differ by at
  most one cent — side only ever decides a tie.
- The market-buy affordability clamp never permits overspending its reservation.
- An order record cannot be constructed in an illegal state, and a self-trade cannot be
  constructed at all.
- Orders and events survive a journal round trip exactly.

Two verification scripts assert properties only a live cluster can show:

```bash
scripts/check-single-engine.sh    # a second engine pod must refuse to start
scripts/check-networkpolicy.sh    # is NetworkPolicy actually enforced by this CNI?
```

Both run as part of `make smoke TARGET=kind`.

## Configuration

Read from the environment; the same keys are used by compose and by the Kubernetes ConfigMap.

| Variable | Default | Purpose |
|----------|---------|---------|
| `DM_DATA_DIR` | `./data` locally, `/data` in-cluster | Persistence root |
| `DM_LOG_LEVEL` | `INFO` | Structured JSON logs to stdout |
| `DM_PORT` | `8080` | Listen port |
| `DM_ENGINE_URL` | `http://engine:8080` | Peer address, used by the gateway's readiness check |
| `DM_LEDGER_URL` | `http://ledger:8080` | Peer address, used by the gateway's readiness check |
| `DM_MARKETDATA_URL` | `http://marketdata:8080` | Peer address |

`DM_FSYNC_MODE`, `DM_SNAPSHOT_EVERY`, `DM_BAND_REFRESH` and `DM_RESERVATION_TTL` are also parsed
and carried through the config, but nothing consumes them yet — they belong to components that
are not built.

## Design principles in the code today

- **Money is integers, never floats.** USD and CAD in cents, price in ticks of 0.00001 CAD per
  USD. A trade's notional rounds to the nearest cent with ties against the taker, and the same
  single value moves between both accounts — so rounding decides who absorbs the sub-cent, never
  whether cents appear or vanish.
- **Deployment first.** The containers and the cluster were built and proven around stub
  services, before any trading logic, so the plumbing was debugged while it was trivial.
- **One engine, defended four ways.** A StatefulSet with one replica, a no-surge rollout, a
  ReadWriteOnce volume, and an advisory `flock` the process takes at startup. On a single-node
  cluster only the lock actually bites, which is why it exists.
- **Injected clock and id generator.** No test depends on the wall clock or on randomness.

## Design documentation

The full design — ten documents covering every component, with the decision log — lives in
`.claude/docs/`. That directory is git-ignored, so it exists only in a working copy, not in a
fresh clone. `deploy/README.md` is committed and covers the deployment stack in full.

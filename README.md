# distributed-market

A distributed foreign-exchange trading venue for **USD/CAD**, built as four Python services in
containers on Kubernetes. It runs a central limit order book with a deterministic matching
engine, tracks per-account balances with fund reservation, and publishes live market data over
WebSocket.

> **Status: design complete, implementation not started.**
> The architecture is settled and every open question is answered; no service code exists yet.
> The commands below describe the intended workflow and will work as each phase lands — see
> *Project status* at the bottom for where things actually stand.

Built to the shape of a real exchange, deliberately not to the scale of one: persistence is
plain JSON files rather than a database, and the whole venue is meant to run on a laptop.

## What it does

- **Central limit order book** for USD/CAD with strict price-time (FIFO) priority
- **Limit and market orders**, with `GTC` and `IOC` time in force
- **Deterministic matching engine** — replaying its journal reproduces state exactly
- **Accounts with fund reservation** — an order is collateralized before it can trade, so a fill
  can never fail to settle
- **Self-trade prevention** — an account never trades with itself
- **Live market data** — sequenced L2 book deltas, trade prints, and a throttled ticker
- **Crash-safe JSON persistence** — append-only journal plus periodic snapshots
- **Container-native** — each component is its own image, its own Deployment, independently
  restartable

## Architecture

```
                    ┌──────────────┐
   REST  ──────────►│ API Gateway  │──── reserve/release ────►┌───────────────┐
   (order entry)    │   (N pods)   │                          │ Account       │
                    └──────┬───────┘                          │ Ledger        │
                           │ submit / cancel                  │  (1 pod)      │
                           ▼                                  └───────▲───────┘
                    ┌──────────────┐                                  │
                    │  Matching    │───── trade events (SSE) ─────────┘
                    │  Engine      │
                    │  (1 pod)     │───── event stream (SSE) ►┌───────────────┐
                    │  order book  │                          │ Market Data   │◄── WebSocket
                    └──────┬───────┘                          │  (N pods)     │     clients
                           │ journal + snapshots              └───────────────┘
                           ▼
                    ┌──────────────┐
                    │  JSON files  │  (PVC)
                    └──────────────┘
```

One authoritative engine owns the book; everything around it is stateless or derived. The
engine is the single serialization point — it assigns sequence numbers, journals every event
before acknowledging it, and publishes the stream the ledger and market-data service consume.

| Service | Replicas | State |
|---------|----------|-------|
| `gateway` | N | none — any pod serves any request |
| `engine` | **1** | owns the order book and the journal |
| `ledger` | 1 | owns account balances |
| `marketdata` | N | derived only; disposable |

## Repository layout

```
src/
  market_core/     shared library: types, money, events (vendored, not published)
  engine/          matching engine service
  ledger/          account ledger service
  gateway/         public REST API
  marketdata/      WebSocket market data service
data/              persistence root — journal, snapshots, state, config
deploy/            Dockerfiles, Kubernetes manifests, kind config — see deploy/README.md
tests/
.claude/docs/      design documentation (local only, not committed)
```

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Python | 3.11+ | 3.12 in the container images |
| Docker | any recent | builds images; also runs the compose inner loop |
| [kind](https://kind.sigs.k8s.io/) | 0.20+ | local Kubernetes cluster |
| `kubectl` | matching your kind node image | |
| `make` | GNU make | preinstalled on macOS and Linux |

No cloud account and no container registry are needed — images are built locally and side-loaded
into the cluster.

## Getting started

```bash
git clone <this repo> && cd distributed-market

make venv            # create .venv and install the project with dev extras
source .venv/bin/activate
make lint typecheck  # ruff + mypy
make test            # unit, property, replay, and service layers — fast
```

`make help` lists every target.

### Configuration you need locally

`data/config/api_keys.json` holds API-key hashes and is **git-ignored** — create it before
running the services:

```bash
python - <<'PY'
import hashlib, json, pathlib
key = "sk_test_alice"
pathlib.Path("data/config/api_keys.json").write_text(
    json.dumps({"sha256:" + hashlib.sha256(key.encode()).hexdigest(): "acct_0001"}, indent=2))
print("wrote data/config/api_keys.json for key:", key)
PY
```

`data/config/instruments.json` and `data/config/accounts.seed.json` are committed and need no
setup. Everything else under `data/` is generated at runtime and ignored by git.

### Inner loop — docker compose (seconds)

Fast iteration on service logic and the API contract. `data/` is bind-mounted from the repo, so
the journal is inspectable with `jq` in your working tree.

```bash
make build           # build all four images
make up              # start gateway, engine, ledger, marketdata
make seed            # deposit fixture balances into the seeded accounts
make smoke           # place crossing orders, assert a trade prints
make logs            # tail all services
make down
```

### Outer loop — kind (1–2 minutes)

The real deployment target. This is where probes, PVC behaviour, the single-engine guarantee,
and NetworkPolicy are actually exercised.

```bash
make keys                  # once: generate the git-ignored data/config/api_keys.json
make kind-up               # create cluster, install ingress-nginx, load images, apply manifests
kubectl -n distributed-market get pods
make smoke TARGET=kind
make kind-down
```

Requires `kind` (`brew install kind`). Routing is host-based, so there is nothing to add to
`/etc/hosts` — pass the host header instead:

```bash
curl -H 'Host: gateway.dm.local'    http://localhost/healthz
curl -H 'Host: marketdata.dm.local' http://localhost/healthz
```

Both loops run the same smoke test. If a change passes under compose but fails under kind, the
difference is real and worth investigating.

**[`deploy/README.md`](deploy/README.md)** explains how the images, compose stack, kind cluster,
and Kubernetes manifests fit together — including how traffic reaches the services, how the
single-engine guarantee is enforced, and the failure modes you are most likely to hit.

### Try it by hand

```bash
# place a limit order
curl -s localhost:8080/v1/orders \
  -H 'X-API-Key: sk_test_alice' -H 'content-type: application/json' \
  -d '{"client_order_id":"alice-001","symbol":"USDCAD","side":"BUY",
       "type":"LIMIT","time_in_force":"GTC","price":"1.37500","quantity":"1000.00"}'

curl -s localhost:8080/v1/book?depth=5      # aggregated L2 snapshot
curl -s localhost:8080/v1/accounts/me -H 'X-API-Key: sk_test_alice'

# stream market data (market data has its own ingress; the gateway is REST-only)
websocat ws://localhost:8081/ws <<< '{"op":"subscribe","channels":["book:USDCAD","trades:USDCAD"]}'
```

## Testing

```bash
make test        # unit + property + replay + service layers  (fast, every save)
make test-all    # adds the docker compose integration and fault-injection layers
```

| Layer | What it proves |
|-------|----------------|
| Unit | `market_core`, book operations, the pure matching function |
| Property (Hypothesis) | Invariants over randomized order flow — see below |
| Replay | Journal → identical state; snapshot + tail == full replay |
| Service | One FastAPI app against fakes, via `httpx` ASGI transport |
| Integration | All four services under compose, including fault injection |
| Cluster smoke | kind deployment end to end |

The invariants that matter most, asserted after *every* command in property tests:

- The book is never crossed
- Quantity is conserved: `filled + remaining + cancelled == original`
- **Money is conserved** — total USD and CAD across all accounts never change from trading
- Balances never go negative; `0 <= reserved <= total`
- Price-time priority holds; IOC orders never rest; no account ever trades with itself
- Replaying the journal reproduces state exactly

CI runs everything through the compose integration layer on every commit, budgeted under five
minutes. The kind smoke test runs on manifest changes and nightly.

## Key configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `DM_DATA_DIR` | `./data` locally, `/data` in-cluster | Persistence root |
| `DM_FSYNC_MODE` | `always` | `interval` / `never` for tests only |
| `DM_SNAPSHOT_EVERY` | `1000` events | Snapshot cadence |
| `DM_BAND_REFRESH` | `1s` | Price-band reference refresh |
| `DM_RESERVATION_TTL` | `60s` | Orphaned-reservation reaper threshold |
| `DM_LOG_LEVEL` | `INFO` | Structured JSON logs to stdout |

## Design notes worth knowing

- **Money is integers, never floats.** USD and CAD in cents, price in ticks of 0.00001 CAD per
  USD. A trade's notional rounds to the nearest cent with ties against the taker, and the same
  single value moves between both accounts — so rounding decides who absorbs the sub-cent, never
  whether cents appear or vanish.
- **Reserve, then trade.** The gateway secures collateral from the ledger before the engine sees
  the order. This is what removes any need for distributed transactions between services.
- **The engine is single-threaded and single-replica by design.** Determinism is worth more than
  throughput here; the journal is what a future replicated design would build on.
- **Balances are eventually consistent.** A balance read can lag a fill by one stream hop;
  responses carry `last_applied_seq` so a client can poll until its order is reflected. The
  reservation — not the balance — is what guarantees correctness.

## Project status

Design is closed: ten documents, every open question answered. Implementation is tracked in
eleven phases, each with exit criteria.

Because `.claude/` is git-ignored, the design docs and the progress tracker live only in the
working copy:

| | |
|---|---|
| Design docs | `.claude/docs/` — start with `README.md` (index + full decision log) |
| Progress tracker | `.claude/docs/10-implementation-progress.md` — current phase, session log, parked items |

**Not in this phase:** additional currency pairs, replicated or sharded matching, fees, margin,
real authentication or settlement, stop and iceberg orders, `FOK`/`GTD`.

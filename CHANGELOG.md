# Changelog

## v0.4.0 - 2026-06-21

- Added a **static HTML report** (`clusterdetect report`) that renders the
  clusters already in the database as a single self-contained page (token, tier,
  score, wallet count, total USD, detected-at). Pure templating, no JavaScript,
  no network — read-only presentation of public-data clusters.
- Added a **cluster graph export** (`clusterdetect graph --format json|dot|graphml`)
  that reshapes detected clusters into a bipartite wallet/token graph for offline
  visualisation in Gephi, Cytoscape or networkx. A wallet seen across clusters
  becomes one shared node. Pure transform of existing data; collects nothing new.
- Both are framework/presentation tooling — no new tracking or data collection.

## v0.3.0 - 2026-06-10

- Added a keyless **Base / EVM read adapter** (`clusterdetect.clients.evm`) that reconstructs swaps from on-chain ERC-20 `Transfer` logs and normalizes them into the same swap shape as the Solana parser. Opt in with `clusterdetect scan --chain base`; the default Solana path is unchanged. BYO endpoint via `EVM_RPC_URL`, otherwise the free public Base RPC is used.
- Added an **inbound webhook receiver** (`clusterdetect.schedule.webhook` + `clusterdetect webhook`) that accepts a Helius-style swap payload for lower-latency cluster capture. HMAC-SHA256 signature-verified (BYO `WEBHOOK_SECRET`, constant-time check, no default secret), feeds the existing pipeline, and never trades.
- Added examples for both (`examples/base_adapter`, `examples/webhook`) that run fully offline, plus fixtured tests with no live network.

## v0.2.0 - 2026-06-04

- Added an opt-in Pump.fun graduation filter with `filters.pumpfun_graduation` and `clusterdetect scan --graduated-only`.
- Added Discord webhook alerts with `alert.channel = telegram|discord|both`.
- Added `clusterdetect export` and `clusterdetect rank` for cluster CSV/JSON export and leaderboard review.

## v0.1.0 - 2026-06-03

- Initial public MIT release of `wallet-cluster-detector`.
- Added Helius client with rate limiting, circuit breaker, key rotation, credit tracking, and signature-first polling.
- Added swap parser, score-weighted cluster detector, generic rule reasoner, watchlist winner-discovery, paper trader, Telegram alerts, optional Gemini commentary, scheduler emitters, examples, docs, and tests.

## Roadmap

- v0.3: webhook subscription adapter. (shipped)
- v0.3: Base wallet-tracking once the wallet layer is wired. (shipped: read adapter)
- v0.4: cluster scoring by recency and public paper-trade performance.
- v0.4: stronger anti-honeypot checks around LP and mint authority data.

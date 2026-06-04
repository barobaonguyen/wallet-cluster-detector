# Changelog

## v0.2.0 - 2026-06-04

- Added an opt-in Pump.fun graduation filter with `filters.pumpfun_graduation` and `clusterdetect scan --graduated-only`.
- Added Discord webhook alerts with `alert.channel = telegram|discord|both`.
- Added `clusterdetect export` and `clusterdetect rank` for cluster CSV/JSON export and leaderboard review.

## v0.1.0 - 2026-06-03

- Initial public MIT release of `wallet-cluster-detector`.
- Added Helius client with rate limiting, circuit breaker, key rotation, credit tracking, and signature-first polling.
- Added swap parser, score-weighted cluster detector, generic rule reasoner, watchlist winner-discovery, paper trader, Telegram alerts, optional Gemini commentary, scheduler emitters, examples, docs, and tests.

## Roadmap

- v0.3: webhook subscription adapter.
- v0.3: Base wallet-tracking once the wallet layer is wired.
- v0.3: cluster scoring by recency and public paper-trade performance.
- v0.3: stronger anti-honeypot checks around LP and mint authority data.

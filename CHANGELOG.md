# Changelog

## v0.1.0 - 2026-06-03

- Initial public MIT release of `wallet-cluster-detector`.
- Added Helius client with rate limiting, circuit breaker, key rotation, credit tracking, and signature-first polling.
- Added swap parser, score-weighted cluster detector, generic rule reasoner, watchlist winner-discovery, paper trader, Telegram alerts, optional Gemini commentary, scheduler emitters, examples, docs, and tests.

## Roadmap

- v0.2: webhook subscription adapter.
- v0.2: Base wallet-tracking once the wallet layer is wired.
- v0.3: cluster scoring by recency and public paper-trade performance.
- v0.3: stronger anti-honeypot checks around LP and mint authority data.

# Quickstart

1. Copy `.env.example` to `.env` and add a Helius key.
2. Initialize SQLite:

```bash
clusterdetect init-db
```

3. Run the no-key discovery demo:

```bash
clusterdetect discover 20 --dry
```

4. Add your own watchlist CSV or run full discovery with a Helius key.
5. Run a single scan:

```bash
clusterdetect scan
```

Use paper trading before any live execution. The defaults are round examples, not tuned values.

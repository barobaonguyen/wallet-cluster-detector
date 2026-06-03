# Watchlist Building

This repository does not ship a real smart-wallet list.

The public method:

1. Collect recent Solana pools from GeckoTerminal trending/new pools and DexScreener boosts.
2. Filter for coarse winner behavior and basic quality.
3. Walk pool signature history backward.
4. Parse the oldest usable pages.
5. Count wallets that received the token early across multiple winners.
6. Store the top addresses with a score equal to appearances.

Run the dry demo without a key:

```bash
clusterdetect discover 20 --dry
```

Full wallet extraction needs a Helius key because it parses transaction history.

# Base / EVM read adapter

`clusterdetect` started Solana-only. v0.3.0 adds a keyless **Base** read adapter
(`clusterdetect.clients.evm`) that reconstructs swaps from on-chain ERC-20
`Transfer` logs and normalizes them into the *same* shape the Solana swap parser
produces, so the existing cluster detector runs on Base unchanged.

## Offline demo (no RPC, no keys)

```bash
python examples/base_adapter/run_base.py
```

It builds a fixture of three Base wallets buying the same token inside a window
and shows the normalized swaps plus the detected cluster.

## Live scan on Base

1. Add Base wallets to your watchlist with `chain=base`:

   ```csv
   address,score,label,chain
   0xYourScoredBaseWallet000000000000000000000,3,demo,base
   ```

2. Opt in via `--chain base` (the default `solana` path is untouched):

   ```bash
   clusterdetect scan --chain base
   ```

By default it reads the free public Base RPC (`https://mainnet.base.org`). For
higher rate limits, bring your own endpoint via `EVM_RPC_URL` in `.env`.

The on-chain `Transfer` event has no price, so `usd_value` starts `None`;
DexScreener-on-Base enrichment fills price downstream, exactly like Solana.

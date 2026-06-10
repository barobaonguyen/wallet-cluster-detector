# Webhook receiver

Polling Helius costs credits and adds latency. v0.3.0 adds an **inbound webhook
receiver** (`clusterdetect.schedule.webhook`) that accepts a Helius-style swap
payload the moment a transaction lands, verifies an HMAC-SHA256 signature, and
feeds the swaps into the existing pipeline (same `parse_swap`, same
`ClusterDetector`, same `save_clusters`).

## Offline demo (no socket, no keys)

```bash
python examples/webhook/post_swap.py
```

It signs a fixture payload, verifies the signature, then ingests three wallets
buying the same token and reports the detected cluster.

## Run the real receiver

```bash
WEBHOOK_SECRET=your-shared-secret clusterdetect webhook --host 127.0.0.1 --port 8787
```

Point your Helius webhook at it and configure the same shared secret. Every
request must carry:

```
X-Webhook-Signature: sha256=<hex hmac-sha256 of the raw body, keyed by WEBHOOK_SECRET>
```

Security notes:

- There is **no default secret**. An unset `WEBHOOK_SECRET` rejects every request.
- The signature check is constant-time (`hmac.compare_digest`).
- The receiver only writes to local SQLite — it performs no trades.

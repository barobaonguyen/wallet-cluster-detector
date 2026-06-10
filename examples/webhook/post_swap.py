"""Webhook receiver demo — sign a Helius-style payload and ingest it offline.

This proves the inbound webhook path end-to-end without opening a socket:
it signs a fixture payload with a shared secret, verifies the signature, and
feeds the swaps into the existing pipeline (persist + cluster detection).

Run:

    python examples/webhook/post_swap.py

To run the real receiver and POST to it:

    WEBHOOK_SECRET=your-secret clusterdetect webhook --host 127.0.0.1 --port 8787
    # then POST signed JSON to http://127.0.0.1:8787 with an
    # X-Webhook-Signature: sha256=<hmac> header.
"""

from __future__ import annotations

import json

from clusterdetect.config import Config
from clusterdetect.db import conn, init_db, upsert_wallet
from clusterdetect.schedule.webhook import ingest_payload, sign_payload, verify_signature

SECRET = "demo-shared-secret"
MEME = "MemeMintDemo444444444444444444444444444444"
WALLETS = [
    "WalletAlphaDemo111111111111111111111111111",
    "WalletBravoDemo222222222222222222222222222",
    "WalletCharlieDemo3333333333333333333333333",
]


def _swap_tx(signature: str, wallet: str, ts: int) -> dict:
    return {
        "type": "SWAP",
        "signature": signature,
        "timestamp": ts,
        "source": "JUPITER",
        "feePayer": wallet,
        "events": {
            "swap": {
                "tokenInputs": [],
                "tokenOutputs": [
                    {
                        "userAccount": wallet,
                        "mint": MEME,
                        "rawTokenAmount": {"tokenAmount": "1000", "decimals": 0},
                    }
                ],
                "nativeInput": {"account": wallet, "amount": "500000000"},
            }
        },
    }


def main() -> None:
    import time

    init_db()
    with conn() as c:
        for wallet in WALLETS:
            upsert_wallet(c, wallet, "demo", score=1, added_at=1)

    now = int(time.time())
    payload = [_swap_tx(f"sig{i}", wallet, now - 30 + i) for i, wallet in enumerate(WALLETS)]
    body = json.dumps(payload).encode("utf-8")

    header = sign_payload(SECRET, body)
    print(f"signature header: {header}")
    print(f"signature valid:  {verify_signature(SECRET, body, header)}")
    print(f"tampered rejected:{verify_signature(SECRET, body + b' ', header)}")

    cfg = Config(
        helius_api_keys=["demo"],
        cluster_min_wallets=3,
        cluster_window_minutes=15,
        cluster_min_total_score=3,
    )
    summary = ingest_payload(payload, cfg, sol_price_usd=100.0)
    print(f"\ningested: {summary}")


if __name__ == "__main__":
    main()

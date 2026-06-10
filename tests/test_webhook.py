"""Tests for the inbound webhook receiver. Fixtured payloads, no live network."""

from __future__ import annotations

import json

from clusterdetect.config import Config
from clusterdetect.db import conn, upsert_wallet
from clusterdetect.schedule.webhook import (
    ingest_payload,
    make_handler,
    sign_payload,
    verify_signature,
)

WALLET_A = "WalletAlphaDemo111111111111111111111111111"
WALLET_B = "WalletBravoDemo222222222222222222222222222"
WALLET_C = "WalletCharlieDemo3333333333333333333333333"
MEME = "MemeMintDemo444444444444444444444444444444"

SECRET = "test-shared-secret"


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


def test_verify_signature_roundtrip_and_rejection():
    body = b'{"hello":"world"}'
    header = sign_payload(SECRET, body)
    assert verify_signature(SECRET, body, header) is True
    # Without the sha256= prefix is also accepted.
    bare = header.split("=", 1)[1]
    assert verify_signature(SECRET, body, bare) is True
    # Wrong secret, tampered body, missing header, unset secret all fail.
    assert verify_signature("wrong", body, header) is False
    assert verify_signature(SECRET, b'{"hello":"evil"}', header) is False
    assert verify_signature(SECRET, body, None) is False
    assert verify_signature(None, body, header) is False


def test_ingest_payload_persists_and_detects_cluster():
    cfg = Config(
        helius_api_keys=["x"],
        cluster_min_wallets=3,
        cluster_window_minutes=15,
        cluster_min_total_score=3,
    )
    base_ts = int(__import__("time").time())
    with conn() as c:
        for w in (WALLET_A, WALLET_B, WALLET_C):
            upsert_wallet(c, w, "test", score=1, added_at=1)

    payload = [
        _swap_tx("sigA", WALLET_A, base_ts - 30),
        _swap_tx("sigB", WALLET_B, base_ts - 20),
        _swap_tx("sigC", WALLET_C, base_ts - 10),
    ]
    summary = ingest_payload(payload, cfg, sol_price_usd=100.0)

    assert summary["received"] == 3
    assert summary["inserted"] == 3
    assert summary["clusters"] == 1

    with conn() as c:
        n = c.execute("SELECT COUNT(*) AS n FROM swaps WHERE token_mint=?", (MEME,)).fetchone()["n"]
        clusters = c.execute(
            "SELECT wallet_count FROM clusters WHERE token_mint=?", (MEME,)
        ).fetchone()
    assert n == 3
    assert clusters["wallet_count"] == 3


def test_ingest_single_tx_and_idempotent():
    cfg = Config(helius_api_keys=["x"])
    ts = int(__import__("time").time())
    payload = _swap_tx("sigSolo", WALLET_A, ts)
    first = ingest_payload(payload, cfg, sol_price_usd=50.0, detect=False)
    second = ingest_payload(payload, cfg, sol_price_usd=50.0, detect=False)
    assert first["inserted"] == 1
    assert second["inserted"] == 0  # INSERT OR IGNORE dedupes by signature


def test_handler_rejects_bad_signature_and_accepts_signed():
    cfg = Config(helius_api_keys=["x"])
    handler_cls = make_handler(SECRET, cfg)

    # Build a minimal fake request harness around the handler's logic.
    body = json.dumps(_swap_tx("sigH", WALLET_A, int(__import__("time").time()))).encode()

    class _FakeWFile:
        def __init__(self) -> None:
            self.data = b""

        def write(self, b: bytes) -> None:
            self.data += b

    class _Recorder(handler_cls):  # type: ignore[valid-type, misc]
        def __init__(self, headers: dict, raw: bytes) -> None:
            self._headers = headers
            self._raw = raw
            self.headers = headers
            self.rfile = __import__("io").BytesIO(raw)
            self.wfile = _FakeWFile()
            self.status = None

        def send_response(self, code: int, *a) -> None:
            self.status = code

        def send_header(self, *a) -> None:
            pass

        def end_headers(self) -> None:
            pass

    good = _Recorder(
        {"Content-Length": str(len(body)), "X-Webhook-Signature": sign_payload(SECRET, body)},
        body,
    )
    good.do_POST()
    assert good.status == 200

    bad = _Recorder(
        {"Content-Length": str(len(body)), "X-Webhook-Signature": "sha256=deadbeef"},
        body,
    )
    bad.do_POST()
    assert bad.status == 401

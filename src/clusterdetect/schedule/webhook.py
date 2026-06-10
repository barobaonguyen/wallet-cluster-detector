"""Inbound webhook receiver for lower-latency cluster capture.

Polling Helius costs credits and adds latency. A Helius (or compatible) webhook
pushes enhanced SWAP transactions to *you* the moment they land, so clusters are
captured sooner. This module:

- verifies an HMAC-SHA256 signature so only your configured sender is trusted
  (BYO ``WEBHOOK_SECRET``; reject everything else),
- parses each pushed transaction with the *existing* ``parse_swap`` (Solana) so the
  swap shape is identical to the polling path,
- persists the swaps and runs the existing ``ClusterDetector`` + ``save_clusters``
  so detection logic is shared, not duplicated.

The pure functions ``verify_signature`` and ``ingest_payload`` do no network I/O,
so tests run against a fixture payload with no live calls. ``run_server`` wraps
them in a stdlib ``http.server`` for production; it is import-safe and never opens
a socket at import time.

Security: the receiver only ingests data into your local SQLite. It performs no
trades. The signature check is constant-time. There is no default secret — an
unset ``WEBHOOK_SECRET`` rejects every request.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from clusterdetect.config import Config
from clusterdetect.domain.cluster import ClusterDetector, save_clusters
from clusterdetect.domain.swap_parser import parse_swap

log = logging.getLogger(__name__)

# Header Helius sends its shared-secret check in. Configurable per deployment.
SIGNATURE_HEADER = "X-Webhook-Signature"


def verify_signature(secret: str | None, body: bytes, provided: str | None) -> bool:
    """Constant-time HMAC-SHA256 check of a raw request body.

    Returns ``False`` (never raises) when the secret is unset, the header is
    missing, or the digests differ. ``provided`` may carry an optional
    ``"sha256="`` prefix, matching common webhook conventions.
    """

    if not secret or not provided:
        return False
    candidate = provided.split("=", 1)[1] if provided.startswith("sha256=") else provided
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, candidate.strip())


def sign_payload(secret: str, body: bytes) -> str:
    """Helper to produce the ``sha256=...`` header value (used by tests/examples)."""

    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _normalise_swaps(payload: Any, sol_price_usd: float | None) -> list[dict[str, Any]]:
    """Turn a Helius webhook payload (one tx or a list) into normalized swaps."""

    transactions = payload if isinstance(payload, list) else [payload]
    swaps: list[dict[str, Any]] = []
    for tx in transactions:
        if not isinstance(tx, dict):
            continue
        wallet = _infer_wallet(tx)
        if not wallet:
            continue
        parsed = parse_swap(tx, wallet, sol_price_usd)
        if parsed:
            swaps.append(parsed)
    return swaps


def _infer_wallet(tx: dict[str, Any]) -> str | None:
    """Pick the wallet POV for a pushed tx.

    Helius webhooks let you attach the watched address as ``accountData`` /
    ``feePayer``; we prefer an explicit ``wallet`` field, then ``feePayer``, then
    the swap's native input account.
    """

    if tx.get("wallet"):
        return str(tx["wallet"])
    if tx.get("feePayer"):
        return str(tx["feePayer"])
    swap = (tx.get("events") or {}).get("swap") or {}
    native_input = swap.get("nativeInput") or {}
    if native_input.get("account"):
        return str(native_input["account"])
    return None


def ingest_payload(
    payload: Any,
    cfg: Config,
    *,
    sol_price_usd: float | None = None,
    detect: bool = True,
) -> dict[str, int]:
    """Persist swaps from a verified payload and (optionally) run cluster detection.

    Pure with respect to the network: it only touches the local SQLite via the
    shared ``db`` helpers and reuses ``ClusterDetector`` / ``save_clusters``. Returns
    a small summary dict for the caller / HTTP response.
    """

    from clusterdetect.db import conn, init_db

    init_db()
    swaps = _normalise_swaps(payload, sol_price_usd)
    inserted = 0
    if swaps:
        with conn() as c:
            for swap in swaps:
                cur = c.execute(
                    """INSERT OR IGNORE INTO swaps
                       (signature, wallet, timestamp, side, token_mint, token_amount,
                        sol_amount, usd_value, source, raw, chain)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        swap["signature"],
                        swap["wallet"],
                        swap["timestamp"],
                        swap["side"],
                        swap["token_mint"],
                        swap["token_amount"],
                        swap["sol_amount"],
                        swap["usd_value"],
                        swap["source"],
                        None,
                        "solana",
                    ),
                )
                inserted += cur.rowcount if cur.rowcount > 0 else 0

    clusters_found = 0
    if detect and inserted:
        window = max(30, cfg.cluster_window_minutes * 2) * 60
        end_ts = int(time.time())
        start_ts = end_ts - window
        with conn() as c:
            rows = [
                dict(r)
                for r in c.execute(
                    """SELECT * FROM swaps WHERE timestamp BETWEEN ? AND ?
                       AND side='buy' AND chain='solana' ORDER BY timestamp""",
                    (start_ts, end_ts),
                ).fetchall()
            ]
            wallet_scores = {
                r["address"]: r["score"] or 1
                for r in c.execute("SELECT address, score FROM wallets WHERE enabled=1").fetchall()
            }
        detector = ClusterDetector(
            min_wallets=cfg.cluster_min_wallets,
            window_minutes=cfg.cluster_window_minutes,
            min_total_score=cfg.cluster_min_total_score,
            min_usd=cfg.min_buy_usd,
        )
        clusters = detector.detect(rows, wallet_scores)
        clusters_found = save_clusters(list(clusters))

    return {"received": len(swaps), "inserted": inserted, "clusters": clusters_found}


def make_handler(secret: str | None, cfg: Config) -> type[BaseHTTPRequestHandler]:
    """Build a request handler bound to a secret + config (factory keeps state out of globals)."""

    class WebhookHandler(BaseHTTPRequestHandler):
        server_version = "wallet-cluster-detector-webhook/0.3"

        def _reply(self, status: int, body: dict[str, Any]) -> None:
            data = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:  # noqa: N802 (stdlib API name)
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            provided = self.headers.get(SIGNATURE_HEADER)
            if not verify_signature(secret, raw, provided):
                log.warning("webhook: rejected unsigned/invalid request")
                self._reply(401, {"error": "invalid signature"})
                return
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else None
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._reply(400, {"error": "invalid json"})
                return
            try:
                summary = ingest_payload(payload, cfg)
            except Exception as exc:  # pragma: no cover - defensive
                log.error("webhook ingest failed: %s", exc)
                self._reply(500, {"error": "ingest failed"})
                return
            self._reply(200, summary)

        def log_message(self, *_args: Any) -> None:  # pragma: no cover - silence stdlib logger
            pass

    return WebhookHandler


def run_server(
    cfg: Config,
    *,
    host: str = "127.0.0.1",
    port: int = 8787,
    secret: str | None = None,
) -> None:  # pragma: no cover - blocking network loop
    """Run a blocking webhook server. BYO secret via arg or ``WEBHOOK_SECRET`` env."""

    import os

    secret = secret or os.getenv("WEBHOOK_SECRET")
    if not secret:
        raise ValueError("WEBHOOK_SECRET is required to run the webhook receiver")
    handler = make_handler(secret, cfg)
    httpd = HTTPServer((host, port), handler)
    log.info("webhook receiver listening on http://%s:%s", host, port)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()

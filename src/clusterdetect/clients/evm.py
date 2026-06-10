"""Base / EVM read adapter.

Fetches a wallet's recent swaps from a free, keyless public EVM JSON-RPC
endpoint (default: Base mainnet) and normalises them into the *same* swap shape
that ``domain.swap_parser.parse_swap`` yields for Solana, so the existing
score-weighted cluster detector runs unchanged on Base.

Design notes
------------
- We only *read* ERC-20 ``Transfer`` logs that touch the watched wallet. A swap
  is reconstructed as "wallet sent token A, wallet received token B" inside one
  transaction. If the stable/native leg is a known Base stable (WETH/USDC/USDT),
  the non-stable leg is the meme being bought or sold.
- The on-chain ``Transfer`` event carries no USD value. ``usd_value`` is left as
  ``None`` here; enrichment (DexScreener on Base) fills price downstream just like
  on Solana. ``sol_amount`` keeps the existing column name but holds the native /
  stable-leg amount so the cluster detector's plumbing stays identical.
- The pure ``parse_evm_logs`` function takes already-decoded RPC logs and does no
  network I/O, so tests run entirely against a fixture response.

BYO: set ``EVM_RPC_URL`` for a private/faster endpoint; otherwise the free public
RPC for the chain is used. This adapter is opt-in via ``--chain base`` on the CLI;
the default Solana path is untouched.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from clusterdetect.config import (
    EVM_CHAIN_IDS,
    EVM_RPC_DEFAULTS,
    STABLES_BY_CHAIN,
)

log = logging.getLogger(__name__)

# keccak256("Transfer(address,address,uint256)")
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# How many EVM blocks back to scan by default. Base produces ~1 block / 2s, so
# 7_200 blocks is roughly the last four hours, comfortably inside a cluster window.
DEFAULT_LOOKBACK_BLOCKS = 7_200


def _hex_to_int(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    try:
        return int(str(value), 16)
    except (TypeError, ValueError):
        return 0


def _topic_to_address(topic: str | None) -> str | None:
    """A 32-byte log topic that holds an address is right-aligned; take last 40 hex."""

    if not topic or not isinstance(topic, str):
        return None
    body = topic[2:] if topic.startswith("0x") else topic
    if len(body) < 40:
        return None
    return "0x" + body[-40:].lower()


def _transfer_amount(data: str | None, decimals: int) -> float:
    raw = _hex_to_int(data)
    if raw == 0:
        return 0.0
    try:
        return raw / (10**decimals)
    except (ArithmeticError, ValueError):
        return float(raw)


def parse_evm_logs(
    logs: list[dict[str, Any]],
    wallet: str,
    *,
    chain: str = "base",
    decimals: dict[str, int] | None = None,
    timestamps: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Reconstruct normalized swaps from raw ERC-20 ``Transfer`` logs for one wallet.

    ``logs`` are the decoded ``eth_getLogs`` entries (each a dict with ``topics``,
    ``data``, ``address``, ``transactionHash``, ``blockNumber``). ``decimals`` maps
    a lowercase token address to its ERC-20 decimals (default 18 when unknown).
    ``timestamps`` optionally maps a lowercase tx hash to a unix timestamp.

    The output dicts match exactly what ``swap_parser.parse_swap`` returns, with an
    added ``chain`` key, so the cluster detector treats Base and Solana identically.
    """

    wallet_lc = wallet.lower()
    decimals = decimals or {}
    timestamps = timestamps or {}
    stables = {s.lower() for s in STABLES_BY_CHAIN.get(chain, set())}

    # Group transfers that involve the wallet by transaction hash.
    by_tx: dict[str, dict[str, Any]] = {}
    for entry in logs:
        topics = entry.get("topics") or []
        if not topics or (topics[0] or "").lower() != TRANSFER_TOPIC:
            continue
        if len(topics) < 3:
            continue
        token = (entry.get("address") or "").lower()
        if not token:
            continue
        sender = _topic_to_address(topics[1])
        recipient = _topic_to_address(topics[2])
        if wallet_lc not in {sender, recipient}:
            continue
        tx_hash = (entry.get("transactionHash") or "").lower()
        if not tx_hash:
            continue
        amount = _transfer_amount(entry.get("data"), decimals.get(token, 18))
        bucket = by_tx.setdefault(
            tx_hash,
            {"sent": {}, "received": {}, "block": _hex_to_int(entry.get("blockNumber"))},
        )
        direction = "sent" if sender == wallet_lc else "received"
        bucket[direction][token] = bucket[direction].get(token, 0.0) + amount

    swaps: list[dict[str, Any]] = []
    for tx_hash, bucket in by_tx.items():
        sent: dict[str, float] = bucket["sent"]
        received: dict[str, float] = bucket["received"]
        if not sent or not received:
            continue

        sent_non_stable = {t: a for t, a in sent.items() if t not in stables and a > 0}
        recv_non_stable = {t: a for t, a in received.items() if t not in stables and a > 0}
        sent_stable_total = sum(a for t, a in sent.items() if t in stables)
        recv_stable_total = sum(a for t, a in received.items() if t in stables)

        side: str | None = None
        token_mint: str | None = None
        token_amount = 0.0
        native_amount = 0.0

        if recv_non_stable and (sent_stable_total > 0 or not sent_non_stable):
            # Spent stable/native, received a meme => buy.
            side = "buy"
            token_mint, token_amount = max(recv_non_stable.items(), key=lambda kv: kv[1])
            native_amount = sent_stable_total
        elif sent_non_stable and (recv_stable_total > 0 or not recv_non_stable):
            # Sent a meme, received stable/native => sell.
            side = "sell"
            token_mint, token_amount = max(sent_non_stable.items(), key=lambda kv: kv[1])
            native_amount = recv_stable_total

        if not side or not token_mint:
            continue

        swaps.append(
            {
                "signature": tx_hash,
                "wallet": wallet,
                "timestamp": timestamps.get(tx_hash),
                "side": side,
                "token_mint": token_mint,
                "token_amount": token_amount,
                "sol_amount": native_amount,
                "usd_value": None,
                "source": chain,
                "chain": chain,
            }
        )
    return swaps


class EvmClient:
    """Minimal keyless EVM JSON-RPC reader for swap reconstruction."""

    def __init__(
        self,
        *,
        chain: str = "base",
        rpc_url: str | None = None,
        timeout: float = 20.0,
    ):
        chain = chain.lower()
        if chain not in EVM_CHAIN_IDS:
            raise ValueError(f"unsupported EVM chain: {chain!r} (known: {sorted(EVM_CHAIN_IDS)})")
        self.chain = chain
        self.rpc_url = rpc_url or EVM_RPC_DEFAULTS[chain]
        self.client = httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": "wallet-cluster-detector/0.3"},
        )
        self._rpc_id = 0

    async def close(self) -> None:
        await self.client.aclose()

    async def _rpc(self, method: str, params: list[Any]) -> Any:
        self._rpc_id += 1
        payload = {"jsonrpc": "2.0", "id": self._rpc_id, "method": method, "params": params}
        try:
            r = await self.client.post(self.rpc_url, json=payload)
            if r.status_code != 200:
                log.warning("evm rpc %s: HTTP %s", method, r.status_code)
                return None
            data = r.json()
        except Exception as exc:
            log.warning("evm rpc %s failed: %s", method, exc)
            return None
        if isinstance(data, dict) and data.get("error"):
            log.warning("evm rpc %s error: %s", method, data["error"])
            return None
        return data.get("result") if isinstance(data, dict) else None

    async def latest_block(self) -> int:
        return _hex_to_int(await self._rpc("eth_blockNumber", []))

    async def _block_timestamp(self, block_hex: str) -> int | None:
        block = await self._rpc("eth_getBlockByNumber", [block_hex, False])
        if not isinstance(block, dict):
            return None
        return _hex_to_int(block.get("timestamp")) or None

    async def _token_decimals(self, token: str) -> int:
        # ERC-20 decimals() selector 0x313ce567; default to 18 on any failure.
        result = await self._rpc("eth_call", [{"to": token, "data": "0x313ce567"}, "latest"])
        decoded = _hex_to_int(result)
        return decoded if 0 < decoded <= 36 else 18

    async def fetch_swaps(
        self,
        wallet: str,
        *,
        lookback_blocks: int = DEFAULT_LOOKBACK_BLOCKS,
    ) -> list[dict[str, Any]]:
        """Fetch and normalise a wallet's recent swaps from on-chain Transfer logs."""

        latest = await self.latest_block()
        if latest <= 0:
            return []
        from_block = max(0, latest - max(1, lookback_blocks))
        topic_wallet = "0x" + "0" * 24 + wallet.lower().removeprefix("0x")
        # Query both legs: wallet as sender (topic1) and as recipient (topic2).
        logs: list[dict[str, Any]] = []
        for topic_slot in ([TRANSFER_TOPIC, topic_wallet], [TRANSFER_TOPIC, None, topic_wallet]):
            result = await self._rpc(
                "eth_getLogs",
                [
                    {
                        "fromBlock": hex(from_block),
                        "toBlock": hex(latest),
                        "topics": topic_slot,
                    }
                ],
            )
            if isinstance(result, list):
                logs.extend(result)

        tokens = {(entry.get("address") or "").lower() for entry in logs if entry.get("address")}
        decimals = {token: await self._token_decimals(token) for token in tokens if token}

        blocks = {(entry.get("blockNumber") or "") for entry in logs if entry.get("blockNumber")}
        block_ts = {block: await self._block_timestamp(block) for block in blocks}
        timestamps: dict[str, int] = {}
        for entry in logs:
            tx_hash = (entry.get("transactionHash") or "").lower()
            ts = block_ts.get(entry.get("blockNumber"))
            if tx_hash and ts is not None:
                timestamps[tx_hash] = ts
        return parse_evm_logs(
            logs,
            wallet,
            chain=self.chain,
            decimals=decimals,
            timestamps=timestamps,
        )

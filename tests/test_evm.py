"""Tests for the Base/EVM read adapter. No live calls: a fixture RPC is injected."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from clusterdetect.clients.evm import EvmClient, parse_evm_logs
from clusterdetect.config import USDC_BASE, WETH_BASE

WALLET = "0x1111111111111111111111111111111111111111"
MEME = "0x22222222222222222222222222222222222222ab"
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def _topic_addr(addr: str) -> str:
    return "0x" + "0" * 24 + addr.lower().removeprefix("0x")


def _hex18(value: float) -> str:
    return hex(int(value * 10**18))


def _hex6(value: float) -> str:
    return hex(int(value * 10**6))


def test_parse_evm_logs_buy_and_sell_and_shape():
    # tx1: wallet spends 0.5 WETH, receives 1000 MEME => buy.
    # tx2: wallet sends 400 MEME, receives 200 USDC => sell.
    logs: list[dict[str, Any]] = [
        {
            "address": WETH_BASE,
            "topics": [TRANSFER, _topic_addr(WALLET), _topic_addr(MEME)],
            "data": _hex18(0.5),
            "transactionHash": "0xtx1",
            "blockNumber": "0x10",
        },
        {
            "address": MEME,
            "topics": [TRANSFER, _topic_addr(MEME), _topic_addr(WALLET)],
            "data": _hex18(1000),
            "transactionHash": "0xtx1",
            "blockNumber": "0x10",
        },
        {
            "address": MEME,
            "topics": [TRANSFER, _topic_addr(WALLET), _topic_addr(MEME)],
            "data": _hex18(400),
            "transactionHash": "0xtx2",
            "blockNumber": "0x11",
        },
        {
            "address": USDC_BASE,
            "topics": [TRANSFER, _topic_addr(MEME), _topic_addr(WALLET)],
            "data": _hex6(200),
            "transactionHash": "0xtx2",
            "blockNumber": "0x11",
        },
    ]
    decimals = {MEME.lower(): 18, WETH_BASE.lower(): 18, USDC_BASE.lower(): 6}
    timestamps = {"0xtx1": 1000, "0xtx2": 1100}
    swaps = parse_evm_logs(logs, WALLET, chain="base", decimals=decimals, timestamps=timestamps)
    by_side = {s["side"]: s for s in swaps}

    assert set(by_side) == {"buy", "sell"}
    buy = by_side["buy"]
    # Same normalized shape as parse_swap, plus a chain key.
    assert set(buy) == {
        "signature",
        "wallet",
        "timestamp",
        "side",
        "token_mint",
        "token_amount",
        "sol_amount",
        "usd_value",
        "source",
        "chain",
    }
    assert buy["token_mint"] == MEME.lower()
    assert buy["token_amount"] == pytest.approx(1000)
    assert buy["sol_amount"] == pytest.approx(0.5)
    assert buy["usd_value"] is None
    assert buy["chain"] == "base"
    assert buy["timestamp"] == 1000

    sell = by_side["sell"]
    assert sell["token_mint"] == MEME.lower()
    assert sell["token_amount"] == pytest.approx(400)
    assert sell["sol_amount"] == pytest.approx(200)


def test_parse_evm_logs_ignores_unrelated_and_stable_only():
    other = "0x9999999999999999999999999999999999999999"
    logs = [
        # Transfer between two third parties, wallet not involved.
        {
            "address": MEME,
            "topics": [TRANSFER, _topic_addr(other), _topic_addr(other)],
            "data": _hex18(5),
            "transactionHash": "0xtx3",
            "blockNumber": "0x12",
        },
        # Stable-only movement for the wallet (no meme leg) => not a swap.
        {
            "address": USDC_BASE,
            "topics": [TRANSFER, _topic_addr(WALLET), _topic_addr(other)],
            "data": _hex6(50),
            "transactionHash": "0xtx4",
            "blockNumber": "0x12",
        },
    ]
    assert parse_evm_logs(logs, WALLET, chain="base") == []


def test_unsupported_chain_raises():
    with pytest.raises(ValueError):
        EvmClient(chain="ethereum")


@pytest.mark.asyncio
async def test_fetch_swaps_against_fixture_rpc():
    """Drive EvmClient.fetch_swaps with a stubbed JSON-RPC transport (no network)."""

    latest_block = 0x100
    log_entry = {
        "address": MEME,
        "topics": [TRANSFER, _topic_addr(MEME), _topic_addr(WALLET)],
        "data": _hex18(1000),
        "transactionHash": "0xabc",
        "blockNumber": hex(latest_block),
    }
    weth_in = {
        "address": WETH_BASE,
        "topics": [TRANSFER, _topic_addr(WALLET), _topic_addr(MEME)],
        "data": _hex18(0.5),
        "transactionHash": "0xabc",
        "blockNumber": hex(latest_block),
    }

    async def fake_post(url: str, json: dict[str, Any]) -> httpx.Response:
        method = json["method"]
        req = httpx.Request("POST", url)
        if method == "eth_blockNumber":
            result: Any = hex(latest_block)
        elif method == "eth_getLogs":
            topics = json["params"][0]["topics"]
            # First query: wallet as recipient slot (topic2). Second: sender slot.
            if len(topics) == 3 and topics[2] == _topic_addr(WALLET):
                result = [log_entry]
            elif len(topics) == 2:
                result = [weth_in]
            else:
                result = []
        elif method == "eth_call":
            result = hex(18)
        elif method == "eth_getBlockByNumber":
            result = {"timestamp": hex(1700000000)}
        else:
            result = None
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": json["id"], "result": result}, request=req
        )

    evm = EvmClient(chain="base")
    evm.client.post = fake_post  # type: ignore[assignment]
    try:
        swaps = await evm.fetch_swaps(WALLET, lookback_blocks=50)
    finally:
        await evm.close()

    assert len(swaps) == 1
    swap = swaps[0]
    assert swap["side"] == "buy"
    assert swap["token_mint"] == MEME.lower()
    assert swap["chain"] == "base"
    assert swap["timestamp"] == 1700000000

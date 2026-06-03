import httpx
import pytest

from clusterdetect.clients.enrichers import Enricher


@pytest.mark.asyncio
async def test_enrichers_mocked():
    def handler(request: httpx.Request) -> httpx.Response:
        path = str(request.url)
        if "tokens/v1/solana/mintA" in path:
            return httpx.Response(
                200,
                json=[
                    {
                        "chainId": "solana",
                        "pairAddress": "pool1",
                        "dexId": "raydium",
                        "priceUsd": "1.2",
                        "liquidity": {"usd": 10},
                        "baseToken": {"address": "mintA", "symbol": "A", "name": "Token A"},
                    },
                    {
                        "chainId": "solana",
                        "pairAddress": "pool2",
                        "priceUsd": "1.3",
                        "liquidity": {"usd": 50},
                        "baseToken": {"address": "mintA", "symbol": "A"},
                    },
                ],
            )
        if "ohlcv" in path:
            return httpx.Response(
                200, json={"data": {"attributes": {"ohlcv_list": [[1, 1, 2, 1, 2, 10]]}}}
            )
        if "pools/pool2" in path:
            return httpx.Response(200, json={"data": {"attributes": {"name": "pool"}}})
        if "rugcheck" in path:
            return httpx.Response(
                200, json={"score": 1, "score_normalised": 80, "lpLockedPct": 75, "risks": []}
            )
        if "pump.fun" in path:
            return httpx.Response(200, json={"mint": "mintA", "symbol": "A", "complete": False})
        return httpx.Response(404)

    e = Enricher()
    e.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    e._gecko_last = 0
    try:
        info = await e.dexscreener_token("mintA")
        assert info["pool_address"] == "pool2"
        batch = await e.dexscreener_tokens_batch(["mintA"])
        assert batch["mintA"]["price_usd"] == 1.3
        assert await e.gecko_ohlc("pool2")
        assert (await e.gecko_pool_info("pool2"))["name"] == "pool"
        assert (await e.rugcheck("mintA"))["score_normalised"] == 80
        assert (await e.pumpfun_token("mintA"))["symbol"] == "A"
    finally:
        await e.close()

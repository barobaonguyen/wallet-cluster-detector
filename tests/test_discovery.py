import httpx
import pytest

from clusterdetect.clients.helius import HeliusClient
from clusterdetect.watchlist import discovery


def test_winner_and_quality_rules():
    assert discovery.is_winner({"h24": 100, "h6": 0, "h1": 0})
    assert discovery.is_winner({"h24": 0, "h6": 60, "h1": 0})
    assert discovery.is_winner({"h24": 0, "h6": 0, "h1": 200})
    assert discovery.passes_quality({"fdv": 100000, "liq": 5000})
    assert not discovery.passes_quality({"fdv": 10, "liq": 5000})


@pytest.mark.asyncio
async def test_collect_and_dry_run(monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr(discovery.asyncio, "sleep", no_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "trending_pools" in url:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "attributes": {
                                "address": "poolA",
                                "name": "A",
                                "price_change_percentage": {"h1": "0", "h6": "60", "h24": "0"},
                                "fdv_usd": "100000",
                                "reserve_in_usd": "5000",
                            },
                            "relationships": {"base_token": {"data": {"id": "solana_mintA"}}},
                        }
                    ]
                },
            )
        if "new_pools" in url or "token-boosts" in url:
            return httpx.Response(200, json=[] if "token-boosts" in url else {"data": []})
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        winners = await discovery.discover_winners(http, max_winners=5, dry_run=True)
    assert winners[0]["pool"] == "poolA"


@pytest.mark.asyncio
async def test_find_oldest_buyers_and_persist(monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr(discovery.asyncio, "sleep", no_sleep)
    h = HeliusClient(["KEY_AAAAAA"], rps=1000)

    async def sigs(address, *, limit=100, before=None, until=None):
        if before:
            return []
        return [{"signature": "s1"}, {"signature": "s2"}]

    async def parse(signatures, *, retries=3):
        return [
            {
                "signature": "s1",
                "timestamp": 1,
                "events": {"swap": {"tokenOutputs": [{"userAccount": "buyer1", "mint": "mintA"}]}},
            },
            {
                "signature": "s2",
                "timestamp": 2,
                "tokenTransfers": [{"toUserAccount": "buyer2", "mint": "mintA"}],
            },
        ]

    h.get_signatures_for_address = sigs
    h.parse_transactions = parse
    try:
        buyers = await discovery.find_oldest_buyers(h, "poolA")
        assert {b["wallet"] for b in buyers} == {"buyer1", "buyer2"}
    finally:
        await h.close()

import time

import httpx
import pytest

from clusterdetect.clients.helius import HeliusClient
from clusterdetect.clients.rate_limiter import QuotaTracker, RateLimiter
from clusterdetect.db import conn, get_meta, upsert_wallet


@pytest.mark.asyncio
async def test_rate_limiter_and_quota():
    limiter = RateLimiter(1000)
    await limiter.acquire()
    await limiter.acquire()
    quota = QuotaTracker(2)
    quota.add(1)
    assert not quota.is_exhausted()
    quota.add(1)
    assert quota.is_exhausted()


@pytest.mark.asyncio
async def test_key_rotation_max_usage_then_success():
    calls = {"n": 0}
    h = HeliusClient(["KEY_AAAAAA", "KEY_BBBBBB"], rps=1000)

    async def fake_request(method, url, params=None, json=None):
        calls["n"] += 1
        req = httpx.Request(method, url, params=params)
        if "KEY_AAAAAA" in url:
            return httpx.Response(429, text='{"message":"max usage reached"}', request=req)
        return httpx.Response(200, json={"result": [{"signature": "s"}]}, request=req)

    h.client.request = fake_request
    try:
        out = await h.get_signatures_for_address("wallet")
        assert out == [{"signature": "s"}]
        assert h.current_key() == "KEY_BBBBBB"
        assert "KEY_AAAAAA" in h._exhausted_keys
        assert h.credits_used == 1
    finally:
        await h.close()


@pytest.mark.asyncio
async def test_all_keys_exhausted_opens_24h_circuit():
    h = HeliusClient(["KEY_AAAAAA", "KEY_BBBBBB"], rps=1000)

    async def fake_request(method, url, params=None, json=None):
        return httpx.Response(
            429, text='{"message":"max usage reached"}', request=httpx.Request(method, url)
        )

    h.client.request = fake_request
    try:
        out = await h._request_with_retry("POST", h.rpc_url, op_name="test", retries=3)
        assert out is None
        assert h.is_circuit_open()
        assert 86000 < h._circuit_open_until - time.monotonic() <= 86400
    finally:
        await h.close()


@pytest.mark.asyncio
async def test_regular_429_opens_short_circuit(monkeypatch):
    h = HeliusClient(["KEY_AAAAAA"], rps=1000)
    h.CIRCUIT_429_THRESHOLD = 2
    h.retry_jitter_seconds = 0
    monkeypatch.setattr(h, "_backoff_seconds", lambda attempt, retry_after=None: 0)

    async def fake_request(method, url, params=None, json=None):
        return httpx.Response(
            429, text='{"message":"slow down"}', request=httpx.Request(method, url)
        )

    h.client.request = fake_request
    try:
        out = await h._request_with_retry("POST", h.rpc_url, op_name="test", retries=3)
        assert out is None
        assert h.is_circuit_open()
    finally:
        await h.close()


@pytest.mark.asyncio
async def test_parse_transactions_and_address_billing_and_404_disable():
    h = HeliusClient(["KEY_AAAAAA"], rps=1000)
    calls = {"n": 0}
    with conn() as c:
        upsert_wallet(c, "deadwallet", "test", score=1, added_at=1)

    async def fake_request(method, url, params=None, json=None):
        calls["n"] += 1
        req = httpx.Request(method, url, params=params)
        if "deadwallet" in url:
            return httpx.Response(404, json={"error": "missing"}, request=req)
        if method == "GET":
            return httpx.Response(200, json=[{"signature": "a"}, {"signature": "b"}], request=req)
        return httpx.Response(200, json=[{"signature": "p"}], request=req)

    h.client.request = fake_request
    try:
        parsed = await h.parse_transactions(["s1", "s2"])
        assert parsed == [{"signature": "p"}]
        txs = await h.get_address_transactions("livewallet")
        assert txs == [{"signature": "a"}, {"signature": "b"}]
        assert h.credits_used == 4
        for _ in range(3):
            assert await h.get_address_transactions("deadwallet") == []
        with conn() as c:
            assert (
                c.execute("SELECT enabled FROM wallets WHERE address='deadwallet'").fetchone()[
                    "enabled"
                ]
                == 0
            )
    finally:
        await h.close()


@pytest.mark.asyncio
async def test_exhausted_key_persistence():
    h1 = HeliusClient(["KEY_AAAAAA", "KEY_BBBBBB"], rps=1000)
    try:
        await h1.load_persisted_credits()
        h1.rotate_key()
    finally:
        await h1.close()
    with conn() as c:
        keys = [r["key"] for r in c.execute("SELECT key FROM meta").fetchall()]
        assert any(k.startswith("helius_exhausted_keys_") for k in keys)
        month_key = next(k for k in keys if k.startswith("helius_exhausted_keys_"))
        assert "AAAAAA" in get_meta(c, month_key)
    h2 = HeliusClient(["KEY_AAAAAA", "KEY_BBBBBB"], rps=1000)
    try:
        await h2.load_persisted_credits()
        assert h2.current_key() == "KEY_BBBBBB"
    finally:
        await h2.close()

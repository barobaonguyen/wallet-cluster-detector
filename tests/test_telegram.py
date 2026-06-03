import httpx
import pytest

from clusterdetect.alert.telegram import (
    TelegramAlerter,
    format_cluster_alert,
    format_paper_trade_close,
)
from clusterdetect.domain.cluster import Cluster
from clusterdetect.domain.reasoner import Evaluation


def test_format_cluster_alert_non_referral():
    cluster = Cluster("mint", 0, 60, ["w1", "w2"], 2, 10, {"w1": 1, "w2": 1}, 2)
    ev = Evaluation("OK", 55, ["evidence"], ["risk"], "OK line", 2)
    msg = format_cluster_alert(
        cluster,
        {"symbol": "TOK", "name": "Token", "price_usd": 0.1, "liquidity_usd": 1000},
        {"score_normalised": 80, "lp_locked_pct": 75},
        ev,
    )
    assert "CLUSTER BUY OK" in msg
    assert "/en/lp/mint" in msg
    assert "tinyastro.io/en/r" not in msg
    assert "Signal review" in msg


def test_format_paper_trade_close():
    msg = format_paper_trade_close(
        {
            "entry_price_usd": 1,
            "exit_price_usd": 2,
            "exit_reason": "time_stop",
            "pnl_pct": 100,
            "pnl_usd": 50,
        },
        {"symbol": "TOK"},
    )
    assert "Paper trade closed" in msg
    assert "+100.0%" in msg


@pytest.mark.asyncio
async def test_telegram_send_and_updates(monkeypatch):
    calls = []
    original_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "sendMessage" in str(request.url):
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(
            200, json={"result": [{"message": {"chat": {"id": 123, "type": "private"}}}]}
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *a, **k: original_client(transport=httpx.MockTransport(handler)),
    )
    alerter = TelegramAlerter("token", "chat")
    assert await alerter.send("hello")
    updates = await alerter.get_updates()
    assert updates[0]["message"]["chat"]["id"] == 123
    assert calls


@pytest.mark.asyncio
async def test_telegram_missing_creds():
    alerter = TelegramAlerter(None, None)
    assert not await alerter.send("hello")
    assert await alerter.get_updates() == []

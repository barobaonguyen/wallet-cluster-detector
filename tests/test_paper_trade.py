from clusterdetect.domain.cluster import Cluster
from clusterdetect.domain.paper_trade import PaperTrader


def cluster():
    return Cluster("mint", 0, 10, ["w1", "w2", "w3"], 3, 100, {"w1": 3, "w2": 2, "w3": 1}, 6)


def test_paper_trade_hard_stop():
    trader = PaperTrader()
    trade = trader.open(cluster(), 1.0, ts=0)
    out = trader.update(trade, 0.5, now=60)
    assert out.status == "closed"
    assert out.exit_reason == "hard_stop"
    assert out.pnl_pct == -50


def test_paper_trade_trail_time_dead():
    trader = PaperTrader(time_stop_hours=1)
    trade = trader.open(cluster(), 1.0, ts=0)
    trade = trader.update(trade, 3.5, now=600)
    assert trade.status == "open"
    trade = trader.update(trade, 1.5, now=700)
    assert trade.exit_reason == "trail_stop"

    dead = trader.open(cluster(), 1.0, ts=0)
    dead.peak_price_usd = 2.0
    dead = trader.update(dead, None, now=3601)
    assert dead.exit_reason == "time_stop_dead"
    assert dead.exit_price_usd == 2.0


def test_paper_trade_time_stop():
    trader = PaperTrader(time_stop_hours=1)
    trade = trader.open(cluster(), 1.0, ts=0, size_mult=0.5)
    out = trader.update(trade, 1.2, now=4000)
    assert out.exit_reason == "time_stop"
    assert round(out.pnl_usd, 2) == 5.0

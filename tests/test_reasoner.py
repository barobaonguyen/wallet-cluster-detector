import time

from clusterdetect.domain.cluster import Cluster
from clusterdetect.domain.reasoner import ClusterScorer, format_reason_block


def cluster() -> Cluster:
    return Cluster("mint", 0, 600, ["w1", "w2", "w3"], 3, 100, {"w1": 3, "w2": 2, "w3": 1}, 6)


def test_reasoner_strong_ok_and_block():
    ev = ClusterScorer().evaluate(
        cluster(),
        {
            "mcap": 900000,
            "liquidity_usd": 80000,
            "volume_h1": 76000,
            "txn_h1_buys": 50,
            "txn_h1_sells": 20,
            "created_at": int((time.time() - 3600) * 1000),
        },
        {"score_normalised": 90, "lp_locked_pct": 80, "risks": []},
        [
            {"address": "w1", "score": 3},
            {"address": "w2", "score": 2},
            {"address": "w3", "score": 1},
        ],
    )
    assert ev.decision == "STRONG"
    assert "top-tier" in " ".join(ev.pros)
    block = format_reason_block(ev)
    assert "Signal review" in block
    assert "paper trade first" in block


def test_reasoner_risky_missing_and_hard_warn():
    ev = ClusterScorer().evaluate(
        cluster(),
        {"liquidity_usd": 1, "mcap": 10000, "txn_h1_buys": 1, "txn_h1_sells": 5},
        {
            "score_normalised": 10,
            "lp_locked_pct": 1,
            "risks": [{"level": "danger", "name": "mint authority"}],
        },
        [{"address": "w1", "score": 1}],
    )
    assert ev.decision in {"RISKY", "SKIP"}
    assert ev.warns

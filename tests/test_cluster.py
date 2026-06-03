import json

from clusterdetect.db import conn
from clusterdetect.domain.cluster import (
    ClusterDetector,
    get_unnotified_clusters,
    mark_cluster_notified,
    save_clusters,
)


def test_cluster_requires_distinct_wallets_and_score():
    swaps = [
        {
            "signature": "a",
            "wallet": "w1",
            "timestamp": 100,
            "side": "buy",
            "token_mint": "m1",
            "usd_value": 1,
        },
        {
            "signature": "b",
            "wallet": "w2",
            "timestamp": 200,
            "side": "buy",
            "token_mint": "m1",
            "usd_value": 1,
        },
        {
            "signature": "c",
            "wallet": "w3",
            "timestamp": 300,
            "side": "buy",
            "token_mint": "m1",
            "usd_value": 1,
        },
    ]
    clusters = ClusterDetector(min_wallets=3, window_minutes=15, min_total_score=6).detect(
        swaps, {"w1": 3, "w2": 2, "w3": 1}
    )
    assert len(clusters) == 1
    assert clusters[0].total_wallet_score == 6
    assert clusters[0].wallet_count == 3


def test_cluster_window_edge_min_usd_and_merge():
    swaps = [
        {
            "signature": "a",
            "wallet": "w1",
            "timestamp": 0,
            "side": "buy",
            "token_mint": "m1",
            "usd_value": 10,
        },
        {
            "signature": "b",
            "wallet": "w2",
            "timestamp": 60,
            "side": "buy",
            "token_mint": "m1",
            "usd_value": 10,
        },
        {
            "signature": "c",
            "wallet": "w3",
            "timestamp": 120,
            "side": "buy",
            "token_mint": "m1",
            "usd_value": 10,
        },
        {
            "signature": "d",
            "wallet": "w4",
            "timestamp": 180,
            "side": "buy",
            "token_mint": "m1",
            "usd_value": 1,
        },
        {
            "signature": "e",
            "wallet": "w5",
            "timestamp": 5000,
            "side": "sell",
            "token_mint": "m1",
            "usd_value": 99,
        },
    ]
    clusters = ClusterDetector(
        min_wallets=2, window_minutes=3, min_total_score=2, min_usd=5
    ).detect(swaps, {"w1": 1, "w2": 1, "w3": 1, "w4": 9})
    assert len(clusters) == 1
    assert clusters[0].wallet_count == 3


def test_cluster_db_helpers():
    cluster = ClusterDetector(min_wallets=2, window_minutes=5, min_total_score=2).detect(
        [
            {"signature": "a", "wallet": "w1", "timestamp": 100, "side": "buy", "token_mint": "m1"},
            {"signature": "b", "wallet": "w2", "timestamp": 101, "side": "buy", "token_mint": "m1"},
        ],
        {"w1": 1, "w2": 1},
    )
    assert save_clusters(cluster) == 1
    assert save_clusters(cluster) == 0
    rows = get_unnotified_clusters()
    assert json.loads(rows[0]["wallets_json"]) == ["w1", "w2"]
    mark_cluster_notified(rows[0]["id"])
    with conn() as c:
        assert c.execute("SELECT notified FROM clusters").fetchone()["notified"] == 1

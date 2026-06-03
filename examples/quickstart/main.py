from clusterdetect import ClusterDetector, ClusterScorer, from_csv

wallets = from_csv("examples/quickstart/watchlist.example.csv")
scores = {w["address"]: w["score"] for w in wallets}

swaps = [
    {
        "signature": "demo-sig-1",
        "wallet": wallets[0]["address"],
        "timestamp": 1000,
        "side": "buy",
        "token_mint": "DemoMintCluster111",
        "usd_value": 40,
    },
    {
        "signature": "demo-sig-2",
        "wallet": wallets[1]["address"],
        "timestamp": 1300,
        "side": "buy",
        "token_mint": "DemoMintCluster111",
        "usd_value": 30,
    },
    {
        "signature": "demo-sig-3",
        "wallet": wallets[2]["address"],
        "timestamp": 1600,
        "side": "buy",
        "token_mint": "DemoMintCluster111",
        "usd_value": 20,
    },
]

detector = ClusterDetector(min_wallets=3, window_minutes=15, min_total_score=6)
scorer = ClusterScorer()

for cluster in detector.detect(swaps, scores):
    evaluation = scorer.evaluate(
        cluster,
        {"symbol": "DEMO", "mcap": 900000, "liquidity_usd": 80000, "volume_h1": 76000},
        None,
        [{"address": w, "score": scores[w]} for w in cluster.wallets],
    )
    print(evaluation.one_liner)

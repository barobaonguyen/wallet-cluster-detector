from pathlib import Path

from clusterdetect.config import load_config, validate_runtime_config
from clusterdetect.db import conn, get_meta, set_meta, upsert_wallet
from clusterdetect.watchlist.loader import from_csv, to_csv


def test_db_meta_and_wallet_upsert():
    with conn() as c:
        set_meta(c, "k", "v")
        upsert_wallet(c, "wallet", "test", score=2, added_at=1)
    with conn() as c:
        assert get_meta(c, "k") == "v"
        assert (
            c.execute("SELECT score FROM wallets WHERE address='wallet'").fetchone()["score"] == 2
        )


def test_load_config_env_and_yaml(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "\n".join(
            [
                "cluster_min_wallets: 4",
                "helius_api_keys: [yaml_key]",
                "alert:",
                "  channel: discord",
                "  webhook_url: https://discord.test/webhook",
                "filters:",
                "  pumpfun_graduation: true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HELIUS_API_KEY", "env_key")
    cfg = load_config(str(cfg_file), str(tmp_path / ".env"))
    assert cfg.helius_api_keys == ["env_key"]
    assert cfg.cluster_min_wallets == 4
    assert cfg.alert_channel == "discord"
    assert cfg.discord_webhook_url == "https://discord.test/webhook"
    assert cfg.pumpfun_graduation is True
    assert validate_runtime_config(cfg) == []


def test_watchlist_loader(tmp_path):
    path = tmp_path / "wallets.csv"
    wallets = [{"address": "DemoWa11etLowercaseL", "score": 3, "label": "demo", "chain": "solana"}]
    to_csv(wallets, str(path))
    assert from_csv(str(path)) == wallets
    assert Path(path).exists()

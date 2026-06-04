import pytest

from clusterdetect import cli
from clusterdetect.db import conn, upsert_wallet


def test_cli_help(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    assert "init-db" in out
    assert "discover" in out


def test_cli_init_status_pnl_schedule(capsys):
    assert cli.main(["init-db"]) == 0
    assert cli.main(["status"]) == 0
    assert cli.main(["pnl", "7", "--json"]) == 0
    assert cli.main(["schedule", "--os", "linux", "--at", "09:30"]) == 0
    out = capsys.readouterr().out
    assert "SQLite schema initialized" in out
    assert "wallet-cluster-detector status" in out
    assert "30 9 * *" in out


def test_cli_export_and_rank(tmp_path, capsys):
    with conn() as c:
        upsert_wallet(c, "WalletA", "test", score=4, added_at=1)
        upsert_wallet(c, "WalletB", "test", score=3, added_at=1)
        upsert_wallet(c, "WalletC", "test", score=3, added_at=1)
        c.execute(
            """INSERT INTO clusters(token_mint, first_buy_ts, last_buy_ts, wallet_count,
                                    wallets_json, total_usd, detected_at, notified, chain)
               VALUES(?,?,?,?,?,?,?,0,'solana')""",
            (
                "DemoMint",
                100,
                160,
                3,
                '["WalletA","WalletB","WalletC"]',
                1234.5,
                200,
            ),
        )

    json_out = tmp_path / "clusters.json"
    csv_out = tmp_path / "clusters.csv"
    assert cli.main(["export", "--format", "json", "--out", str(json_out)]) == 0
    assert cli.main(["export", "--format", "csv", "--out", str(csv_out)]) == 0
    assert cli.main(["rank"]) == 0

    assert '"tier": "STRONG"' in json_out.read_text(encoding="utf-8")
    assert "DemoMint" in csv_out.read_text(encoding="utf-8")
    out = capsys.readouterr().out
    assert "STRONG" in out
    assert "DemoMint" in out


@pytest.mark.asyncio
async def test_cli_discover_dry_mock(monkeypatch, capsys):
    async def fake_discover(http, *, helius=None, max_winners=25, max_keep=80, dry_run=False):
        assert dry_run is True
        assert helius is None
        return [
            {
                "name": "DEMO",
                "h1": 200,
                "h6": 0,
                "h24": 0,
                "fdv": 100000,
                "liq": 5000,
                "pool": "pool",
            }
        ]

    monkeypatch.setattr(cli, "discover_winners", fake_discover)
    assert await cli._async_main(["discover", "1", "--dry"]) == 0
    assert "DEMO" in capsys.readouterr().out

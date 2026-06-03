import pytest

from clusterdetect import cli


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

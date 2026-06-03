from clusterdetect.config import USDC, WSOL
from clusterdetect.domain.swap_parser import _amt, parse_swap

WALLET = "DemoWalletWithLowercaseL"
MEME = "DemoMint"


def test_amt_formats():
    assert _amt({"tokenAmount": "1.5"}) == 1.5
    assert _amt({"rawTokenAmount": {"tokenAmount": "1500000", "decimals": 6}}) == 1.5
    assert _amt({}) == 0.0


def test_parse_buy_native():
    tx = {
        "type": "SWAP",
        "signature": "sig1",
        "timestamp": 100,
        "source": "JUPITER",
        "events": {
            "swap": {
                "tokenInputs": [],
                "tokenOutputs": [
                    {
                        "userAccount": WALLET,
                        "mint": MEME,
                        "rawTokenAmount": {"tokenAmount": "2", "decimals": 0},
                    }
                ],
                "nativeInput": {"account": WALLET, "amount": "100000000"},
            }
        },
    }
    out = parse_swap(tx, WALLET, sol_price_usd=100)
    assert out["side"] == "buy"
    assert out["token_mint"] == MEME
    assert out["usd_value"] == 10


def test_parse_sell_native_and_stable_skip():
    sell = {
        "type": "SWAP",
        "signature": "sig2",
        "timestamp": 100,
        "events": {
            "swap": {
                "tokenInputs": [{"userAccount": WALLET, "mint": MEME, "tokenAmount": 2}],
                "tokenOutputs": [],
                "nativeOutput": {"account": WALLET, "amount": "200000000"},
            }
        },
    }
    assert parse_swap(sell, WALLET, sol_price_usd=50)["side"] == "sell"
    stable = {
        "type": "SWAP",
        "signature": "sig3",
        "timestamp": 100,
        "events": {
            "swap": {
                "tokenInputs": [{"userAccount": WALLET, "mint": USDC, "tokenAmount": 2}],
                "tokenOutputs": [{"userAccount": WALLET, "mint": WSOL, "tokenAmount": 1}],
            }
        },
    }
    assert parse_swap(stable, WALLET) is None


def test_parse_inner_swap_and_non_swap():
    tx = {
        "type": "SWAP",
        "signature": "sig4",
        "timestamp": 100,
        "events": {
            "swap": {
                "tokenInputs": [],
                "tokenOutputs": [],
                "nativeInput": {"account": WALLET, "amount": "50000000"},
                "innerSwaps": [
                    {"tokenOutputs": [{"userAccount": WALLET, "mint": MEME, "tokenAmount": 3}]}
                ],
            }
        },
    }
    assert parse_swap(tx, WALLET)["token_amount"] == 3
    assert parse_swap({"type": "TRANSFER"}, WALLET) is None
    assert parse_swap(None, WALLET) is None

"""Parse Helius enhanced SWAP transactions into normalized records."""

from __future__ import annotations

from typing import Any

from clusterdetect.config import STABLES, WSOL


def _amt(item: dict[str, Any]) -> float:
    """Extract amount from either decimal tokenAmount or rawTokenAmount."""

    if "tokenAmount" in item and item["tokenAmount"] is not None:
        try:
            return float(item["tokenAmount"])
        except (TypeError, ValueError):
            pass
    raw_token_amount = item.get("rawTokenAmount") or {}
    raw = raw_token_amount.get("tokenAmount")
    decimals = raw_token_amount.get("decimals", 0)
    if raw is None:
        return 0.0
    try:
        return float(raw) / (10**decimals)
    except Exception:
        return 0.0


def parse_swap(
    tx: dict[str, Any] | None, wallet: str, sol_price_usd: float | None = None
) -> dict[str, Any] | None:
    """Convert one Helius enhanced transaction into a normalized wallet-POV swap."""

    if not tx or tx.get("transactionError"):
        return None
    if tx.get("type") != "SWAP":
        return None

    swap = (tx.get("events") or {}).get("swap")
    if not swap:
        return None

    token_inputs = swap.get("tokenInputs") or []
    token_outputs = swap.get("tokenOutputs") or []
    native_input = swap.get("nativeInput") or {}
    native_output = swap.get("nativeOutput") or {}
    inner_swaps = swap.get("innerSwaps") or []

    wallet_sent_token = None
    wallet_sent_amt = 0.0
    wallet_received_token = None
    wallet_received_amt = 0.0
    sol_in = 0.0
    sol_out = 0.0

    for token_input in token_inputs:
        if token_input.get("userAccount") == wallet or token_input.get("fromUserAccount") == wallet:
            mint = token_input.get("mint")
            amt = _amt(token_input)
            if mint and amt > 0:
                wallet_sent_token = mint
                wallet_sent_amt = amt
                break

    for token_output in token_outputs:
        if token_output.get("userAccount") == wallet or token_output.get("toUserAccount") == wallet:
            mint = token_output.get("mint")
            amt = _amt(token_output)
            if mint and amt > 0:
                wallet_received_token = mint
                wallet_received_amt = amt
                break

    if native_input and (native_input.get("account") == wallet or wallet in str(native_input)):
        sol_in = float(native_input.get("amount", 0) or 0) / 1e9

    if native_output and (native_output.get("account") == wallet or wallet in str(native_output)):
        sol_out = float(native_output.get("amount", 0) or 0) / 1e9

    if not wallet_received_token and not wallet_sent_token and inner_swaps:
        for inner in inner_swaps:
            for token_input in inner.get("tokenInputs", []) or []:
                if (
                    token_input.get("userAccount") == wallet
                    or token_input.get("fromUserAccount") == wallet
                ):
                    mint = token_input.get("mint")
                    amt = _amt(token_input)
                    if mint:
                        wallet_sent_token = wallet_sent_token or mint
                        wallet_sent_amt = wallet_sent_amt or amt
            for token_output in inner.get("tokenOutputs", []) or []:
                if (
                    token_output.get("userAccount") == wallet
                    or token_output.get("toUserAccount") == wallet
                ):
                    mint = token_output.get("mint")
                    amt = _amt(token_output)
                    if mint:
                        wallet_received_token = wallet_received_token or mint
                        wallet_received_amt = wallet_received_amt or amt

    sent_is_stable = wallet_sent_token in STABLES if wallet_sent_token else False
    received_is_stable = wallet_received_token in STABLES if wallet_received_token else False

    side = None
    token_mint = None
    token_amount = 0.0
    sol_amount = 0.0

    if (sol_in > 0 or sent_is_stable) and wallet_received_token and not received_is_stable:
        side = "buy"
        token_mint = wallet_received_token
        token_amount = wallet_received_amt
        if sol_in > 0:
            sol_amount = sol_in
        elif wallet_sent_token == WSOL:
            sol_amount = wallet_sent_amt
    elif wallet_sent_token and not sent_is_stable and (sol_out > 0 or received_is_stable):
        side = "sell"
        token_mint = wallet_sent_token
        token_amount = wallet_sent_amt
        if sol_out > 0:
            sol_amount = sol_out
        elif wallet_received_token == WSOL:
            sol_amount = wallet_received_amt

    if not side or not token_mint:
        return None

    usd_value = sol_amount * sol_price_usd if sol_price_usd and sol_amount else None
    return {
        "signature": tx.get("signature"),
        "wallet": wallet,
        "timestamp": tx.get("timestamp"),
        "side": side,
        "token_mint": token_mint,
        "token_amount": token_amount,
        "sol_amount": sol_amount,
        "usd_value": usd_value,
        "source": tx.get("source", ""),
    }


async def get_sol_price_usd(http) -> float:
    """Fetch SOL/USD from CoinGecko free API, with a conservative fallback."""

    try:
        r = await http.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd",
            timeout=10,
        )
        return float(r.json()["solana"]["usd"])
    except Exception:
        return 150.0

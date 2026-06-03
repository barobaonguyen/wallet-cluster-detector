import argparse
import asyncio

import httpx

from clusterdetect.watchlist.discovery import discover_winners


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-winners", type=int, default=20)
    parser.add_argument("--dry", action="store_true", default=True)
    args = parser.parse_args()
    async with httpx.AsyncClient(timeout=20) as http:
        winners = await discover_winners(http, max_winners=args.max_winners, dry_run=True)
    for winner in winners:
        print(
            f"{winner.get('name') or '?':16s} h24={winner.get('h24', 0):+7.0f}% "
            f"liq={winner.get('liq', 0):.0f} pool={winner.get('pool')}"
        )


if __name__ == "__main__":
    asyncio.run(main())

import asyncio

import httpx

from clusterdetect.clients.helius import HeliusClient


async def main() -> None:
    client = HeliusClient(["DEMO_KEY_A", "DEMO_KEY_B"], rps=1000, daily_budget=2)
    calls = {"n": 0}

    async def fake_request(method, url, params=None, json=None):
        calls["n"] += 1
        req = httpx.Request(method, url, params=params)
        if calls["n"] == 1:
            return httpx.Response(
                429, text='{"error":{"message":"max usage reached"}}', request=req
            )
        return httpx.Response(200, json={"result": []}, request=req)

    client.client.request = fake_request
    try:
        await client.get_signatures_for_address("DemoPool111")
        print(f"rotated_to={client.current_key()}")
        client.credits_used = 2
        print(f"budget_exhausted={client.is_budget_exhausted()}")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())

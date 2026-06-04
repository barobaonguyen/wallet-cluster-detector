import httpx
import pytest

from clusterdetect.alert.discord import DiscordAlerter, html_alert_to_text


def test_html_alert_to_text_preserves_links():
    text = html_alert_to_text("<b>CLUSTER</b> <a href='https://example.com'>Open</a>")

    assert text == "CLUSTER Open: https://example.com"


@pytest.mark.asyncio
async def test_discord_alerter_mocked():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.read().decode())
        return httpx.Response(204)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        alerter = DiscordAlerter("https://discord.test/webhook", client=client)
        assert await alerter.send("<b>Signal</b> &amp; detail")
    finally:
        await client.aclose()

    assert "Signal & detail" in calls[0]

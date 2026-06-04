"""Discord webhook alert client."""

from __future__ import annotations

import html
import logging
import re

import httpx

log = logging.getLogger(__name__)

_LINK_RE = re.compile(r"<a\s+href=['\"]([^'\"]+)['\"]>(.*?)</a>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


def html_alert_to_text(text: str) -> str:
    """Convert the Telegram HTML alert body into Discord-safe plain text."""

    text = _LINK_RE.sub(lambda m: f"{m.group(2)}: {m.group(1)}", text)
    text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = _TAG_RE.sub("", text)
    return html.unescape(text)


class DiscordAlerter:
    def __init__(self, webhook_url: str | None, *, client: httpx.AsyncClient | None = None):
        self.webhook_url = (webhook_url or "").strip()
        self.client = client

    async def send(
        self,
        text: str,
        *,
        parse_mode: str = "HTML",
        disable_preview: bool = True,
    ) -> bool:
        del parse_mode, disable_preview
        if not self.webhook_url:
            log.warning("Discord webhook missing; skipping send")
            return False
        content = html_alert_to_text(text).strip()
        if len(content) > 1900:
            content = content[:1897].rstrip() + "..."
        payload = {"content": content}
        try:
            if self.client is not None:
                r = await self.client.post(self.webhook_url, json=payload)
            else:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    r = await client.post(self.webhook_url, json=payload)
            if r.status_code not in {200, 204}:
                log.error("Discord error: HTTP %s %s", r.status_code, r.text[:200])
                return False
            return True
        except Exception as exc:
            log.error("discord send failed: %s", exc)
            return False

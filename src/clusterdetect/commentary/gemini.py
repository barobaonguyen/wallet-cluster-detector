"""Optional Gemini commentary for cluster alerts.

No dependency is required: this module uses urllib and returns an empty string
when no plausible Gemini API key is configured.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

ROTATE_CODES = {429, 403, 400, 503}
DEFAULT_MODEL = "gemini-2.5-flash"
PRO_MODEL = "gemini-2.5-pro"

log = logging.getLogger(__name__)


def _load_keys() -> list[str]:
    keys: list[str] = []
    names = ["GEMINI_API_KEY", *[f"GEMINI_API_KEY_{i}" for i in range(2, 11)]]
    names.extend(f"GEMINI_API_KEY{i}" for i in range(2, 11))
    for name in names:
        key = os.getenv(name, "").strip()
        if key and key.startswith("AIza") and key not in keys:
            keys.append(key)
    return keys


def _prompt(payload: dict[str, Any], system_prompt: str | None) -> str:
    default_system = (
        "You are a neutral crypto market research assistant. Summarize the cluster signal in English. "
        "Do not provide buy, sell, leverage, entry, or sizing advice. Focus on evidence, missing data, "
        "and risk checks."
    )
    body = json.dumps(payload, indent=2, default=str)
    return f"{system_prompt or default_system}\n\nCluster payload:\n{body}\n\nReturn 2-4 concise sentences."


def generate_commentary(
    payload: dict[str, Any],
    *,
    model: str = DEFAULT_MODEL,
    system_prompt: str | None = None,
    temperature: float = 0.4,
) -> str:
    keys = _load_keys()
    if not keys:
        return ""
    rest_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    request_payload = {
        "contents": [{"parts": [{"text": _prompt(payload, system_prompt)}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": 500},
    }
    data = json.dumps(request_payload).encode("utf-8")
    for idx, key in enumerate(keys, start=1):
        req = urllib.request.Request(
            f"{rest_url}?key={key}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read())
            candidates = result.get("candidates", [])
            if not candidates:
                return ""
            parts = candidates[0].get("content", {}).get("parts", [])
            return "\n".join(part.get("text", "") for part in parts).strip()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")[:200]
            if exc.code in ROTATE_CODES and idx < len(keys):
                log.warning("Gemini key#%s returned HTTP %s; rotating", idx, exc.code)
                continue
            log.warning("Gemini HTTP %s: %s", exc.code, body)
            return ""
        except Exception as exc:
            if idx < len(keys):
                log.warning("Gemini key#%s failed; rotating: %s", idx, exc)
                continue
            log.warning("Gemini failed: %s", exc)
            return ""
    return ""

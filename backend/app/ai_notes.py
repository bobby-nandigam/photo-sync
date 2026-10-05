"""Optional one-line AI captions. OFF by default and fully isolated: this is
called AFTER a file is already SYNCED, in the worker's spare cycles, and any
failure is swallowed so it can never block or fail a sync.
"""
from __future__ import annotations

import base64

import httpx

from .config import settings
from .logging_conf import get_logger

log = get_logger(__name__)

_PROMPT = (
    "In one short line (max ~10 words), describe this photo plainly. "
    "No preamble, no punctuation at the end. Example: 'Beach sunset with people near the shoreline'."
)


def generate_note(data: bytes, mime_type: str) -> str | None:
    if not settings.ai_notes_enabled or not settings.ai_api_key:
        return None
    try:
        if settings.ai_provider == "gemini":
            return _gemini(data, mime_type)
        return _openai(data, mime_type)
    except Exception as e:  # noqa: BLE001 - never propagate
        log.warning("AI note generation failed (ignored): %s", e)
        return None


def _openai(data: bytes, mime_type: str) -> str | None:
    b64 = base64.b64encode(data).decode()
    resp = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {settings.ai_api_key}"},
        json={
            "model": settings.ai_model,
            "max_tokens": 40,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{b64}"},
                        },
                    ],
                }
            ],
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()[:500]


def _gemini(data: bytes, mime_type: str) -> str | None:
    b64 = base64.b64encode(data).decode()
    resp = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{settings.ai_model}:generateContent",
        params={"key": settings.ai_api_key},
        json={
            "contents": [
                {
                    "parts": [
                        {"text": _PROMPT},
                        {"inline_data": {"mime_type": mime_type, "data": b64}},
                    ]
                }
            ]
        },
        timeout=60,
    )
    resp.raise_for_status()
    parts = resp.json()["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts).strip()[:500]

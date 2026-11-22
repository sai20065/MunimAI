"""
Client for the local Whisper service (munimai/stt/stt_service.py). Free and offline: faster-whisper (MIT) with
Whisper weights (MIT), run from a separate virtual environment on the D drive. If the service is not running the
caller falls back to Bhashini, then to the browser's own recogniser, so voice never hard-fails.
"""

from __future__ import annotations

import os
from typing import Optional

import requests

BASE = os.environ.get("STT_URL", "http://127.0.0.1:8094")


def health() -> bool:
    try:
        return requests.get(f"{BASE}/health", timeout=2).ok
    except requests.RequestException:
        return False


def transcribe(audio: bytes, lang: str = "en", timeout: int = 60) -> Optional[str]:
    """Text for the audio, or None if the service is unavailable or heard nothing."""
    try:
        r = requests.post(f"{BASE}/transcribe", params={"lang": lang}, data=audio, timeout=timeout,
                          headers={"Content-Type": "application/octet-stream"})
        if not r.ok:
            return None
        text = (r.json().get("text") or "").strip()
        return text or None
    except (requests.RequestException, ValueError):
        return None

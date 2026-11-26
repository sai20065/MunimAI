"""
Client for the lab-box embedding service (BGE-M3, CPU). Every caller treats a missing service as
"no dense results", so retrieval degrades to BM25 instead of failing.
"""

from __future__ import annotations

import os
from typing import Optional

import requests

EMBED_URL = os.environ.get("EMBED_URL", "http://100.86.188.31:8095").rstrip("/")
DIM = 1024


def available(timeout: float = 2.0) -> bool:
    try:
        return requests.get(f"{EMBED_URL}/health", timeout=timeout).json().get("ok") is True
    except Exception:
        return False


def embed(texts: list[str], timeout: float = 20.0) -> Optional[list[list[float]]]:
    """Unit-length vectors, one per text, or None if the service is unreachable."""
    if not texts:
        return []
    out: list[list[float]] = []
    try:
        for i in range(0, len(texts), 32):
            r = requests.post(f"{EMBED_URL}/embed", json={"texts": texts[i:i + 32]}, timeout=timeout)
            r.raise_for_status()
            out += r.json()["vectors"]
    except Exception:
        return None
    return out


def to_pg(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"

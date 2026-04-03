from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .config import CACHE_DIR


def cache_key(payload: dict) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def read_cache(key: str):
    target = CACHE_DIR / f"{key}.json"
    if not target.exists():
        return None

    return json.loads(target.read_text(encoding="utf-8"))


def write_cache(key: str, payload: dict):
    target = CACHE_DIR / f"{key}.json"
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def cache_stats() -> dict:
    files = list(Path(CACHE_DIR).glob("*.json"))
    return {"entries": len(files), "path": str(CACHE_DIR)}

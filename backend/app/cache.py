from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .config import CACHE_DIR

DEFAULT_CACHE_MAX_ENTRIES = 32
DEFAULT_CACHE_MAX_BYTES = 50 * 1024 * 1024


def _read_int_env(name: str, default: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default

    try:
        return max(0, int(raw_value))
    except ValueError:
        return default


CACHE_MAX_ENTRIES = _read_int_env(
    "SHEETGEN_CACHE_MAX_ENTRIES",
    DEFAULT_CACHE_MAX_ENTRIES,
)
CACHE_MAX_BYTES = _read_int_env("SHEETGEN_CACHE_MAX_BYTES", DEFAULT_CACHE_MAX_BYTES)


def cache_key(payload: dict) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _cache_inventory() -> list[tuple[Path, float, int]]:
    files: list[tuple[Path, float, int]] = []
    for path in Path(CACHE_DIR).glob("*.json"):
        try:
            stats = path.stat()
        except OSError:
            continue
        files.append((path, stats.st_mtime, stats.st_size))
    return files


def _prune_cache(extra_entries: int = 0, extra_bytes: int = 0) -> None:
    files = _cache_inventory()
    entry_count = len(files) + extra_entries
    total_bytes = sum(size for _, _, size in files) + extra_bytes

    if CACHE_MAX_ENTRIES == 0 or CACHE_MAX_BYTES == 0:
        should_delete = lambda: entry_count > 0
    else:
        should_delete = lambda: (
            entry_count > CACHE_MAX_ENTRIES or total_bytes > CACHE_MAX_BYTES
        )

    for path, _, size in sorted(files, key=lambda item: item[1]):
        if not should_delete():
            break
        try:
            path.unlink()
        except OSError:
            continue
        entry_count -= 1
        total_bytes -= size


def read_cache(key: str):
    target = CACHE_DIR / f"{key}.json"
    if not target.exists():
        return None

    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        target.touch(exist_ok=True)
        return payload
    except (OSError, json.JSONDecodeError):
        try:
            target.unlink()
        except OSError:
            pass
        return None


def write_cache(key: str, payload: dict):
    if CACHE_MAX_ENTRIES == 0 or CACHE_MAX_BYTES == 0:
        _prune_cache()
        return

    target = CACHE_DIR / f"{key}.json"
    serialized = json.dumps(payload, ensure_ascii=False)
    payload_bytes = len(serialized.encode("utf-8"))

    if payload_bytes > CACHE_MAX_BYTES:
        _prune_cache()
        return

    existing_bytes = 0
    existing_entry = target.exists()
    if existing_entry:
        try:
            existing_bytes = target.stat().st_size
        except OSError:
            existing_bytes = 0

    _prune_cache(
        extra_entries=0 if existing_entry else 1,
        extra_bytes=max(0, payload_bytes - existing_bytes),
    )

    try:
        target.write_text(serialized, encoding="utf-8")
    except OSError:
        # Cache persistence should never make generation fail.
        return

    _prune_cache()


def cache_stats() -> dict:
    files = _cache_inventory()
    return {
        "entries": len(files),
        "bytes": sum(size for _, _, size in files),
        "maxEntries": CACHE_MAX_ENTRIES,
        "maxBytes": CACHE_MAX_BYTES,
        "path": str(CACHE_DIR),
    }

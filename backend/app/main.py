from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .cache import cache_key, cache_stats, read_cache, write_cache
from .config import SHARED_DIR
from .generator import build_exercise
from .models import ExerciseRequest, ExerciseResponse


app = FastAPI(title="SheetGenerator API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _fingerprint_parts(path: Path, root: Path) -> list[str]:
    if not path.exists():
        return []

    if path.is_file():
        candidates = [path]
    else:
        candidates = sorted(
            candidate
            for candidate in path.rglob("*")
            if candidate.is_file() and candidate.suffix in {".py", ".json"}
        )

    parts: list[str] = []
    for candidate in candidates:
        try:
            stamp = int(candidate.stat().st_mtime)
        except OSError:
            continue
        try:
            label = candidate.relative_to(root).as_posix()
        except ValueError:
            label = candidate.name
        parts.append(f"{label}:{stamp}")
    return parts


def _build_fingerprint():
    base = Path(__file__).resolve().parent
    root = base.parents[1]
    tracked = [
        base / "main.py",
        base / "audio.py",
        base / "cache.py",
        base / "config.py",
        base / "models.py",
        base / "generator",
        SHARED_DIR,
    ]
    parts: list[str] = []
    for path in tracked:
        parts.extend(_fingerprint_parts(path, root))
    return "|".join(parts)


@app.get("/v1/health")
async def health():
    return {"ok": True, "cache": cache_stats(), "build": _build_fingerprint()}


@app.post("/v1/exercises/generate", response_model=ExerciseResponse)
async def generate_exercise(payload: ExerciseRequest):
    normalized = payload.model_dump()
    key = cache_key(normalized)
    cached = read_cache(key)
    if cached:
        return cached

    result = build_exercise(normalized)
    write_cache(key, result)
    return result

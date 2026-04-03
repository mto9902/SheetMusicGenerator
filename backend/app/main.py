from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .cache import cache_key, cache_stats, read_cache, write_cache
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


def _build_fingerprint():
    base = Path(__file__).resolve().parent
    tracked = [
        base / "main.py",
        base / "generator.py",
        base / "audio.py",
        base.parent / "shared",
    ]
    parts: list[str] = []
    for path in tracked:
        if not path.exists():
            continue
        try:
            stamp = int(path.stat().st_mtime)
        except OSError:
            continue
        parts.append(f"{path.name}:{stamp}")
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

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .cache import cache_key, cache_stats, read_cache, write_cache
from .config import SHARED_DIR
from .generator import build_exercise
from .models import ExerciseRequest, ExerciseResponse


app = FastAPI(title="SheetGenerator API", version="0.1.0")
logger = logging.getLogger(__name__)

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


def _with_seed_suffix(payload: dict[str, object], attempt: int) -> dict[str, object]:
    candidate = dict(payload)
    candidate["seed"] = f"{payload['seed']}-retry{attempt}"
    return candidate


def _build_exercise_with_retries(payload: dict[str, object], attempts: int = 4):
    last_error: Exception | None = None

    for attempt in range(attempts + 1):
        candidate = payload if attempt == 0 else _with_seed_suffix(payload, attempt)
        try:
            return build_exercise(candidate)
        except ValueError as exc:
            last_error = exc
            logger.warning(
                "Generation failed for seed '%s' on attempt %s/%s: %s",
                candidate["seed"],
                attempt + 1,
                attempts + 1,
                exc,
            )
            continue

    raise ValueError(
        f"Could not generate a valid exercise after {attempts + 1} attempts"
    ) from last_error


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled API error for %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error"},
    )


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

    result = _build_exercise_with_retries(normalized)
    write_cache(key, result)
    return result

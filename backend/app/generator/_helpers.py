"""Small utility functions used across the generator package."""
from __future__ import annotations

import random
from typing import Any

from ..config import GRADE_PRESETS, MEASURE_TOTALS, PULSE_BY_SIGNATURE


def _preset_for_grade(grade: int) -> dict[str, Any]:
    return next(item for item in GRADE_PRESETS if item["grade"] == grade)


def _measure_total(signature: str) -> float:
    return float(MEASURE_TOTALS[signature])


def _pulse_value(signature: str) -> float:
    return float(PULSE_BY_SIGNATURE[signature])


def _fit_measure(remaining: float, allowed: list[float], rng: random.Random) -> list[float] | None:
    if abs(remaining) < 0.001:
        return []
    candidates = [value for value in allowed if value <= remaining + 0.001]
    rng.shuffle(candidates)
    for candidate in candidates:
        tail = _fit_measure(round(remaining - candidate, 3), allowed, rng)
        if tail is not None:
            return [candidate, *tail]
    return None


def _fit_measure_variants(
    total: float,
    allowed_durations: list[float],
    min_parts: int,
    max_parts: int,
) -> list[tuple[float, ...]]:
    ordered = sorted({round(float(value), 3) for value in allowed_durations if float(value) > 0}, reverse=True)
    results: set[tuple[float, ...]] = set()

    def _walk(remaining: float, parts: tuple[float, ...]) -> None:
        remaining = round(remaining, 3)
        if abs(remaining) < 0.02:
            if min_parts <= len(parts) <= max_parts:
                results.add(parts)
            return
        if len(parts) >= max_parts:
            return

        for duration_value in ordered:
            if duration_value <= remaining + 0.001:
                _walk(round(remaining - duration_value, 3), parts + (duration_value,))

    _walk(round(float(total), 3), tuple())
    return sorted(results, key=lambda item: (len(item), item))


def _signature_similarity(
    left: tuple[tuple[str, float], ...],
    right: tuple[tuple[str, float], ...],
) -> float:
    if not left or not right:
        return 0.0

    matches = 0.0
    compare_len = min(len(left), len(right))
    for idx in range(compare_len):
        if left[idx] == right[idx]:
            matches += 1.0
        elif left[idx][0] == right[idx][0] and abs(left[idx][1] - right[idx][1]) < 0.01:
            matches += 0.75
    return matches / max(len(left), len(right))


def _mean(values: list[float], default: float = 0.0) -> float:
    return sum(values) / len(values) if values else default

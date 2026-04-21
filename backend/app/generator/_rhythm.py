"""Rhythmic cells, phrase contour types, and texture selection helpers.

Extracted from _monolith.py (lines 1103-1297).  All logic is unchanged.
"""

from __future__ import annotations

import random
from typing import Any

# ---------------------------------------------------------------------------
# Rhythmic cells — pre-composed rhythm patterns that sum to 1 or 2 beats
# ---------------------------------------------------------------------------

# Each cell is a list of (quarterLength) values summing to `pulse` or `pulse*2`.
# Cells are defined relative to pulse=1.0 (quarter note); scaled at use time.

_RHYTHM_CELLS_1BEAT: list[list[float]] = [
    [1.0],                  # quarter
    [0.5, 0.5],            # two eighths
    [0.75, 0.25],          # dotted eighth + sixteenth
]

_RHYTHM_CELLS_2BEAT: list[list[float]] = [
    [2.0],                  # half note
    [1.5, 0.5],            # dotted quarter + eighth  ** SRF signature **
    [1.5, 0.5],            # (doubled weight — this is the most musical cell)
    [0.5, 1.5],            # eighth + dotted quarter
    [1.0, 1.0],            # two quarters
    [1.0, 0.5, 0.5],      # quarter + two eighths
    [0.5, 0.5, 1.0],      # two eighths + quarter
    [0.5, 1.0, 0.5],      # eighth, quarter, eighth
    [0.75, 0.25, 1.0],    # dotted eighth + sixteenth + quarter
    [1.0, 0.75, 0.25],    # quarter + dotted eighth + sixteenth
]

_RHYTHM_CELLS_SIMPLE: list[list[float]] = [
    [1.0],
    [2.0],
    [1.0, 1.0],
]

# Grade 3: quarter-dominated with occasional eighths and dotted quarters.
# Produces a calmer, more singable rhythm than jumping straight to 1-beat cells.
_RHYTHM_CELLS_GRADE3: list[list[float]] = [
    [1.0],                  # quarter  (high weight via repetition)
    [1.0],                  # quarter  (doubled)
    [2.0],                  # half note
    [2.0],                  # half note (doubled)
    [1.5, 0.5],            # dotted quarter + eighth  ** SRF signature **
    [1.5, 0.5],            # (doubled weight)
    [0.5, 1.5],            # eighth + dotted quarter
    [1.0, 1.0],            # two quarters
    [1.0, 1.0],            # two quarters (doubled)
    [0.5, 0.5, 1.0],      # two eighths + quarter (eighth pair, not a stream)
]


def _pick_rhythm_cells(
    grade: int,
    allowed_durations: list[float],
    rng: random.Random,
) -> list[list[float]]:
    """Pick 3-5 favorite rhythm cells for a phrase, filtered by allowed durations.

    Grades 3-4 avoid mixing sixteenths with long values in the same piece.
    This keeps the rhythmic vocabulary focused — more SRF-like consistency.
    """
    allowed_set = set(allowed_durations)
    if grade <= 2:
        candidates = _RHYTHM_CELLS_SIMPLE
    elif grade == 3:
        candidates = _RHYTHM_CELLS_GRADE3
    else:
        candidates = _RHYTHM_CELLS_1BEAT + _RHYTHM_CELLS_2BEAT

    # Filter to cells whose durations are all allowed
    valid = [c for c in candidates if all(d in allowed_set for d in c)]
    if not valid:
        valid = [[1.0]]  # fallback

    # For grades 3-4: avoid mixing sixteenths (0.25) with cells that contain
    # half notes (2.0). This prevents visual overload from mixing very short
    # and very long values in the same piece.
    if 3 <= grade <= 4 and len(valid) > 3:
        has_sixteenth = [c for c in valid if any(d <= 0.25 for d in c)]
        no_sixteenth = [c for c in valid if not any(d <= 0.25 for d in c)]
        # Prefer no-sixteenth cells 75% of the time
        if no_sixteenth and has_sixteenth:
            valid = no_sixteenth if rng.random() < 0.75 else valid

    # Pick 3-4 distinct favorites (but only 2-3 for grades 1-3 to keep simpler)
    max_cells = 4 if grade >= 4 else 3
    k = min(rng.randint(2, max_cells), len(valid))
    favorites = rng.sample(valid, k)
    # Double up 1-2 favorites for rhythmic motif repetition (creates coherence)
    if favorites:
        favorites.append(rng.choice(favorites))
        if grade >= 3:
            favorites.append(rng.choice(favorites))
    return favorites


def _fill_measure_from_cells(
    total: float,
    cells: list[list[float]],
    allowed_durations: list[float],
    rng: random.Random,
) -> list[float]:
    """Fill a measure using rhythm cells, returning a list of durations."""
    durations: list[float] = []
    cursor = 0.0
    allowed_set = set(allowed_durations)
    attempts = 0
    max_attempts = 50

    while cursor < total - 0.001 and attempts < max_attempts:
        remaining = round(total - cursor, 3)
        attempts += 1

        # Try to fit a cell
        fitting = [c for c in cells if round(sum(c), 3) <= remaining + 0.001
                   and all(d in allowed_set for d in c)]
        if fitting:
            cell = rng.choice(fitting)
            for d in cell:
                durations.append(d)
                cursor = round(cursor + d, 3)
        else:
            # Fill remaining with a single allowed duration
            valid = [d for d in allowed_durations if d <= remaining + 0.01]
            if valid:
                d = rng.choice(valid)
                durations.append(d)
                cursor = round(cursor + d, 3)
            else:
                break

    return durations


# ---------------------------------------------------------------------------
# Phrase contour — gives melodic direction to each phrase
# ---------------------------------------------------------------------------

_CONTOUR_TYPES = ["ascending", "descending", "arch", "valley", "flat"]


def _pick_contour(rng: random.Random) -> str:
    """Pick a melodic contour type for a phrase."""
    return rng.choices(
        _CONTOUR_TYPES,
        weights=[0.25, 0.25, 0.3, 0.1, 0.1],
        k=1,
    )[0]


def _related_contour(contour: str, rng: random.Random) -> str:
    related = {
        "ascending": ["ascending", "arch"],
        "descending": ["descending", "valley"],
        "arch": ["arch", "ascending"],
        "valley": ["valley", "descending"],
        "flat": ["flat", "arch"],
    }
    return rng.choice(related.get(contour, [contour]))


def _contour_direction_bias(
    contour: str,
    position_in_phrase: float,  # 0.0 to 1.0
) -> int:
    """Return preferred direction (-1, 0, +1) based on contour and position."""
    if contour == "ascending":
        return 1
    elif contour == "descending":
        return -1
    elif contour == "arch":
        return 1 if position_in_phrase < 0.5 else -1
    elif contour == "valley":
        return -1 if position_in_phrase < 0.5 else 1
    else:  # "flat"
        return 0


# ---------------------------------------------------------------------------
# Texture selection (kept for compatibility but no longer picks per-measure)
# ---------------------------------------------------------------------------

def _pick_texture(
    hand: str,
    grade: int,
    measure_index: int,
    preset: dict[str, Any],
    rng: random.Random,
) -> str:
    """Fallback texture picker when a phrase plan does not provide one."""
    weights = dict(preset.get("piano", {}).get("textureWeights", {"melody": 1.0, "chordal": 0.0, "running": 0.0}))
    if grade < 4:
        return "melody"

    choices = ["melody", "chordal", "running"]
    raw = [max(0.001, float(weights.get(choice, 0.0))) for choice in choices]
    return rng.choices(choices, weights=raw, k=1)[0]


# ---------------------------------------------------------------------------
# Cadence rhythm library — time-signature-specific cadence patterns
# ---------------------------------------------------------------------------

_CADENCE_LIBRARY = {
    "2/4": {
        "tonic": {"connection": "cadential_turn", "ornament": "arrival", "durations": [1.0, 0.5, 0.5]},
        "dominant": {"connection": "lead_in", "ornament": "arrival", "durations": [0.5, 0.5, 1.0]},
        "stable": {"connection": "liquidation", "ornament": "arrival", "durations": [1.0, 1.0]},
    },
    "3/4": {
        "tonic": {"connection": "cadential_turn", "ornament": "arrival", "durations": [1.0, 0.5, 0.5, 1.0]},
        "dominant": {"connection": "lead_in", "ornament": "arrival", "durations": [0.5, 0.5, 1.0, 1.0]},
        "stable": {"connection": "liquidation", "ornament": "arrival", "durations": [1.0, 1.0, 1.0]},
    },
    "4/4": {
        "tonic": {"connection": "cadential_turn", "ornament": "arrival", "durations": [1.0, 0.5, 0.5, 2.0]},
        "dominant": {"connection": "lead_in", "ornament": "arrival", "durations": [0.5, 0.5, 1.0, 2.0]},
        "stable": {"connection": "liquidation", "ornament": "arrival", "durations": [1.0, 1.0, 2.0]},
    },
    "6/8": {
        "tonic": {"connection": "cadential_turn", "ornament": "arrival", "durations": [0.75, 0.75, 1.5]},
        "dominant": {"connection": "lead_in", "ornament": "arrival", "durations": [0.75, 0.75, 1.5]},
        "stable": {"connection": "liquidation", "ornament": "arrival", "durations": [1.5, 1.5]},
    },
}

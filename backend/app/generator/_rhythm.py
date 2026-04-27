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
    """Pick 2-3 favourite rhythm cells for the piece.

    Production-quality output: each piece picks a TIGHT rhythmic palette
    (2-3 cells) and reuses it consistently.  Mixing sixteenths with long
    values in the same piece is the loudest "engine-generated" tell.

    - Grade ≤ 2: 2 cells max from the simple bank.
    - Grade 3:   2-3 cells, no sixteenths (sixteenths are explicitly opt-in
                 only via grade 4+).
    - Grade 4:   3 cells.  Sixteenths allowed but kept rare (one cell at most).
    - Grade 5:   3-4 cells, full vocabulary.
    """
    allowed_set = set(allowed_durations)
    if grade <= 2:
        candidates = _RHYTHM_CELLS_SIMPLE
    elif grade == 3:
        # Grade 3 should NEVER pick a cell with a sixteenth — purely quarter-
        # and eighth-based vocabulary keeps the visual flow clean.
        candidates = [c for c in _RHYTHM_CELLS_GRADE3 if min(c) >= 0.5]
    else:
        candidates = _RHYTHM_CELLS_1BEAT + _RHYTHM_CELLS_2BEAT

    valid = [c for c in candidates if all(d in allowed_set for d in c)]
    if not valid:
        valid = [[1.0]]  # fallback

    # Grade 4: keep sixteenths rare. Pick from the no-sixteenth pool 80% of
    # the time so most pieces stay clean; the remaining 20% can include one
    # sixteenth-bearing cell as colour.
    if grade == 4 and len(valid) > 3:
        has_sixteenth = [c for c in valid if any(d <= 0.25 for d in c)]
        no_sixteenth = [c for c in valid if not any(d <= 0.25 for d in c)]
        if no_sixteenth and has_sixteenth:
            valid = no_sixteenth if rng.random() < 0.80 else valid

    # Pick a TIGHT palette: 2 cells for low grades, 3 for high.
    if grade <= 2:
        max_cells = 2
    elif grade <= 4:
        max_cells = 3
    else:
        max_cells = 4
    k = min(max_cells, len(valid))
    favourites = rng.sample(valid, k) if len(valid) >= k else list(valid)
    # Repeat the *first* (anchor) cell so it dominates the piece — this
    # creates the rhythmic motif identity.
    if favourites:
        favourites.append(favourites[0])
        if grade >= 3:
            favourites.append(favourites[0])
    return favourites


def _bar_rhythm_coherence_pass(
    bar_durations: list[float],
    pulse: float,
) -> list[float]:
    """Force a bar to use ≤ 2 distinct durations (excluding the cadence tail).

    A bar mixing 4+ different durations reads as visual chaos.  This pass
    finds the dominant 1-2 durations in the bar and remaps any outliers to
    the nearest dominant one (within tolerance) — preserves total length.
    """
    if len(bar_durations) <= 2:
        return list(bar_durations)
    from collections import Counter
    counts = Counter(round(float(d), 3) for d in bar_durations)
    dominant = [d for d, _ in counts.most_common(2)]
    if len(dominant) <= 1 or len(set(bar_durations)) <= 2:
        return list(bar_durations)

    output: list[float] = []
    for d in bar_durations:
        if round(d, 3) in dominant:
            output.append(d)
        else:
            # Map outlier to the nearest dominant duration.
            best = min(dominant, key=lambda dd: abs(dd - d))
            # Only remap if the swap is small (within a pulse).
            if abs(best - d) <= pulse:
                output.append(best)
            else:
                output.append(d)  # leave alone if too far
    # Re-pad/trim if total drifted (should be rare since outliers were small).
    return output


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

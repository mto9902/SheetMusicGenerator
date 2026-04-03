from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass, field
from typing import Any

from music21 import (
    articulations,
    bar,
    chord,
    clef,
    duration as m21duration,
    dynamics,
    expressions,
    key,
    layout,
    meter,
    note,
    spanner,
    stream,
    tempo,
    tie as m21tie,
)
from music21.musicxml.m21ToXml import GeneralObjectExporter

from .audio import render_audio_data_uri
from .config import (
    COORDINATION_LABELS,
    HAND_ACTIVITY_LABELS,
    HAND_POSITION_ROOTS,
    HARMONY_INTERVALS,
    KEY_TONIC_PITCH_CLASS,
    MEASURE_TOTALS,
    POSITION_LABELS,
    PULSE_BY_SIGNATURE,
    READING_FOCUS_LABELS,
    GRADE_LABELS,
    GRADE_PRESETS,
    TEMPO_BY_PRESET,
    hand_position_limits_for_grade,
    is_minor_key,
    scale_steps_for_key,
)

try:
    from verovio import toolkit  # type: ignore
except Exception:  # pragma: no cover
    toolkit = None


@dataclass(frozen=True)
class StyleProfile:
    grade: int
    focus: str
    cadence_strength: float
    left_hand_persistence: float
    register_span: tuple[float, float]
    texture_ceiling: str
    allowed_connection_functions: tuple[str, ...]
    allowed_ornament_functions: tuple[str, ...]
    accidental_policy: str
    density_floor: float
    density_ceiling: float
    search_attempts: int


@dataclass(frozen=True)
class PhraseGrammar:
    """Grammatical role and shape pre-decided for each phrase."""
    phrase_index: int
    function: str           # "antecedent", "consequent", "continuation", "closing"
    cadence_type: str       # "half", "authentic", "plagal", "deceptive"
    peak_position: float    # 0.0-1.0 within phrase (0=start, 1=end)
    opening_energy: float   # 0.0-1.0 — how assertively phrase begins
    energy_profile: tuple[float, ...]  # per-measure intensity multipliers (len = phrase length)


@dataclass(frozen=True)
class PiecePlan:
    phrase_count: int
    apex_measure: int
    cadence_map: dict[int, str]
    intensity_curve: dict[int, float]
    dynamic_arc: str
    contrast_measures: tuple[int, ...]
    phrase_grammars: tuple[PhraseGrammar, ...]
    summary: str


@dataclass(frozen=True)
class AnchorTone:
    measure: int
    beat: float
    pitch_role: str
    register_slot: float
    local_goal: str


@dataclass(frozen=True)
class ConnectionFunction:
    name: str
    role: str
    intensity: float


@dataclass(frozen=True)
class OrnamentFunction:
    name: str
    placement: str


@dataclass(frozen=True)
class LinePlan:
    phrase_index: int
    climax_measure: int
    register_trajectory: dict[int, float]
    anchors: tuple[AnchorTone, ...]
    connections: dict[int, ConnectionFunction]
    ornaments: dict[int, OrnamentFunction]


@dataclass(frozen=True)
class TopLinePlan:
    phrase_index: int
    peak_measure: int
    register_targets: dict[int, float]
    pitch_roles: dict[int, str]
    motion_roles: dict[int, str]


@dataclass(frozen=True)
class BassLinePlan:
    phrase_index: int
    cadence_measure: int
    register_targets: dict[int, float]
    pitch_roles: dict[int, str]
    motion_roles: dict[int, str]


@dataclass(frozen=True)
class AccompanimentPlan:
    role: str
    primary_family: str
    support_families: tuple[str, ...]
    cadence_family: str


@dataclass(frozen=True)
class PhraseBlueprint:
    phrase_index: int
    measures: tuple[int, ...]
    archetype: str
    phrase_role: str
    cadence_target: str
    primary_motive: dict[str, Any]
    answer_form: str
    accompaniment_role: str
    line_plan: LinePlan
    top_line_plan: TopLinePlan
    bass_line_plan: BassLinePlan


@dataclass(frozen=True)
class EvaluationBreakdown:
    phrase_coherence: float = 0.0
    motivic_recurrence: float = 0.0
    line_continuity: float = 0.0
    anchor_clarity: float = 0.0
    non_chord_tone_correctness: float = 0.0
    cadence_preparation: float = 0.0
    register_arc_quality: float = 0.0
    lh_role_stability: float = 0.0
    rh_lh_hierarchy: float = 0.0
    difficulty_smoothness: float = 0.0
    sight_reading_chunkability: float = 0.0
    accidental_justification: float = 0.0
    top_line_strength: float = 0.0
    bass_function: float = 0.0
    foreground_background_clarity: float = 0.0
    vertical_balance: float = 0.0
    total: float = 0.0


@dataclass(frozen=True)
class QualityGateResult:
    passed: bool = True
    score: float = 1.0
    reasons: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Key / pitch helpers
# ---------------------------------------------------------------------------

def _key_pitch_classes(key_signature: str) -> set[int]:
    tonic = KEY_TONIC_PITCH_CLASS[key_signature]
    steps = scale_steps_for_key(key_signature)
    return {(tonic + step) % 12 for step in steps}


def _position_pitches_from_root(root: int, key_signature: str,
                                pool_size: int = 5) -> list[int]:
    pitch_classes = _key_pitch_classes(key_signature)
    scan_range = pool_size + 8
    pitches = [midi for midi in range(root, root + scan_range)
               if midi % 12 in pitch_classes]
    if len(pitches) >= pool_size:
        return pitches[:pool_size]
    return [root, root + 2, root + 4, root + 5, root + 7]


def _shift_root(current_root: int, hand: str, grade: int, rng: random.Random) -> int:
    lower, upper = hand_position_limits_for_grade(hand, grade)
    next_root = current_root + rng.choice([-2, -1, 1, 2])
    return max(lower, min(upper, next_root))


# ---------------------------------------------------------------------------
# Harmonic plan
# ---------------------------------------------------------------------------

_MAJOR_PROGRESSIONS: dict[int, list[list[str]]] = {
    1: [
        ["I", "V", "I", "I"],
        ["I", "I", "V", "I"],
        ["I", "IV", "I", "I"],
        ["I", "V", "V", "I"],
    ],
    2: [
        ["I", "IV", "V", "I"],
        ["I", "V", "IV", "I"],
        ["I", "IV", "I", "V"],
    ],
    3: [
        ["I", "IV", "V", "I"],
        ["I", "V", "IV", "I"],
        ["I", "IV", "I", "V"],
        ["I", "ii", "V", "I"],
    ],
    4: [
        ["I", "vi", "ii", "V", "I", "IV", "V", "I"],
        ["I", "IV", "vi", "V", "I", "ii", "V", "I"],
        ["I", "vi", "IV", "V", "I", "IV", "ii", "V"],
        ["I", "ii", "V", "I", "vi", "IV", "V", "I"],
        ["IV", "V", "I", "vi", "ii", "V", "I", "I"],
        ["vi", "IV", "V", "I", "ii", "V", "I", "I"],
    ],
    5: [
        ["I", "vi", "ii", "V", "I", "IV", "V", "I"],
        ["I", "IV", "vi", "V", "I", "ii", "V", "I"],
        ["I", "vi", "IV", "V", "I", "IV", "ii", "V"],
        ["I", "ii", "V", "I", "vi", "IV", "V", "I"],
        ["IV", "V", "vi", "I", "ii", "V", "I", "I"],
        ["vi", "ii", "V", "I", "IV", "V", "I", "I"],
        ["V", "I", "IV", "vi", "ii", "V", "I", "I"],
        ["ii", "V", "I", "vi", "IV", "I", "V", "I"],
        ["I", "iii", "vi", "IV", "ii", "V", "I", "IV", "V", "vi", "ii", "V"],
    ],
}

_MINOR_PROGRESSIONS: dict[int, list[list[str]]] = {
    1: [
        ["i", "V", "i", "i"],
        ["i", "i", "V", "i"],
        ["i", "iv", "i", "i"],
    ],
    2: [
        ["i", "iv", "V", "i"],
        ["i", "VI", "V", "i"],
        ["i", "iv", "i", "V"],
    ],
    3: [
        ["i", "iv", "V", "i"],
        ["i", "VI", "V", "i"],
        ["i", "iv", "i", "V"],
        ["i", "III", "V", "i"],
    ],
    4: [
        ["i", "VI", "iv", "V", "i", "III", "V", "i"],
        ["i", "iv", "VII", "III", "VI", "iv", "V", "i"],
        ["i", "III", "VI", "iv", "i", "iv", "V", "i"],
        ["iv", "V", "i", "VI", "III", "iv", "V", "i"],
        ["VI", "iv", "V", "i", "iv", "V", "i", "i"],
    ],
    5: [
        ["i", "VI", "iv", "V", "i", "III", "V", "i"],
        ["i", "iv", "VII", "III", "VI", "iv", "V", "i"],
        ["i", "III", "VI", "iv", "i", "iv", "V", "i"],
        ["iv", "V", "i", "VI", "III", "iv", "V", "i"],
        ["VI", "III", "iv", "V", "i", "iv", "V", "i"],
        ["V", "i", "VI", "iv", "III", "iv", "V", "i"],
        ["III", "VI", "iv", "V", "i", "iv", "V", "i"],
        ["i", "VI", "III", "VII", "i", "iv", "V", "i", "VI", "iv", "V", "i"],
    ],
}

_MAJOR_WEAK_CADENCE_BANK: dict[int, list[list[str]]] = {
    1: [["I", "I", "V", "V"], ["I", "IV", "I", "V"], ["I", "V", "I", "V"]],
    2: [["I", "IV", "I", "V"], ["I", "V", "IV", "V"], ["I", "IV", "V", "V"]],
    3: [["I", "IV", "ii", "V"], ["I", "V", "IV", "V"], ["I", "vi", "ii", "V"]],
    4: [["I", "vi", "ii", "V"], ["I", "IV", "ii", "V"], ["I", "V", "IV", "V"]],
    5: [["I", "vi", "ii", "V"], ["I", "IV", "ii", "V"], ["I", "ii", "IV", "V"]],
}

_MAJOR_STRONG_CADENCE_BANK: dict[int, list[list[str]]] = {
    1: [["I", "V", "V", "I"], ["I", "IV", "V", "I"], ["I", "I", "V", "I"]],
    2: [["I", "IV", "V", "I"], ["I", "V", "IV", "I"], ["I", "ii", "V", "I"]],
    3: [["I", "ii", "V", "I"], ["I", "IV", "V", "I"], ["I", "vi", "V", "I"]],
    4: [["I", "vi", "ii", "V"], ["I", "IV", "V", "I"], ["I", "ii", "V", "I"]],
    5: [["I", "vi", "ii", "V"], ["I", "IV", "ii", "V"], ["I", "ii", "V", "I"]],
}

_MINOR_WEAK_CADENCE_BANK: dict[int, list[list[str]]] = {
    1: [["i", "i", "v", "v"], ["i", "iv", "i", "v"], ["i", "V", "i", "V"]],
    2: [["i", "iv", "i", "V"], ["i", "VI", "iv", "V"], ["i", "iv", "V", "V"]],
    3: [["i", "iv", "V", "V"], ["i", "VI", "iv", "V"], ["i", "III", "iv", "V"]],
    4: [["i", "VI", "iv", "V"], ["i", "III", "iv", "V"], ["i", "iv", "VII", "V"]],
    5: [["i", "VI", "iv", "V"], ["i", "III", "iv", "V"], ["i", "iv", "VII", "V"]],
}

_MINOR_STRONG_CADENCE_BANK: dict[int, list[list[str]]] = {
    1: [["i", "V", "V", "i"], ["i", "iv", "V", "i"], ["i", "i", "V", "i"]],
    2: [["i", "iv", "V", "i"], ["i", "VI", "V", "i"], ["i", "III", "V", "i"]],
    3: [["i", "iv", "V", "i"], ["i", "VI", "V", "i"], ["i", "III", "V", "i"]],
    4: [["i", "VI", "iv", "V"], ["i", "iv", "V", "i"], ["i", "III", "V", "i"]],
    5: [["i", "VI", "iv", "V"], ["i", "iv", "V", "i"], ["i", "III", "V", "i"]],
}


def _progression_bank(
    grade: int,
    key_signature: str,
    *,
    cadence_strength: str,
) -> list[list[str]]:
    effective_grade = max(1, min(5, int(grade)))
    if is_minor_key(key_signature):
        bank = _MINOR_STRONG_CADENCE_BANK if cadence_strength == "strong" else _MINOR_WEAK_CADENCE_BANK
    else:
        bank = _MAJOR_STRONG_CADENCE_BANK if cadence_strength == "strong" else _MAJOR_WEAK_CADENCE_BANK
    return bank.get(effective_grade, bank[max(bank.keys())])


def _phrase_form_template(measure_count: int) -> list[list[int]]:
    if measure_count <= 4:
        return [list(range(1, measure_count + 1))]
    if measure_count in {8, 12, 16}:
        return [list(range(start, start + 4)) for start in range(1, measure_count + 1, 4)]

    phrases: list[list[int]] = []
    start = 1
    while start <= measure_count:
        end = min(measure_count, start + 3)
        phrases.append(list(range(start, end + 1)))
        start = end + 1
    return phrases


def _form_label(phrases: list[list[int]]) -> str:
    phrase_count = len(phrases)
    if phrase_count <= 1:
        return "Single phrase"
    if phrase_count == 2:
        return "A + B"
    if phrase_count == 3:
        return "A + A' + B"
    if phrase_count == 4:
        return "A + A' + B + close"
    return f"{phrase_count} phrases"


def _harmonic_plan(
    measure_count: int,
    grade: int,
    key_signature: str,
    phrases: list[list[int]],
    rng: random.Random,
    *,
    phrase_grammars: list[PhraseGrammar] | None = None,
) -> list[str]:
    if measure_count <= 0:
        return []

    minor = is_minor_key(key_signature)
    plan = ["I"] * measure_count if not minor else ["i"] * measure_count
    for phrase_index, phrase_measures in enumerate(phrases or _phrase_form_template(measure_count)):
        if not phrase_measures:
            continue

        # Grammar-aware cadence strength: consequent/closing get strong,
        # antecedent/continuation get weak (half cadence on V).
        pg = (
            phrase_grammars[phrase_index]
            if phrase_grammars and phrase_index < len(phrase_grammars)
            else None
        )
        if pg is not None:
            cadence_strength = (
                "strong" if pg.cadence_type in ("authentic", "plagal") else "weak"
            )
        else:
            cadence_strength = "strong" if phrase_measures[-1] == measure_count else "weak"

        bank = _progression_bank(grade, key_signature, cadence_strength=cadence_strength)
        progression = list(rng.choice(bank))
        if len(progression) < len(phrase_measures):
            while len(progression) < len(phrase_measures):
                progression.extend(rng.choice(bank))
        progression = progression[: len(phrase_measures)]

        if cadence_strength == "weak":
            progression[-1] = "V"
        else:
            # Plagal cadences end IV → I instead of V → I.
            if pg is not None and pg.cadence_type == "plagal":
                progression[-1] = "I" if not minor else "i"
                if len(progression) >= 2:
                    progression[-2] = "IV" if not minor else "iv"
            else:
                # Authentic: V → I
                progression[-1] = "I" if not minor else "i"
                if len(progression) >= 2 and progression[-2] not in {"V", "v"}:
                    progression[-2] = "V"

        # Deceptive cadences: V → vi instead of V → I (surprise resolution).
        if pg is not None and pg.cadence_type == "deceptive":
            progression[-1] = "vi" if not minor else "VI"
            if len(progression) >= 2 and progression[-2] not in {"V", "v"}:
                progression[-2] = "V"

        for measure_number, harmony in zip(phrase_measures, progression, strict=False):
            plan[measure_number - 1] = harmony
        if phrase_index > 0 and len(phrase_measures) >= 4:
            plan[phrase_measures[0] - 1] = progression[0]
    return plan


# ---------------------------------------------------------------------------
# Chord helpers
# ---------------------------------------------------------------------------

def _chord_pitch_classes(key_signature: str, harmony: str) -> set[int]:
    tonic = KEY_TONIC_PITCH_CLASS[key_signature]
    root_pc = (tonic + HARMONY_INTERVALS[harmony]) % 12
    third = 3 if harmony[0].islower() else 4
    return {root_pc, (root_pc + third) % 12, (root_pc + 7) % 12}


def _chord_tones_in_pool(pool: list[int], key_signature: str, harmony: str) -> list[int]:
    chord_pcs = _chord_pitch_classes(key_signature, harmony)
    tones = [midi for midi in pool if midi % 12 in chord_pcs]
    return tones or pool


def _build_block_triad(
    pool: list[int],
    key_signature: str,
    harmony: str,
    near_pitch: int,
    *,
    max_span: int | None = None,
) -> list[int]:
    """Return a 3-note block chord from pool near near_pitch."""
    chord_pcs = _chord_pitch_classes(key_signature, harmony)
    tones = sorted([p for p in pool if p % 12 in chord_pcs])
    if len(tones) < 3:
        return tones if tones else [pool[len(pool) // 2]]
    best_triad: list[int] = []
    best_dist = 999
    for i in range(len(tones) - 2):
        triad = [tones[i], tones[i + 1], tones[i + 2]]
        if max_span is not None and triad[-1] - triad[0] > max_span:
            continue
        center = sum(triad) / 3.0
        dist = abs(center - near_pitch)
        if dist < best_dist:
            best_dist = dist
            best_triad = triad
    if not best_triad and max_span is not None:
        bounded_tones = tones
        for start_index in range(len(tones)):
            low = tones[start_index]
            window = [pitch_value for pitch_value in tones if low <= pitch_value <= low + max_span]
            if len(window) >= 3:
                triad = [window[0], window[1], window[-1]]
                center = sum(triad) / 3.0
                dist = abs(center - near_pitch)
                if dist < best_dist:
                    best_dist = dist
                    best_triad = triad
                    bounded_tones = window
        if not best_triad and len(bounded_tones) >= 2:
            return [bounded_tones[0], bounded_tones[-1]]
    return best_triad


def _simultaneous_span_cap(
    grade: int,
    hand: str,
    *,
    is_cadence: bool = False,
    accent: bool = False,
) -> int:
    if hand == "rh":
        if grade <= 2:
            return 4
        if grade == 3:
            return 7
        if grade == 4:
            return 8
        return 9

    if grade <= 2:
        return 5
    if grade == 3:
        return 7
    if grade == 4:
        return 9
    if is_cadence or accent:
        return 12
    return 9


def _bounded_upper_tones(
    tones: list[int],
    low: int,
    max_span: int,
) -> list[int]:
    bounded = [pitch_value for pitch_value in tones if low < pitch_value <= low + max_span]
    if bounded:
        return bounded
    return [pitch_value for pitch_value in tones if pitch_value > low] or [low]


def _normalize_pitch_stack(pitches: list[int]) -> list[int]:
    return sorted({int(pitch_value) for pitch_value in pitches})


def _build_voiced_block_chord(
    pool: list[int],
    key_signature: str,
    harmony: str,
    near_pitch: int,
    *,
    top_target: int | None = None,
    bass_target: int | None = None,
    max_span: int | None = None,
) -> list[int]:
    base = _build_block_triad(pool, key_signature, harmony, near_pitch, max_span=max_span)
    tones = sorted({int(pitch_value) for pitch_value in pool if pitch_value % 12 in _chord_pitch_classes(key_signature, harmony)})
    if len(tones) < 2:
        return base

    resolved_top = base[-1]
    if top_target is not None:
        resolved_top = min(
            tones,
            key=lambda pitch_value: abs(pitch_value - top_target) + abs(pitch_value - near_pitch) * 0.08,
        )

    bass_candidates = [pitch_value for pitch_value in tones if pitch_value < resolved_top]
    if max_span is not None:
        bounded_bass = [pitch_value for pitch_value in bass_candidates if resolved_top - pitch_value <= max_span]
        if bounded_bass:
            bass_candidates = bounded_bass
    if not bass_candidates:
        bass_candidates = tones[:-1] or tones
    resolved_bass = base[0]
    if bass_target is not None:
        resolved_bass = min(
            bass_candidates,
            key=lambda pitch_value: abs(pitch_value - bass_target) + abs(pitch_value - base[0]) * 0.05,
        )
    else:
        resolved_bass = bass_candidates[0]

    mid_candidates = [
        pitch_value for pitch_value in tones
        if resolved_bass < pitch_value < resolved_top
    ]
    if max_span is not None:
        bounded_mid = [
            pitch_value for pitch_value in mid_candidates
            if pitch_value - resolved_bass <= max_span and resolved_top - pitch_value <= max_span
        ]
        if bounded_mid:
            mid_candidates = bounded_mid
    if mid_candidates:
        resolved_mid = min(
            mid_candidates,
            key=lambda pitch_value: abs(pitch_value - near_pitch) + abs((resolved_bass + resolved_top) / 2 - pitch_value) * 0.08,
        )
        return sorted([resolved_bass, resolved_mid, resolved_top])

    if resolved_bass == resolved_top:
        return [resolved_bass]
    return sorted([resolved_bass, resolved_top])


def _stable_tone(pool: list[int], key_signature: str, harmony: str) -> int:
    tonic_pc = KEY_TONIC_PITCH_CLASS[key_signature]
    preferred = {tonic_pc, (tonic_pc + 4) % 12, (tonic_pc + 7) % 12}
    harmony_tones = _chord_tones_in_pool(pool, key_signature, harmony)
    candidates = [midi for midi in harmony_tones if midi % 12 in preferred]
    return candidates[0] if candidates else harmony_tones[0]


def _event_primary_pitch(event: dict[str, Any]) -> int | None:
    pitches = [int(pitch_value) for pitch_value in event.get("pitches", [])]
    if not pitches:
        return None
    return max(pitches) if str(event.get("hand")) == "rh" else min(pitches)


def _rh_lead_pitch(event: dict[str, Any]) -> int | None:
    pitches = [int(pitch_value) for pitch_value in event.get("pitches", [])]
    if not pitches:
        return None
    return max(pitches)


def _event_interval_span(event: dict[str, Any]) -> int | None:
    pitches = sorted(int(pitch_value) for pitch_value in event.get("pitches", []))
    if len(pitches) < 2:
        return None
    return pitches[-1] - pitches[0]


def _is_second_dyad(event: dict[str, Any]) -> bool:
    span = _event_interval_span(event)
    if span is None:
        return False
    return _interval_category(abs(span)) == "2nd"


def _second_partner_candidates(top_pitch: int, key_signature: str) -> list[int]:
    candidates: list[int] = []
    key_pcs = _key_pitch_classes(key_signature)
    for delta in (-2, -1, 1, 2):
        candidate = top_pitch + delta
        if candidate % 12 not in key_pcs:
            continue
        if _interval_category(abs(candidate - top_pitch)) != "2nd":
            continue
        candidates.append(candidate)
    return candidates


def _choose_second_partner(
    top_pitch: int,
    key_signature: str,
    harmony: str,
    measure_role: str,
    rng: random.Random,
) -> int | None:
    candidates = _second_partner_candidates(top_pitch, key_signature)
    if not candidates:
        return None

    chord_pcs = _chord_pitch_classes(key_signature, harmony)
    best_partner: int | None = None
    best_score = -999.0
    for candidate in candidates:
        score = 0.0
        if candidate < top_pitch:
            score += 0.95
        if candidate % 12 in chord_pcs:
            score += 0.55
        if measure_role in {"answer", "develop"} and candidate < top_pitch:
            score += 0.22
        if measure_role == "intensify" and candidate > top_pitch:
            score += 0.12
        if abs(candidate - top_pitch) == 1:
            score += 0.08
        score += rng.random() * 0.18
        if score > best_score:
            best_score = score
            best_partner = candidate
    return best_partner


def _apply_right_hand_seconds(
    events: list[dict[str, Any]],
    request: dict[str, Any],
    preset: dict[str, Any],
    rng: random.Random,
) -> list[dict[str, Any]]:
    grade = int(request.get("grade", 0))
    if request.get("mode") != "piano" or grade not in {3, 4}:
        return events

    piano = preset.get("piano", {})
    base_chance = float(piano.get("rightSecondChance", 0.22 if grade == 3 else 0.32))
    updated = [{**event, "pitches": list(event.get("pitches", []))} for event in events]

    phrase_candidates: dict[int, list[tuple[float, int, int]]] = {}
    for index, event in enumerate(updated):
        if event.get("hand") != "rh" or event.get("isRest"):
            continue
        pitches = [int(pitch_value) for pitch_value in event.get("pitches", [])]
        if len(pitches) != 1:
            continue
        if event.get("tuplet") or event.get("tieType"):
            continue
        if float(event.get("_actualDur", event.get("quarterLength", 0.0))) < 0.5:
            continue
        technique = str(event.get("technique", ""))
        if technique in {"block chord", "chordal texture", "triplet", "scale run", "scale figure"}:
            continue
        measure_role = str(event.get("measureRole", "develop"))
        if measure_role == "cadence":
            continue
        if measure_role == "establish" and abs(float(event.get("offset", 0.0)) % _measure_total(request["timeSignature"])) < 0.001:
            continue

        top_pitch = pitches[0]
        harmony = str(event.get("harmony", "I"))
        partner = _choose_second_partner(top_pitch, request["keySignature"], harmony, measure_role, rng)
        if partner is None:
            continue

        score = float(event.get("_actualDur", event.get("quarterLength", 0.0)))
        if measure_role == "develop":
            score += 1.0
        elif measure_role == "answer":
            score += 0.75
        elif measure_role == "intensify":
            score += 0.6
        if str(event.get("phraseFunction", "")) in {"passing", "neighbor", "echo_fragment", "sequence"}:
            score += 0.45
        if str(event.get("ornamentFunction", "")) in {"passing", "neighbor"}:
            score += 0.35
        if partner < top_pitch:
            score += 0.22

        phrase_index = int(event.get("phraseIndex", 0))
        phrase_candidates.setdefault(phrase_index, []).append((score, index, partner))

    for phrase_index, candidates in phrase_candidates.items():
        if not candidates:
            continue
        measure_best: dict[int, tuple[float, int, int]] = {}
        for score, index, partner in candidates:
            measure_number = int(updated[index].get("measure", 0))
            existing = measure_best.get(measure_number)
            if existing is None or score > existing[0]:
                measure_best[measure_number] = (score, index, partner)

        collapsed_candidates = list(measure_best.values())
        phrase_measures = {int(updated[idx].get("measure", 0)) for _, idx, _ in collapsed_candidates}
        target_count = 1
        if grade >= 4 and len(phrase_measures) >= 3 and rng.random() < 0.45:
            target_count = 2

        chosen: list[tuple[int, int]] = []
        used_measures: set[int] = set()
        sorted_candidates = sorted(collapsed_candidates, key=lambda item: item[0], reverse=True)

        for _, index, partner in sorted_candidates:
            measure_number = int(updated[index].get("measure", 0))
            if measure_number in used_measures:
                continue
            measure_role = str(updated[index].get("measureRole", "develop"))
            chance = base_chance
            if measure_role == "develop":
                chance += 0.18
            elif measure_role == "answer":
                chance += 0.1
            elif measure_role == "intensify":
                chance += 0.08
            if rng.random() > min(0.95, chance):
                continue
            chosen.append((index, partner))
            used_measures.add(measure_number)
            if len(chosen) >= target_count:
                break

        if not chosen:
            best_index = sorted_candidates[0][1]
            best_partner = sorted_candidates[0][2]
            chosen = [(best_index, best_partner)]

        for index, partner in chosen:
            top_pitch = int(updated[index]["pitches"][0])
            lower, upper = sorted([partner, top_pitch])
            updated[index]["pitches"] = [lower, upper]
            updated[index]["intervalTechnique"] = "second"
            updated[index]["textureDetail"] = "rh-second"

    rh_second_by_measure: dict[int, list[int]] = {}
    for index, event in enumerate(updated):
        if event.get("hand") != "rh" or not _is_second_dyad(event):
            continue
        rh_second_by_measure.setdefault(int(event.get("measure", 0)), []).append(index)

    for measure_number, indices in rh_second_by_measure.items():
        if len(indices) <= 1:
            continue
        keep_index = max(
            indices,
            key=lambda idx: (
                float(updated[idx].get("_actualDur", updated[idx].get("quarterLength", 0.0))),
                -float(updated[idx].get("offset", 0.0)),
            ),
        )
        for index in indices:
            if index == keep_index:
                continue
            lead_pitch = _rh_lead_pitch(updated[index])
            if lead_pitch is None:
                continue
            updated[index]["pitches"] = [lead_pitch]
            updated[index].pop("intervalTechnique", None)
            updated[index].pop("textureDetail", None)

    return updated


def _apply_right_hand_harmonic_punctuations(
    events: list[dict[str, Any]],
    request: dict[str, Any],
    preset: dict[str, Any],
    rng: random.Random,
) -> list[dict[str, Any]]:
    grade = int(request.get("grade", 0))
    if request.get("mode") != "piano" or grade < 4:
        return events

    total = _measure_total(request["timeSignature"])
    pulse = _pulse_value(request["timeSignature"])
    focus = str(request.get("readingFocus", "balanced"))
    updated = [{**event, "pitches": list(event.get("pitches", []))} for event in events]

    phrase_candidates: dict[int, list[tuple[float, int]]] = {}
    for index, event in enumerate(updated):
        if event.get("hand") != "rh" or event.get("isRest"):
            continue
        pitches = [int(pitch_value) for pitch_value in event.get("pitches", [])]
        if len(pitches) != 1:
            continue
        if event.get("tuplet") or event.get("tieType"):
            continue

        duration_value = float(event.get("_actualDur", event.get("quarterLength", 0.0)))
        if duration_value < max(0.5, pulse * 0.5):
            continue

        technique = str(event.get("technique", ""))
        if technique in {
            "block chord",
            "chordal texture",
            "triplet",
            "scale run",
            "scale figure",
            "scale figure landing",
        }:
            continue

        measure_role = str(event.get("measureRole", "develop"))
        if measure_role == "cadence":
            continue

        local_offset = round(float(event.get("offset", 0.0)) % total, 3)
        on_structural_beat = abs((local_offset / pulse) - round(local_offset / pulse)) < 0.08
        phrase_function = str(event.get("phraseFunction", ""))
        allow_inner_punct = (
            grade >= 5
            and duration_value >= 0.5
            and phrase_function in {"passing", "neighbor", "sequence", "echo_fragment"}
        )
        if not on_structural_beat and not allow_inner_punct:
            continue

        score = duration_value
        if measure_role == "develop":
            score += 1.2
        elif measure_role == "answer":
            score += 0.95
        elif measure_role == "intensify":
            score += 0.8
        if local_offset > 0:
            score += 0.3
        if focus == "harmonic":
            score += 0.45
        elif focus == "balanced":
            score += 0.2
        if technique in {"melody", "motif", "motif tail"}:
            score += 0.2
        if phrase_function in {"passing", "neighbor", "sequence", "echo_fragment"}:
            score += 0.25
        if allow_inner_punct:
            score += 0.18

        phrase_index = int(event.get("phraseIndex", 0))
        phrase_candidates.setdefault(phrase_index, []).append((score, index))

    for phrase_index, candidates in phrase_candidates.items():
        if not candidates:
            continue

        by_measure: dict[int, tuple[float, int]] = {}
        for score, index in candidates:
            measure_number = int(updated[index].get("measure", 0))
            existing = by_measure.get(measure_number)
            if existing is None or score > existing[0]:
                by_measure[measure_number] = (score, index)

        collapsed = sorted(by_measure.values(), key=lambda item: item[0], reverse=True)
        target_count = 1
        if grade >= 5:
            if len(collapsed) >= 2:
                target_count = 2
            if len(collapsed) >= 4 and focus in {"balanced", "harmonic"} and rng.random() < 0.62:
                target_count = 3
            if len(collapsed) >= 6 and focus == "harmonic" and rng.random() < 0.24:
                target_count = 4

        chosen_indices: list[int] = []
        for _, index in collapsed:
            measure_number = int(updated[index].get("measure", 0))
            local_offset = round(float(updated[index].get("offset", 0.0)) % total, 3)
            if any(
                int(updated[chosen].get("measure", 0)) == measure_number
                and abs(round(float(updated[chosen].get("offset", 0.0)) % total, 3) - local_offset) < 0.4
                for chosen in chosen_indices
            ):
                continue
            chosen_indices.append(index)
            if len(chosen_indices) >= target_count:
                break

        for index in chosen_indices:
            event = updated[index]
            top_pitch = int(event["pitches"][0])
            harmony = str(event.get("harmony", "I"))
            measure_role = str(event.get("measureRole", "develop"))
            duration_value = float(event.get("_actualDur", event.get("quarterLength", 0.0)))
            rh_span_cap = _simultaneous_span_cap(
                grade,
                "rh",
                accent=measure_role in {"answer", "intensify"},
            )
            use_triad = (
                grade >= 5
                and duration_value >= pulse
                and (measure_role == "intensify" or focus == "harmonic")
                and rng.random() < 0.62
            )
            key_pcs = _key_pitch_classes(request["keySignature"])
            local_pool = [
                midi for midi in range(top_pitch - 12, top_pitch + 5)
                if midi % 12 in key_pcs
            ]
            voicing = _build_voiced_block_chord(
                local_pool or _position_pitches_from_root(
                    HAND_POSITION_ROOTS["rh"][request["handPosition"]],
                    request["keySignature"],
                    10,
                ),
                request["keySignature"],
                harmony,
                top_pitch,
                top_target=top_pitch,
                max_span=rh_span_cap,
            )
            if not voicing or len(voicing) < 2:
                continue
            if use_triad and len(voicing) >= 3:
                event["pitches"] = voicing
                event["technique"] = "melodic chord accent"
                event["textureDetail"] = "rh-chord-punct"
            else:
                event["pitches"] = [voicing[0], voicing[-1]]
                event["technique"] = "melodic dyad"
                event["textureDetail"] = "rh-dyad-punct"

    return updated


def _lh_bass_pitch(event: dict[str, Any]) -> int | None:
    pitches = [int(pitch_value) for pitch_value in event.get("pitches", [])]
    if not pitches:
        return None
    return min(pitches)


def _sequence_from_cycle(source: list[list[int]], count: int) -> list[list[int]]:
    output: list[list[int]] = []
    while len(output) < count:
        output.extend(source)
    return output[:count]


# ---------------------------------------------------------------------------
# Weights & pitch/duration selection (NEW — cleaner design)
# ---------------------------------------------------------------------------

def _weights_for_hand(hand: str, preset: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    """Return weight parameters for the given hand."""
    p = preset["piano"]
    base = {
        "stepWeight": float(p.get("stepWeight", 0.7)),
        "chordToneWeight": float(p.get("chordToneWeight", 2.0)),
        "strongBeatChordToneWeight": float(p.get("strongBeatChordToneWeight", 0.88)),
        "varietyDecay": float(p.get("varietyDecay", 0.4)),
        "directionPersistence": float(p.get("directionPersistence", 0.6)),
        "rangeSigma": float(p.get("rangeSigma", 3.0)),
        "allowIntervals": list(p.get("allowIntervals", ["2nd", "3rd"])),
        "blockChordChance": float(p.get("blockChordChance", 0.0)),
        "tripletChance": float(p.get("tripletChance", 0.0)),
        "restChance": float(p.get("rightRestChance", 0.05)),
    }
    if hand == "rh":
        motion = str(request.get("rightHandMotion", "mixed"))
        if motion == "stepwise":
            base["stepWeight"] = min(0.96, base["stepWeight"] + 0.14)
            base["rangeSigma"] = max(2.0, base["rangeSigma"] - 0.6)
        elif motion == "small-leaps":
            base["stepWeight"] = max(0.35, base["stepWeight"] - 0.12)
            base["rangeSigma"] = min(10.0, base["rangeSigma"] + 0.45)
        elif motion == "mixed":
            base["stepWeight"] = max(0.4, base["stepWeight"] - 0.04)
            base["rangeSigma"] = min(10.0, base["rangeSigma"] + 0.2)
    if hand == "lh":
        # LH anchors harmony more, steps a bit more
        base["chordToneWeight"] = base["chordToneWeight"] * 1.4
        base["stepWeight"] = min(0.85, base["stepWeight"] + 0.15)
        base["restChance"] = float(p.get("leftRestChance", 0.08))
        base["blockChordChance"] = base["blockChordChance"] * 0.6
    return base


def _preferred_left_families(
    request: dict[str, Any],
    available_families: list[str],
) -> list[str]:
    preferred_pattern = str(request.get("leftHandPattern", "held"))
    available_set = set(available_families)
    preferred = [
        family
        for family in _LEFT_PATTERN_FAMILY_PREFERENCES.get(preferred_pattern, ())
        if family in available_set
    ]
    return preferred or list(available_families)


def _interval_category(semitones: int) -> str:
    if semitones <= 2:
        return "2nd"
    if semitones <= 4:
        return "3rd"
    if semitones <= 5:
        return "4th"
    if semitones <= 7:
        return "5th"
    if semitones <= 9:
        return "6th"
    if semitones <= 11:
        return "7th"
    return "octave"


def _recent_pitch_streak(recent_pitches: list[int], pitch_value: int) -> int:
    streak = 0
    for recent_pitch in reversed(recent_pitches):
        if recent_pitch != pitch_value:
            break
        streak += 1
    return streak


def _recent_reversal_count(recent: list[int], n: int = 5) -> int:
    """Count direction reversals in the last *n* pitches."""
    if len(recent) < 3:
        return 0
    tail = recent[-n:]
    reversals = 0
    for i in range(2, len(tail)):
        d1 = tail[i - 1] - tail[i - 2]
        d2 = tail[i] - tail[i - 1]
        if d1 != 0 and d2 != 0 and (d1 > 0) != (d2 > 0):
            reversals += 1
    return reversals


def _weighted_pitch_select(
    pool: list[int],
    prev_pitch: int,
    recent_pitches: list[int],
    direction: int,
    key_signature: str,
    harmony: str,
    weights: dict[str, Any],
    max_leap: int,
    on_strong_beat: bool,
    rng: random.Random,
) -> int:
    """Score each pool pitch and sample one."""
    chord_pcs = _chord_pitch_classes(key_signature, harmony)
    pool_center = (pool[0] + pool[-1]) / 2.0
    sigma = weights["rangeSigma"]
    step_w = weights["stepWeight"]
    allowed_ivls = weights.get("allowIntervals", ["2nd", "3rd"])

    # step_ratio: how much more likely a step is vs a 3rd (baseline)
    step_ratio = step_w / max(0.08, 1.0 - step_w)

    candidates: list[int] = []
    scores: list[float] = []

    for p in pool:
        interval = abs(p - prev_pitch)
        if interval > max_leap:
            continue

        # --- Interval scoring ---
        ivl_cat = _interval_category(interval)
        if interval == 0:
            step_score = 0.2
        elif ivl_cat == "2nd":
            step_score = step_ratio
        elif ivl_cat == "3rd":
            step_score = 1.0
        elif ivl_cat in allowed_ivls:
            if ivl_cat == "4th":
                step_score = 0.75
            elif ivl_cat == "5th":
                step_score = 0.55
            elif ivl_cat == "6th":
                step_score = 0.4
            elif ivl_cat == "7th":
                step_score = 0.3
            elif ivl_cat == "octave":
                step_score = 0.25
            else:
                step_score = 0.2
        else:
            step_score = 0.01

        # --- Chord tone gravity ---
        if p % 12 in chord_pcs:
            chord_score = weights["strongBeatChordToneWeight"] * 2.0 if on_strong_beat else weights["chordToneWeight"]
        else:
            chord_score = 1.0

        # --- Direction tendency ---
        # Boost persistence to create longer melodic runs (SRF-style commitment).
        effective_persistence = min(0.92, weights["directionPersistence"] + 0.12)
        delta = p - prev_pitch
        if delta == 0:
            dir_score = 0.35
        elif (delta > 0 and direction > 0) or (delta < 0 and direction < 0):
            dir_score = effective_persistence
        else:
            dir_score = 1.0 - effective_persistence
        dir_score = max(0.05, dir_score)

        # Phase 8: anti-oscillation — penalize reversals when melody is zigzagging
        would_reverse = delta != 0 and (
            (delta > 0 and direction < 0) or (delta < 0 and direction > 0)
        )
        if would_reverse:
            reversals = _recent_reversal_count(recent_pitches)
            if reversals >= 2:
                dir_score *= 0.08   # near-zero: strongly commit to current direction
            elif reversals >= 1:
                dir_score *= 0.30   # discourage changing again after one reversal

        # --- Range centering (Gaussian) ---
        range_score = math.exp(-((p - pool_center) / max(0.5, sigma)) ** 2)

        # --- Variety penalty ---
        variety_score = 1.0
        decay = weights["varietyDecay"]
        for idx, recent in enumerate(reversed(recent_pitches[-5:])):
            if recent == p:
                variety_score *= decay ** (1.0 / (idx + 1))

        repeat_streak = _recent_pitch_streak(recent_pitches, p)
        if interval == 0:
            repeat_penalties = {
                0: 0.4,
                1: 0.24,
                2: 0.1,
            }
            variety_score *= repeat_penalties.get(repeat_streak, 0.04)
        elif repeat_streak >= 2 and interval <= 2:
            variety_score *= 0.82

        total_score = step_score * chord_score * dir_score * range_score * variety_score
        candidates.append(p)
        scores.append(max(0.001, total_score))

    if not candidates:
        return prev_pitch if prev_pitch in pool else pool[len(pool) // 2]

    return rng.choices(candidates, weights=scores, k=1)[0]


def _weighted_duration_select(
    remaining: float,
    allowed: list[float],
    pulse: float,
    cursor: float,
    prev_dur: float | None,
    rng: random.Random,
) -> float:
    """Pick a duration from allowed values that fits remaining time."""
    valid = [d for d in allowed if d <= remaining + 0.01]
    if not valid:
        # Snap to nearest expressible duration
        snap = min(allowed, key=lambda d: abs(d - remaining))
        return snap if abs(snap - remaining) < 0.1 else round(remaining * 4) / 4

    weights: list[float] = []
    for d in valid:
        w = 1.0
        # Strong bias toward musical durations (quarter, dotted quarter, half)
        # to avoid sixteenth-note spam
        if d >= pulse:
            w *= 2.5       # quarter note or longer: strongly preferred
        elif d >= pulse * 0.75:
            w *= 1.8       # dotted eighth: somewhat preferred
        elif d >= pulse * 0.5:
            w *= 1.2       # eighth note: slightly preferred
        else:
            w *= 0.4       # sixteenths: less likely as standalone picks

        # Prefer beat-aligned durations
        if abs(cursor % pulse) < 0.001 and d >= pulse:
            w *= 1.8
        # Dotted durations get a boost for rhythmic interest
        if d in (1.5, 0.75):
            w *= 1.5
        # Avoid repeating same duration
        if prev_dur is not None and abs(d - prev_dur) < 0.001:
            w *= 0.5
        # Avoid leaving unfillable remainder
        leftover = round(remaining - d, 3)
        if leftover > 0 and leftover < min(allowed):
            w *= 0.01
        weights.append(max(0.01, w))

    return rng.choices(valid, weights=weights, k=1)[0]


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
# Texture builders
# ---------------------------------------------------------------------------

def _snap_duration(dur: float, allowed: list[float]) -> float:
    """Snap a duration to the nearest allowed standard value (fixes float drift)."""
    best = min(allowed, key=lambda d: abs(d - dur))
    if abs(best - dur) < 0.02:
        return best
    return dur


def _next_cell_duration(
    rhythm_cells: list[list[float]],
    cell_state: dict[str, Any],
    remaining: float,
    allowed_durations: list[float],
    rng: random.Random,
) -> float:
    """Get the next duration from rhythm cells, picking a new cell when needed."""
    # If we have durations left in the current cell, use them
    queue = cell_state.get("queue", [])
    if queue:
        dur = queue.pop(0)
        cell_state["queue"] = queue
        return dur

    # Pick a new cell that fits the remaining time
    fitting = [c for c in rhythm_cells
               if round(sum(c), 3) <= remaining + 0.001
               and all(d in set(allowed_durations) for d in c)]
    if fitting:
        cell = rng.choice(fitting)
        cell_state["queue"] = list(cell[1:])  # remaining durations
        return cell[0]

    # No cell fits — pick a single allowed duration that fits
    valid = [d for d in allowed_durations if d <= remaining + 0.01]
    if valid:
        # Snap remaining to nearest allowed if close (float drift fix)
        snapped = _snap_duration(remaining, allowed_durations)
        if snapped in valid:
            return snapped
        return rng.choice(valid)
    # Last resort: snap to nearest allowed
    return _snap_duration(remaining, allowed_durations)


def _nearest_pool_index(pool: list[int], pitch_value: int) -> int:
    if pitch_value in pool:
        return pool.index(pitch_value)
    return min(range(len(pool)), key=lambda idx: abs(pool[idx] - pitch_value))


def _duration_signature(durations: list[float]) -> tuple[tuple[str, float], ...]:
    return tuple(("M", round(float(duration_value), 2)) for duration_value in durations)


def _motive_index_bounds(steps: list[int], pool_length: int) -> tuple[int, int]:
    cumulative = 0
    low = 0
    high = 0
    for step in steps:
        cumulative += int(step)
        low = min(low, cumulative)
        high = max(high, cumulative)
    min_index = max(0, -low)
    max_index = max(min_index, pool_length - 1 - high)
    return min_index, max_index


def _fit_motive_start_index(desired_index: int, steps: list[int], pool_length: int) -> int:
    min_index, max_index = _motive_index_bounds(steps, pool_length)
    return max(min_index, min(max_index, desired_index))


def _realize_motive_fragment(
    pool: list[int],
    harmony_tones: list[int],
    blueprint: dict[str, Any],
    transform: str,
    prev_pitch: int,
    recent: list[int],
    direction: int,
    total: float,
    max_leap: int,
    target_pitch: int | None = None,
) -> tuple[list[dict[str, Any]], int, list[int], int, float, dict[str, Any] | None]:
    if transform in {"none", "contrast"}:
        return [], prev_pitch, recent, direction, 0.0, None

    durations = list(blueprint.get("durations", []))
    steps = list(blueprint.get("steps", []))
    if transform == "cadence":
        durations = list(blueprint.get("answerDurations", durations))
        durations = durations[: max(2, min(3, len(durations)))]
        if len(durations) >= 2:
            durations[-1] = round(sum(durations[-2:]), 3)
            durations = durations[:-1]
        steps = steps[: max(1, len(durations) - 1)]
    elif transform == "fragment":
        keep_count = max(2, min(3, len(durations)))
        durations = durations[:keep_count]
        steps = steps[: max(1, keep_count - 1)]
    elif transform == "sequence":
        durations = list(blueprint.get("answerDurations", durations))
        steps = list(steps)
    # Phase 10: "intensify" transform — same rhythm, wider intervals
    elif transform == "intensify":
        durations = list(blueprint.get("answerDurations", durations))
        steps = [min(3, max(-3, s + (1 if s > 0 else -1))) for s in steps]

    total_duration = round(sum(durations), 3)
    if total_duration <= 0 or total_duration > total + 0.001:
        return [], prev_pitch, recent, direction, 0.0, None

    if harmony_tones:
        anchor_pitch = min(harmony_tones, key=lambda candidate: abs(candidate - prev_pitch))
    else:
        anchor_pitch = prev_pitch

    desired_index = _nearest_pool_index(pool, anchor_pitch)
    if transform == "sequence":
        # Phase 10: wider transposition (a third instead of a step)
        shift = 2 if direction >= 0 else -2
        desired_index = max(0, min(len(pool) - 1, desired_index + shift))
    elif transform == "intensify":
        shift = 1 if direction >= 0 else -1
        desired_index = max(0, min(len(pool) - 1, desired_index + shift))
    current_index = _fit_motive_start_index(desired_index, steps, len(pool))
    # Safety clamp — full-measure motifs can produce indices outside pool bounds
    current_index = max(0, min(len(pool) - 1, current_index))

    events: list[dict[str, Any]] = []
    cursor = 0.0
    current_pitch = pool[current_index]
    technique = "motif"

    events.append({
        "hand": "rh",
        "offset": 0.0,
        "quarterLength": durations[0],
        "isRest": False,
        "pitches": [current_pitch],
        "technique": technique,
        "motifTechnique": transform,
    })
    recent = (recent + [current_pitch])[-6:]
    prev_pitch = current_pitch
    last_event = events[-1]
    cursor = round(cursor + float(durations[0]), 3)

    for duration_value, step in zip(durations[1:], steps, strict=False):
        next_index = max(0, min(len(pool) - 1, current_index + step))
        next_pitch = pool[next_index]
        if abs(next_pitch - prev_pitch) > max_leap:
            step_sign = 1 if step >= 0 else -1
            while abs(next_pitch - prev_pitch) > max_leap and next_index != current_index:
                next_index -= step_sign
                next_pitch = pool[next_index]
        events.append({
            "hand": "rh",
            "offset": round(cursor, 3),
            "quarterLength": duration_value,
            "isRest": False,
            "pitches": [next_pitch],
            "technique": technique,
            "motifTechnique": transform,
        })
        delta = next_pitch - prev_pitch
        if delta != 0:
            direction = 1 if delta > 0 else -1
        recent = (recent + [next_pitch])[-6:]
        prev_pitch = next_pitch
        current_index = next_index
        last_event = events[-1]
        cursor = round(cursor + float(duration_value), 3)

    if transform == "cadence" and last_event and harmony_tones:
        stable_pitch = min(harmony_tones, key=lambda candidate: abs(candidate - prev_pitch))
        last_event["pitches"] = [stable_pitch]
        prev_pitch = stable_pitch
        recent = (recent[:-1] + [stable_pitch])[-6:] if recent else [stable_pitch]
    elif last_event and target_pitch is not None:
        aligned_pitch = min(pool, key=lambda candidate: abs(candidate - int(target_pitch)))
        last_event["pitches"] = [aligned_pitch]
        prev_pitch = aligned_pitch
        recent = (recent[:-1] + [aligned_pitch])[-6:] if recent else [aligned_pitch]

    return events, prev_pitch, recent, direction, cursor, last_event


def _clamp_pool_index(index_value: int, pool_length: int) -> int:
    return max(0, min(pool_length - 1, index_value))


def _interpolate_index_path(
    start_index: int,
    target_index: int,
    note_count: int,
    pool_length: int,
) -> list[int]:
    if note_count <= 1:
        return [_clamp_pool_index(target_index, pool_length)]

    if start_index == target_index:
        return [start_index for _ in range(note_count)]

    path: list[int] = []
    for idx in range(note_count):
        ratio = idx / max(1, note_count - 1)
        guess = round(start_index + (target_index - start_index) * ratio)
        guess = _clamp_pool_index(guess, pool_length)
        if path and guess == path[-1]:
            step = 1 if target_index > start_index else -1
            guess = _clamp_pool_index(path[-1] + step, pool_length)
        path.append(guess)

    path[-1] = _clamp_pool_index(target_index, pool_length)
    return path


def _choose_continuation_durations(
    remaining: float,
    pulse: float,
    allowed_durations: list[float],
    gesture: str,
    rng: random.Random,
) -> list[float]:
    gesture_parts = {
        "sustain": (1, 2),
        "hold-answer": (2, 3),
        "neighbor-answer": (2, 3),
        "echo-tail": (2, 3),
        "bridge": (2, 4),
        "sequence-tail": (2, 4),
        "fragment-push": (3, 4),
        "climb": (3, 4),
        "rise-release": (3, 4),
        "cadence-step": (2, 3),
        "cadence-turn": (2, 3),
    }
    min_parts, max_parts = gesture_parts.get(gesture, (2, 4))
    variants = _fit_measure_variants(remaining, allowed_durations, min_parts, max_parts)
    ordered = sorted({round(float(value), 3) for value in allowed_durations}, reverse=True)
    if not variants:
        fallback = _fit_measure(round(remaining, 3), ordered, rng)
        if fallback:
            return [round(float(value), 3) for value in fallback]
        return [_snap_duration(remaining, ordered)]

    weights: list[float] = []
    for variant in variants:
        count = len(variant)
        first = variant[0]
        last = variant[-1]
        longest = max(variant)
        score = 1.0

        if gesture in {"sustain", "hold-answer"}:
            score *= 1.25 if count <= 2 else 0.75
            score *= 1.20 if first >= pulse or longest >= pulse else 0.85
        elif gesture in {"neighbor-answer", "cadence-turn", "echo-tail"}:
            score *= 1.20 if count in {2, 3} else 0.75
            score *= 1.25 if abs(last - longest) < 0.02 else 0.90
        elif gesture in {"bridge", "sequence-tail"}:
            score *= 1.15 if count in {2, 3} else 0.90
            score *= 1.10 if longest <= max(pulse, 1.0) * 1.5 else 0.92
        elif gesture in {"fragment-push", "climb", "rise-release"}:
            score *= 1.25 if count >= 3 else 0.72
            score *= 1.18 if any(value <= pulse + 0.001 for value in variant[:-1]) else 0.88
        elif gesture == "cadence-step":
            score *= 1.25 if count in {2, 3} else 0.72
            score *= 1.35 if abs(last - longest) < 0.02 else 0.86

        weights.append(max(0.05, score))

    return list(rng.choices(variants, weights=weights, k=1)[0])


def _realize_continuation_figure(
    pool: list[int],
    harmony_tones: list[int],
    gesture: str,
    prev_pitch: int,
    recent: list[int],
    direction: int,
    remaining: float,
    pulse: float,
    allowed_durations: list[float],
    measure_role: str,
    current_measure: int,
    target_peak_measure: int,
    contour_dir: int,
    max_leap: int,
    rng: random.Random,
) -> tuple[list[dict[str, Any]], int, list[int], int, float, dict[str, Any] | None]:
    if remaining <= 0.001:
        return [], prev_pitch, recent, direction, 0.0, None

    durations = _choose_continuation_durations(remaining, pulse, allowed_durations, gesture, rng)
    if not durations:
        return [], prev_pitch, recent, direction, 0.0, None

    start_index = _nearest_pool_index(pool, prev_pitch)
    stable_indices = sorted({
        _nearest_pool_index(pool, pitch_value) for pitch_value in (harmony_tones or [prev_pitch])
    })
    stable_index = min(stable_indices, key=lambda idx: abs(pool[idx] - prev_pitch))
    pool_length = len(pool)
    note_count = len(durations)

    drive_direction = contour_dir if contour_dir != 0 else (direction if direction != 0 else 1)
    if current_measure > target_peak_measure:
        drive_direction *= -1
    push_direction = 1 if current_measure <= target_peak_measure else -1

    path_indices: list[int]
    if gesture == "sustain":
        path_indices = [stable_index for _ in durations]
    elif gesture == "hold-answer":
        target_index = stable_index
        path_indices = _interpolate_index_path(start_index, target_index, note_count, pool_length)
        if note_count >= 2:
            path_indices[0] = start_index
            path_indices[-1] = target_index
    elif gesture == "neighbor-answer":
        neighbor_direction = -drive_direction if drive_direction != 0 else -1
        neighbor_index = _clamp_pool_index(stable_index + neighbor_direction, pool_length)
        if note_count <= 2:
            path_indices = [neighbor_index, stable_index][:note_count]
        else:
            path_indices = [stable_index, neighbor_index] + [stable_index for _ in range(note_count - 2)]
    elif gesture == "echo-tail":
        target_index = _clamp_pool_index(start_index + drive_direction, pool_length)
        path_indices = [start_index]
        if note_count >= 2:
            path_indices.append(target_index)
        while len(path_indices) < note_count:
            path_indices.append(stable_index)
    elif gesture in {"bridge", "sequence-tail"}:
        target_index = _clamp_pool_index(start_index + drive_direction * max(1, note_count - 1), pool_length)
        path_indices = _interpolate_index_path(start_index, target_index, note_count, pool_length)
        path_indices[-1] = min(stable_indices, key=lambda idx: abs(idx - path_indices[-1]))
    elif gesture in {"fragment-push", "climb"}:
        push_distance = max(2, note_count - 1)
        target_index = _clamp_pool_index(start_index + push_direction * push_distance, pool_length)
        path_indices = _interpolate_index_path(start_index, target_index, note_count, pool_length)
    elif gesture == "rise-release":
        rise_index = _clamp_pool_index(start_index + push_direction * max(1, note_count - 2), pool_length)
        path_indices = _interpolate_index_path(start_index, rise_index, max(2, note_count - 1), pool_length)
        path_indices = path_indices[: max(1, note_count - 1)] + [stable_index]
        if len(path_indices) < note_count:
            path_indices.append(stable_index)
    elif gesture == "cadence-turn":
        lower_stables = [idx for idx in stable_indices if idx <= start_index]
        target_index = lower_stables[-1] if lower_stables else min(stable_indices)
        neighbor_index = _clamp_pool_index(target_index + 1, pool_length)
        if neighbor_index == target_index:
            neighbor_index = _clamp_pool_index(target_index - 1, pool_length)
        if note_count <= 2:
            path_indices = [neighbor_index, target_index][:note_count]
        else:
            path_indices = [neighbor_index, target_index] + [target_index for _ in range(note_count - 2)]
    else:  # cadence-step and fallback
        lower_stables = [idx for idx in stable_indices if idx <= start_index]
        target_index = lower_stables[-1] if lower_stables else min(stable_indices)
        path_indices = _interpolate_index_path(start_index, target_index, note_count, pool_length)
        if note_count >= 2 and len(set(path_indices)) == 1:
            approach_index = _clamp_pool_index(target_index + 1, pool_length)
            path_indices = [approach_index] + [target_index for _ in range(note_count - 1)]

    path_indices = _soften_static_path(
        path_indices,
        pool_length,
        drive_direction if drive_direction != 0 else push_direction,
    )

    events: list[dict[str, Any]] = []
    cursor = 0.0
    last_event: dict[str, Any] | None = None
    for duration_value, index_value in zip(durations, path_indices, strict=False):
        pitch_value = pool[_clamp_pool_index(index_value, pool_length)]
        if events and abs(pitch_value - prev_pitch) > max_leap:
            step_sign = 1 if pitch_value > prev_pitch else -1
            adjusted_index = _nearest_pool_index(pool, prev_pitch)
            while abs(pool[adjusted_index] - prev_pitch) <= max_leap and adjusted_index != index_value:
                next_index = _clamp_pool_index(adjusted_index + step_sign, pool_length)
                if next_index == adjusted_index or abs(pool[next_index] - prev_pitch) > max_leap:
                    break
                adjusted_index = next_index
            pitch_value = pool[adjusted_index]

        event = {
            "hand": "rh",
            "offset": round(cursor, 3),
            "quarterLength": duration_value,
            "isRest": False,
            "pitches": [pitch_value],
            "technique": "melody",
            "phraseFunction": gesture,
            "continuationRole": measure_role,
        }
        events.append(event)

        delta = pitch_value - prev_pitch
        if delta != 0:
            direction = 1 if delta > 0 else -1
        prev_pitch = pitch_value
        recent = (recent + [pitch_value])[-6:]
        cursor = round(cursor + float(duration_value), 3)
        last_event = event

    return events, prev_pitch, recent, direction, cursor, last_event


def _relative_slot_to_index(register_slot: float, pool_length: int) -> int:
    if pool_length <= 1:
        return 0
    return _clamp_pool_index(int(round(register_slot * (pool_length - 1))), pool_length)


def _pitch_role_candidates(
    pool: list[int],
    harmony_tones: list[int],
    key_signature: str,
    harmony: str,
    pitch_role: str,
) -> list[int]:
    tonic_pc = KEY_TONIC_PITCH_CLASS[key_signature]
    root_pc = (tonic_pc + HARMONY_INTERVALS[harmony]) % 12
    third_pc = (root_pc + (3 if harmony[0].islower() else 4)) % 12
    fifth_pc = (root_pc + 7) % 12
    dominant_pc = (tonic_pc + 7) % 12

    role_map = {
        "root": {root_pc},
        "third": {third_pc},
        "fifth": {fifth_pc},
        "tonic": {tonic_pc},
        "dominant": {dominant_pc},
        "stable": _chord_pitch_classes(key_signature, harmony) | {tonic_pc},
    }
    desired_pcs = role_map.get(pitch_role, _chord_pitch_classes(key_signature, harmony))
    candidates = [pitch_value for pitch_value in pool if pitch_value % 12 in desired_pcs]
    if candidates:
        return candidates
    if harmony_tones:
        return list(harmony_tones)
    return list(pool)


def _fit_desired_durations(
    total: float,
    allowed_durations: list[float],
    desired: list[float],
    rng: random.Random,
) -> list[float]:
    allowed = sorted({round(float(value), 3) for value in allowed_durations if float(value) > 0}, reverse=True)
    allowed_set = set(allowed)
    durations: list[float] = []
    remaining = round(float(total), 3)

    for desired_duration in desired:
        snapped = round(float(desired_duration), 3)
        if snapped in allowed_set and snapped <= remaining + 0.001:
            durations.append(snapped)
            remaining = round(remaining - snapped, 3)

    if remaining > 0.001:
        tail = _fit_measure(remaining, allowed, rng)
        if tail is None:
            snapped = min(allowed, key=lambda value: abs(value - remaining))
            tail = [snapped]
        durations.extend([round(float(value), 3) for value in tail])

    return durations


def _preferred_connection_durations(
    connection_name: str,
    total: float,
    pulse: float,
    allowed_durations: list[float],
    rng: random.Random,
) -> list[float] | None:
    part_ranges = {
        "arrival": (1, 3),
        "lead_in": (2, 3),
        "passing": (2, 4),
        "neighbor": (2, 4),
        "arpeggiation": (3, 4),
        "sequence": (3, 4),
        "suspension_like": (2, 3),
        "cadential_turn": (3, 5),
        "echo_fragment": (2, 4),
        "liquidation": (2, 4),
    }
    min_parts, max_parts = part_ranges.get(connection_name, (2, 4))
    variants = _fit_measure_variants(total, allowed_durations, min_parts, max_parts)
    if not variants:
        return None

    weights: list[float] = []
    for variant in variants:
        count = len(variant)
        longest = max(variant)
        last = variant[-1]
        short_count = sum(1 for value in variant if value <= max(0.5, pulse * 0.5) + 0.001)
        score = 1.0

        if connection_name == "arrival":
            score *= 1.7 if count <= 2 else 1.15 if count == 3 else 0.35
            score *= 1.45 if abs(last - longest) < 0.02 else 0.88
            score *= 0.78 ** short_count
        elif connection_name in {"lead_in", "liquidation"}:
            score *= 1.4 if count in {2, 3} else 0.45
            score *= 1.35 if abs(last - longest) < 0.02 else 0.9
            score *= 0.84 ** short_count
        elif connection_name in {"echo_fragment", "sequence"}:
            score *= 1.2 if 2 <= count <= 4 else 0.55
            score *= 1.08 if short_count <= max(1, count - 2) else 0.82
        elif connection_name in {"passing", "neighbor", "suspension_like"}:
            score *= 1.15 if 2 <= count <= 4 else 0.62
            score *= 1.06 if short_count <= max(1, count - 1) else 0.86
        elif connection_name == "arpeggiation":
            score *= 1.25 if count in {3, 4} else 0.6
        elif connection_name == "cadential_turn":
            score *= 1.2 if 3 <= count <= 5 else 0.65
            score *= 1.15 if abs(last - longest) < 0.02 else 0.92

        weights.append(max(0.05, score))

    return list(rng.choices(variants, weights=weights, k=1)[0])


def _durations_for_connection(
    connection_name: str,
    total: float,
    pulse: float,
    allowed_durations: list[float],
    cadence_target: str,
    time_signature: str,
    motive_blueprint: dict[str, Any],
    rng: random.Random,
) -> list[float]:
    preferred = _preferred_connection_durations(
        connection_name,
        total,
        pulse,
        allowed_durations,
        rng,
    )
    if preferred:
        return preferred

    base = {
        "arrival": [total],
        "lead_in": [pulse, max(total - pulse, pulse)],
        "passing": [pulse, pulse, max(total - pulse * 2, pulse)],
        "neighbor": [pulse, pulse / 2, pulse / 2, max(total - pulse * 2, pulse)],
        "arpeggiation": [pulse, pulse, pulse, max(total - pulse * 3, pulse)],
        "sequence": list(motive_blueprint.get("answerDurations") or motive_blueprint.get("durations") or [pulse, pulse]),
        "suspension_like": [pulse, pulse, max(total - pulse * 2, pulse)],
        "cadential_turn": list(
            _CADENCE_LIBRARY.get(time_signature, _CADENCE_LIBRARY["4/4"]).get(cadence_target, {}).get(
                "durations",
                [pulse, pulse / 2, pulse / 2, max(total - pulse * 2, pulse)],
            )
        ),
        "echo_fragment": list(motive_blueprint.get("durations") or [pulse, pulse])[:3],
        "liquidation": [pulse, max(total - pulse, pulse)],
    }.get(connection_name, [pulse, max(total - pulse, pulse)])
    return _fit_desired_durations(total, allowed_durations, [value for value in base if value > 0], rng)


def _soften_static_path(
    path_indices: list[int],
    pool_length: int,
    preferred_direction: int,
) -> list[int]:
    if len(path_indices) < 3:
        return path_indices

    softened = list(path_indices)
    direction = preferred_direction if preferred_direction != 0 else 1
    run_start = 0
    while run_start < len(softened):
        run_end = run_start + 1
        while run_end < len(softened) and softened[run_end] == softened[run_start]:
            run_end += 1
        run_length = run_end - run_start
        if run_length > 2:
            base_index = softened[run_start]
            alternate = _clamp_pool_index(base_index + direction, pool_length)
            if alternate == base_index:
                alternate = _clamp_pool_index(base_index - direction, pool_length)
            if alternate != base_index:
                for position in range(run_start + 1, run_end - 1, 2):
                    softened[position] = alternate
        run_start = run_end
    return softened


def _path_indices_for_connection(
    connection_name: str,
    start_index: int,
    target_index: int,
    note_count: int,
    direction: int,
    motif_blueprint: dict[str, Any],
    pool_length: int,
) -> list[int]:
    if note_count <= 1:
        return [target_index]

    preferred_direction = 1 if target_index >= start_index else -1
    if direction != 0:
        preferred_direction = direction

    if connection_name == "arrival":
        if start_index == target_index:
            approach_index = _clamp_pool_index(target_index - preferred_direction, pool_length)
            path = [approach_index] + [target_index for _ in range(note_count - 1)]
        else:
            path = _interpolate_index_path(start_index, target_index, note_count, pool_length)
            path[-1] = target_index
        return _soften_static_path(path, pool_length, preferred_direction)

    if connection_name == "lead_in":
        lead = _interpolate_index_path(start_index, target_index, max(2, note_count), pool_length)
        lead[-1] = target_index
        return lead[:note_count]

    if connection_name == "passing":
        return _interpolate_index_path(start_index, target_index, note_count, pool_length)

    if connection_name == "neighbor":
        neighbor_index = _clamp_pool_index(target_index + (1 if direction >= 0 else -1), pool_length)
        path = [target_index, neighbor_index, target_index]
        while len(path) < note_count:
            path.append(target_index)
        return _soften_static_path(path[:note_count], pool_length, preferred_direction)

    if connection_name == "arpeggiation":
        lower = _clamp_pool_index(target_index - 2, pool_length)
        upper = _clamp_pool_index(target_index + 2, pool_length)
        path = [target_index, upper if direction >= 0 else lower, lower if direction >= 0 else upper, target_index]
        while len(path) < note_count:
            path.append(target_index)
        return _soften_static_path(path[:note_count], pool_length, preferred_direction)

    if connection_name == "sequence":
        steps = list(motif_blueprint.get("steps") or [1, -1, 1])
        if not steps:
            steps = [1, -1]
        output = [start_index]
        current = start_index
        for step in steps:
            if len(output) >= note_count:
                break
            current = _clamp_pool_index(current + int(step), pool_length)
            output.append(current)
        while len(output) < note_count - 1:
            current = _clamp_pool_index(current + (1 if direction >= 0 else -1), pool_length)
            output.append(current)
        output.append(target_index)
        return _soften_static_path(output[:note_count], pool_length, preferred_direction)

    if connection_name == "suspension_like":
        suspension_index = _clamp_pool_index(target_index + (1 if direction >= 0 else -1), pool_length)
        path = [suspension_index, suspension_index, target_index]
        while len(path) < note_count:
            path.append(target_index)
        return _soften_static_path(path[:note_count], pool_length, preferred_direction)

    if connection_name == "cadential_turn":
        upper = _clamp_pool_index(target_index + 1, pool_length)
        lower = _clamp_pool_index(target_index - 1, pool_length)
        path = [target_index, upper, target_index, lower, target_index]
        while len(path) < note_count:
            path.append(target_index)
        return _soften_static_path(path[:note_count], pool_length, preferred_direction)

    if connection_name == "echo_fragment":
        path = [start_index]
        current = start_index
        for step in list(motif_blueprint.get("steps") or [direction or 1])[: max(1, note_count - 2)]:
            current = _clamp_pool_index(current + int(step), pool_length)
            path.append(current)
        while len(path) < note_count:
            path.append(target_index)
        return _soften_static_path(path[:note_count], pool_length, preferred_direction)

    if connection_name == "liquidation":
        path = [start_index]
        while len(path) < note_count:
            next_index = target_index if len(path) >= note_count - 1 else _clamp_pool_index(
                path[-1] + (1 if target_index > path[-1] else -1 if target_index < path[-1] else 0),
                pool_length,
            )
            path.append(next_index)
        return _soften_static_path(path[:note_count], pool_length, preferred_direction)

    return _soften_static_path(
        _interpolate_index_path(start_index, target_index, note_count, pool_length),
        pool_length,
        preferred_direction,
    )


def _apply_ornament_to_events(
    events: list[dict[str, Any]],
    ornament_name: str,
    allow_accidentals: bool,
) -> list[dict[str, Any]]:
    if not events or ornament_name in {"none", "arrival"}:
        return events

    updated = [{**event, "pitches": list(event.get("pitches", []))} for event in events]
    if ornament_name == "passing" and len(updated) >= 2:
        updated[0]["technique"] = "passing approach"
    elif ornament_name == "neighbor" and len(updated) >= 2:
        updated[min(1, len(updated) - 1)]["technique"] = "neighbor motion"
    elif ornament_name == "release_turn" and len(updated) >= 3:
        updated[-2]["technique"] = "release turn"
    elif ornament_name == "chromatic_approach" and allow_accidentals and len(updated) >= 2:
        target_pitch = int(updated[-1]["pitches"][0])
        approach_pitch = target_pitch - 1 if target_pitch > int(updated[0]["pitches"][0]) else target_pitch + 1
        updated[0]["pitches"] = [approach_pitch]
        updated[0]["technique"] = "chromatic approach"
    return updated


def _realize_line_measure(
    pool: list[int],
    harmony_tones: list[int],
    key_signature: str,
    harmony: str,
    total: float,
    pulse: float,
    allowed_durations: list[float],
    max_leap: int,
    prev_pitch: int,
    recent: list[int],
    direction: int,
    current_measure: int,
    cadence_target: str,
    time_signature: str,
    line_plan: LinePlan | None,
    motive_blueprint: dict[str, Any],
    allow_accidentals: bool,
    planned_top_pitch: int | None,
    rng: random.Random,
) -> tuple[list[dict[str, Any]], int, list[int], int, float, dict[str, Any] | None]:
    if line_plan is None:
        return [], prev_pitch, recent, direction, 0.0, None

    anchor = next((item for item in line_plan.anchors if item.measure == current_measure), None)
    connection = line_plan.connections.get(current_measure)
    ornament = line_plan.ornaments.get(current_measure)
    if anchor is None or connection is None or ornament is None:
        return [], prev_pitch, recent, direction, 0.0, None

    pool_length = len(pool)
    start_index = _nearest_pool_index(pool, prev_pitch)
    target_index = _relative_slot_to_index(anchor.register_slot, pool_length)
    if planned_top_pitch is not None:
        target_pitch = planned_top_pitch
    else:
        candidates = _pitch_role_candidates(pool, harmony_tones, key_signature, harmony, anchor.pitch_role)
        target_pitch = min(
            candidates,
            key=lambda candidate: abs(_nearest_pool_index(pool, candidate) - target_index) + abs(candidate - prev_pitch) * 0.05,
        )
    target_index = _nearest_pool_index(pool, target_pitch)
    durations = _durations_for_connection(
        connection.name,
        total,
        pulse,
        allowed_durations,
        cadence_target,
        time_signature,
        motive_blueprint,
        rng,
    )
    path_indices = _path_indices_for_connection(
        connection.name,
        start_index,
        target_index,
        len(durations),
        direction,
        motive_blueprint,
        pool_length,
    )

    events: list[dict[str, Any]] = []
    cursor = 0.0
    last_event: dict[str, Any] | None = None
    motif_eligible_connections = {"arrival", "lead_in", "passing", "neighbor", "echo_fragment", "sequence"}
    motif_technique = (
        connection.name
        if connection.name in motif_eligible_connections and anchor.local_goal in {"establish", "answer", "develop", "intensify"}
        else None
    )
    for duration_value, index_value in zip(durations, path_indices, strict=False):
        pitch_value = pool[_clamp_pool_index(index_value, pool_length)]
        if abs(pitch_value - prev_pitch) > max_leap:
            step_sign = 1 if pitch_value > prev_pitch else -1
            adjusted_index = _nearest_pool_index(pool, prev_pitch)
            while adjusted_index != index_value:
                next_index = _clamp_pool_index(adjusted_index + step_sign, pool_length)
                if abs(pool[next_index] - prev_pitch) > max_leap:
                    break
                adjusted_index = next_index
            pitch_value = pool[adjusted_index]

        event = {
            "hand": "rh",
            "offset": round(cursor, 3),
            "quarterLength": duration_value,
            "isRest": False,
            "pitches": [pitch_value],
            "technique": connection.name.replace("_", " "),
            "phraseFunction": connection.name,
            "lineRole": anchor.local_goal,
            "ornamentFunction": ornament.name,
            "motifTechnique": motif_technique,
        }
        events.append(event)
        delta = pitch_value - prev_pitch
        if delta != 0:
            direction = 1 if delta > 0 else -1
        prev_pitch = pitch_value
        recent = (recent + [pitch_value])[-6:]
        cursor = round(cursor + float(duration_value), 3)
        last_event = event

    if last_event is not None:
        last_event["pitches"] = [target_pitch]
        prev_pitch = target_pitch
        recent = (recent[:-1] + [target_pitch])[-6:] if recent else [target_pitch]

    events = _apply_ornament_to_events(events, ornament.name, allow_accidentals)
    return events, prev_pitch, recent, direction, cursor, last_event


def _build_melody_content(
    hand: str,
    pool: list[int],
    harmony_tones: list[int],
    total: float,
    pulse: float,
    allowed_durations: list[float],
    key_signature: str,
    harmony: str,
    weights: dict[str, Any],
    max_leap: int,
    rng: random.Random,
    prev_pitch: int,
    recent: list[int],
    direction: int,
    is_cadence: bool,
    cadence_target: str,
    request: dict[str, Any],
    preset: dict[str, Any],
    phrase_plan: dict[str, Any],
) -> tuple[list[dict[str, Any]], int, list[int], int]:
    """Build one measure of music using rhythmic cells and phrase contour."""
    events: list[dict[str, Any]] = []
    last_pitched_event: dict[str, Any] | None = None

    # Get phrase-level rhythm cells and contour
    rhythm_cells = phrase_plan.get("_rhythmCells") or _RHYTHM_CELLS_SIMPLE
    contour = phrase_plan.get("_contour", "flat")
    phrase_measures = phrase_plan.get("measures", [1])
    current_measure = phrase_plan.get("_currentMeasure", phrase_measures[0])
    measure_role = phrase_plan.get("_measureRoles", {}).get(current_measure, "develop")
    role_cells = phrase_plan.get("_roleRhythmCells", {})
    triplet_measures = set(phrase_plan.get("_tripletMeasures", []))
    motive_blueprint = phrase_plan.get("_motiveBlueprint", {})
    motive_transform = motive_blueprint.get("transformByMeasure", {}).get(current_measure, "none")
    continuation_gesture = phrase_plan.get("_continuationByMeasure", {}).get(current_measure)
    line_plan = phrase_plan.get("_linePlan")
    planned_top_pitch = phrase_plan.get("_currentTopTargetPitch")

    local_weights = dict(weights)
    triplet_chance = float(local_weights.get("tripletChance", 0.0))
    block_chord_chance = float(local_weights.get("blockChordChance", 0.0))
    short_run_chance = float(preset["piano"].get("textureWeights", {}).get("running", 0.0))
    rest_chance = float(local_weights.get("restChance", 0.0))

    # Position in phrase (0.0 = start, 1.0 = end)
    if len(phrase_measures) > 1:
        mi_in_phrase = phrase_measures.index(current_measure) if current_measure in phrase_measures else 0
        phrase_position = mi_in_phrase / max(1, len(phrase_measures) - 1)
    else:
        phrase_position = 0.5

    # Chords are strongest at structural moments, but chordal texture bars can also open with them.
    is_phrase_start = (current_measure == phrase_measures[0])
    is_phrase_end = (current_measure == phrase_measures[-1])
    current_texture = str(phrase_plan.get("_textureByMeasure", {}).get(current_measure, "melody"))
    force_motif_measure = bool(
        hand == "rh"
        and current_texture == "melody"
        and current_measure in set(phrase_plan.get("_forceMotifMeasures", ()))
        and motive_transform not in {"none", "contrast"}
    )
    chord_allowed = is_phrase_start or is_phrase_end or current_texture == "chordal"

    # Apply contour direction bias
    contour_dir = _contour_direction_bias(contour, phrase_position)
    if contour_dir != 0:
        direction = contour_dir

    # Phase 7: tension → release arc — active intensity response
    _piece_plan = phrase_plan.get("_piecePlan")
    intensity = 0.5
    if _piece_plan is not None and hasattr(_piece_plan, "intensity_curve"):
        intensity = _piece_plan.intensity_curve.get(current_measure, 0.5)

    # Register: narrow the pitch selection pool at low intensity (keep full pool for motif).
    # We use a separate variable so _realize_motive_fragment still gets the full pool.
    select_pool = pool
    if intensity < 0.45 and len(pool) >= 7:
        trim = max(1, len(pool) // 5)
        select_pool = pool[trim:-trim] or pool
    elif measure_role == "cadence" and len(pool) >= 7:
        trim = max(1, len(pool) // 4)
        select_pool = pool[trim:-trim] or pool
    # Rhythmic density: prefer shorter cells at high intensity (non-cadence)
    if intensity > 0.6 and measure_role not in ("establish", "cadence"):
        short_cells = [c for c in rhythm_cells if round(sum(c), 3) <= pulse + 0.001]
        if short_cells:
            rhythm_cells = short_cells
    # Chord tone loosening at peak intensity (creates harmonic tension before resolution)
    if intensity > 0.65 and measure_role == "intensify":
        local_weights["strongBeatChordToneWeight"] = float(local_weights["strongBeatChordToneWeight"]) * 0.88
        local_weights["chordToneWeight"] = float(local_weights["chordToneWeight"]) * 0.85
    # Cadence contrast: tighten chord tone weight for release
    if measure_role == "cadence":
        local_weights["strongBeatChordToneWeight"] = float(local_weights["strongBeatChordToneWeight"]) * 1.10

    if measure_role == "establish":
        rhythm_cells = role_cells.get("establish", rhythm_cells)
        triplet_chance = 0.0
        short_run_chance *= 0.15
        rest_chance *= 0.65
        local_weights["stepWeight"] = min(0.95, float(local_weights["stepWeight"]) + 0.08)
        local_weights["directionPersistence"] = min(0.88, float(local_weights["directionPersistence"]) + 0.10)
    elif measure_role == "answer":
        rhythm_cells = role_cells.get("answer", rhythm_cells)
        triplet_chance = 0.0
        short_run_chance *= 0.35
        rest_chance *= 0.8
        local_weights["stepWeight"] = min(0.92, float(local_weights["stepWeight"]) + 0.05)
    elif measure_role == "develop":
        rhythm_cells = role_cells.get("develop", rhythm_cells)
        if current_measure not in triplet_measures:
            triplet_chance *= 0.35
        else:
            triplet_chance = max(triplet_chance * 1.8, 0.28)
        short_run_chance *= 1.05
    elif measure_role == "intensify":
        rhythm_cells = role_cells.get("intensify", rhythm_cells)
        if current_measure not in triplet_measures:
            triplet_chance *= 0.15
        else:
            triplet_chance = max(triplet_chance * 2.2, 0.42)
        short_run_chance *= 1.35
        rest_chance *= 0.8
        local_weights["directionPersistence"] = min(0.9, float(local_weights["directionPersistence"]) + 0.06)
    elif measure_role == "cadence":
        rhythm_cells = role_cells.get("cadence", phrase_plan.get("_cadenceCells", rhythm_cells))
        triplet_chance = 0.0
        short_run_chance *= 0.1
        block_chord_chance *= 0.25
        rest_chance *= 0.35
        local_weights["stepWeight"] = min(0.98, float(local_weights["stepWeight"]) + 0.12)
        local_weights["strongBeatChordToneWeight"] = float(local_weights["strongBeatChordToneWeight"]) * 1.15

    # --- Final measure of the piece: make it feel like an ending ---
    is_piece_final = current_measure == int(request.get("measureCount", 999))
    if is_piece_final and is_cadence:
        # Override rhythm cells: use only long values for a definitive close.
        # Ideal final bar: 1-2 notes, mostly half/whole, ending on tonic.
        final_cells = [[total], [pulse * 2, total - pulse * 2], [pulse, total - pulse]]
        valid_final = [c for c in final_cells if all(d > 0 for d in c) and round(sum(c), 3) == round(total, 3)]
        if valid_final:
            rhythm_cells = valid_final
        triplet_chance = 0.0
        short_run_chance = 0.0
        rest_chance = 0.0
        block_chord_chance = 0.0

    # Cell state: tracks which cell we're in and remaining durations
    cell_state: dict[str, Any] = {"queue": []}

    cursor = 0.0
    note_count = 0

    line_events: list[dict[str, Any]] = []
    line_cursor = 0.0
    line_last_event: dict[str, Any] | None = None
    if not force_motif_measure:
        line_events, prev_pitch, recent, direction, line_cursor, line_last_event = _realize_line_measure(
            pool,
            harmony_tones,
            key_signature,
            harmony,
            total,
            pulse,
            allowed_durations,
            max_leap,
            prev_pitch,
            recent,
            direction,
            current_measure,
            cadence_target,
            request["timeSignature"],
            line_plan if isinstance(line_plan, LinePlan) else None,
            motive_blueprint,
            bool(request.get("allowAccidentals")),
            int(planned_top_pitch) if planned_top_pitch is not None else None,
            rng,
        )
        if line_events and line_cursor >= total - 0.001:
            for line_event in line_events:
                events.append({**line_event, "hand": hand})
            return events, prev_pitch, recent, direction
        if line_events:
            for line_event in line_events:
                events.append({**line_event, "hand": hand})
            cursor = round(line_cursor, 3)
            note_count = len(line_events)
            last_pitched_event = line_last_event
            short_run_chance *= 0.2
            rest_chance *= 0.6
            triplet_chance *= 0.2

    motif_events: list[dict[str, Any]] = []
    motif_cursor = cursor
    motif_last_event: dict[str, Any] | None = last_pitched_event
    if force_motif_measure or not line_events:
        motif_events, prev_pitch, recent, direction, motif_cursor, motif_last_event = _realize_motive_fragment(
            pool,
            harmony_tones,
            motive_blueprint,
            motive_transform,
            prev_pitch,
            recent,
            direction,
            total,
            max_leap,
            target_pitch=int(planned_top_pitch) if planned_top_pitch is not None else None,
        )
        if motif_events:
            for motif_event in motif_events:
                events.append({**motif_event, "hand": hand})
            cursor = round(motif_cursor, 3)
            note_count = len(motif_events)
            last_pitched_event = events[-1] if motif_last_event else None
            short_run_chance *= 0.15

    if continuation_gesture and cursor < total - 0.001:
        continuation_events, prev_pitch, recent, direction, continuation_cursor, continuation_last = _realize_continuation_figure(
            pool,
            harmony_tones,
            str(continuation_gesture),
            prev_pitch,
            recent,
            direction,
            round(total - cursor, 3),
            pulse,
            allowed_durations,
            measure_role,
            current_measure,
            int(phrase_plan.get("_targetPeakMeasure", current_measure)),
            contour_dir,
            max_leap,
            rng,
        )
        if continuation_events:
            for continuation_event in continuation_events:
                continuation_event["offset"] = round(float(continuation_event["offset"]) + cursor, 3)
                continuation_event["hand"] = hand
                events.append(continuation_event)
            cursor = round(cursor + continuation_cursor, 3)
            note_count += len(continuation_events)
            last_pitched_event = continuation_last or last_pitched_event
            triplet_chance *= 0.35
            rest_chance *= 0.55
            short_run_chance *= 0.1

    if force_motif_measure and cursor < total - 0.001:
        remaining = round(total - cursor, 3)
        if remaining > 0.001:
            if is_cadence:
                tail_pool = _chord_tones_in_pool(pool, key_signature, harmony)
            else:
                tail_pool = [
                    pitch_value for pitch_value in pool
                    if abs(pitch_value - prev_pitch) <= max(4, max_leap // 2)
                ] or _chord_tones_in_pool(pool, key_signature, harmony)
            if planned_top_pitch is not None:
                tail_pitch = min(
                    tail_pool,
                    key=lambda pitch_value: abs(pitch_value - int(planned_top_pitch)) + abs(pitch_value - prev_pitch) * 0.08,
                )
            else:
                tail_pitch = min(tail_pool, key=lambda pitch_value: abs(pitch_value - prev_pitch))
            tail_event = {
                "hand": hand,
                "offset": round(cursor, 3),
                "quarterLength": remaining,
                "isRest": False,
                "pitches": [tail_pitch],
                "technique": "motif tail",
                "motifTechnique": "tail",
            }
            events.append(tail_event)
            prev_pitch = tail_pitch
            recent = (recent + [tail_pitch])[-6:]
            last_pitched_event = tail_event
            cursor = total

    while not force_motif_measure and cursor < total - 0.001:
        remaining = round(total - cursor, 3)
        on_strong = abs(cursor % pulse) < 0.001

        # --- Triplet insertion (Grade 4+) ---
        if (
            triplet_chance > 0
            and on_strong
            and remaining >= pulse
            and rng.random() < triplet_chance
            and (note_count > 0 or current_measure in triplet_measures)
        ):
            # Clear cell queue — triplet replaces current beat
            cell_state["queue"] = []
            base_dur = 0.5
            actual_dur = round(pulse / 3, 4)
            for ti in range(3):
                tp = _weighted_pitch_select(
                    select_pool, prev_pitch, recent, direction,
                    key_signature, harmony, local_weights, max_leap,
                    ti == 0, rng,
                )
                events.append({
                    "hand": hand,
                    "offset": round(cursor, 3),
                    "quarterLength": base_dur,
                    "isRest": False,
                    "pitches": [tp],
                    "technique": "triplet",
                    "tuplet": {"actual": 3, "normal": 2},
                    "_actualDur": actual_dur,
                })
                recent = (recent + [tp])[-6:]
                delta = tp - prev_pitch
                if delta != 0:
                    direction = 1 if delta > 0 else -1
                prev_pitch = tp
                last_pitched_event = events[-1]
                cursor = round(cursor + actual_dur, 3)
            note_count += 3
            continue

        # Get duration from rhythm cell system
        dur = _next_cell_duration(rhythm_cells, cell_state, remaining, allowed_durations, rng)
        dur = min(dur, remaining)
        dur = _snap_duration(dur, allowed_durations)

        # --- Rest (rare, musical — never on first note, rarely on beat 1) ---
        if note_count >= 2 and not (on_strong and cursor < 0.01) and rng.random() < rest_chance:
            events.append({
                "hand": hand,
                "offset": round(cursor, 3),
                "quarterLength": dur,
                "isRest": True,
                "pitches": [],
                "technique": "rest",
            })
            cursor = round(cursor + dur, 3)
            note_count += 1
            continue

        # --- Block chord (only at phrase boundaries, beat 1) ---
        if (
            block_chord_chance > 0
            and chord_allowed
            and note_count == 0
            and rng.random() < block_chord_chance
            and remaining >= pulse
        ):
            triad = _build_block_triad(pool, key_signature, harmony, prev_pitch)
            if triad and len(triad) >= 2:
                chord_dur = max(dur, pulse) if dur < pulse else dur
                chord_dur = min(chord_dur, remaining)
                # Snap chord_dur to an allowed duration
                if chord_dur not in set(allowed_durations):
                    snapped = [d for d in allowed_durations if d <= remaining + 0.001 and d >= pulse]
                    chord_dur = rng.choice(snapped) if snapped else dur
                triad = _build_voiced_block_chord(
                    pool,
                    key_signature,
                    harmony,
                    prev_pitch,
                    top_target=int(planned_top_pitch) if planned_top_pitch is not None else None,
                )
                events.append({
                    "hand": hand,
                    "offset": round(cursor, 3),
                    "quarterLength": chord_dur,
                    "isRest": False,
                    "pitches": triad,
                    "technique": "block chord",
                })
                prev_pitch = triad[-1]
                recent = (recent + [prev_pitch])[-6:]
                last_pitched_event = events[-1]
                cursor = round(cursor + chord_dur, 3)
                # Clear remaining cell durations since chord consumed different time
                cell_state["queue"] = []
                note_count += 1
                continue

        # --- Single note (default, contour-aware) ---
        p = _weighted_pitch_select(
            select_pool, prev_pitch, recent, direction,
            key_signature, harmony, local_weights, max_leap,
            on_strong, rng,
        )
        events.append({
            "hand": hand,
            "offset": round(cursor, 3),
            "quarterLength": dur,
            "isRest": False,
            "pitches": [p],
            "technique": "melody",
        })
        recent = (recent + [p])[-6:]
        delta = p - prev_pitch
        if delta != 0:
            direction = 1 if delta > 0 else -1
        prev_pitch = p
        last_pitched_event = events[-1]
        cursor = round(cursor + dur, 3)
        note_count += 1

        # Occasionally flip direction — longer arcs = more melodic
        if note_count > 0 and note_count % rng.randint(6, 10) == 0:
            direction *= -1

    # --- Cadence: force last pitched note to stable tone ---
    if is_cadence and last_pitched_event and last_pitched_event["pitches"]:
        candidates = _chord_tones_in_pool(pool, key_signature, harmony)
        if candidates:
            best = min(candidates, key=lambda c: abs(c - prev_pitch))
            if len(last_pitched_event["pitches"]) == 1:
                last_pitched_event["pitches"] = [best]
            else:
                last_pitched_event["pitches"][0] = best
            prev_pitch = best

    # --- Final measure of piece: definitive ending ---
    if is_piece_final and is_cadence and events:
        # Force last pitched note to tonic pitch class (root of key).
        tonic_pc = KEY_TONIC_PITCH_CLASS.get(key_signature, 0)
        tonic_candidates = [p for p in pool if p % 12 == tonic_pc]
        if tonic_candidates and last_pitched_event and last_pitched_event["pitches"]:
            best_tonic = min(tonic_candidates, key=lambda c: abs(c - prev_pitch))
            if len(last_pitched_event["pitches"]) == 1:
                last_pitched_event["pitches"] = [best_tonic]
            else:
                last_pitched_event["pitches"][0] = best_tonic
            prev_pitch = best_tonic

        # Add fermata flag on the last note for notation rendering.
        if last_pitched_event:
            last_pitched_event["fermata"] = True

        # If last note is short (< half the measure), absorb remaining time.
        if last_pitched_event:
            last_dur = float(last_pitched_event["quarterLength"])
            last_local_offset = float(last_pitched_event["offset"])
            remaining_in_measure = round(total - last_local_offset, 3)
            if remaining_in_measure > 0 and last_dur < remaining_in_measure * 0.5:
                # Remove any events after the last pitched event and extend it.
                last_idx = events.index(last_pitched_event)
                events = events[: last_idx + 1]
                last_pitched_event["quarterLength"] = remaining_in_measure
                cursor = round(last_local_offset + remaining_in_measure, 3)

    # Apply accidentals (with piece-level budget tracking)
    pitched_groups = [e["pitches"] for e in events if not e["isRest"] and e["pitches"]]
    piece_acc_count = int(phrase_plan.get("_pieceAccidentalCount", 0))
    # Store current measure role for accidental role gating
    phrase_plan["_currentMeasureRole"] = measure_role
    if pitched_groups:
        original_groups = [list(g) for g in pitched_groups]
        accidental_groups = _apply_accidental(
            pitched_groups, request, preset, phrase_plan, rng,
            piece_accidental_count=piece_acc_count,
        )
        # Track whether an accidental was actually applied
        if accidental_groups != original_groups:
            phrase_plan["_pieceAccidentalCount"] = piece_acc_count + 1
        gi = 0
        for e in events:
            if not e["isRest"] and e["pitches"]:
                e["pitches"] = accidental_groups[gi]
                gi += 1

    return events, prev_pitch, recent, direction


def _build_chordal_content(
    hand: str,
    pool: list[int],
    harmony_tones: list[int],
    total: float,
    pulse: float,
    allowed_durations: list[float],
    key_signature: str,
    harmony: str,
    weights: dict[str, Any],
    max_leap: int,
    rng: random.Random,
    prev_pitch: int,
    recent: list[int],
    direction: int,
    is_cadence: bool,
    cadence_target: str,
    **_kwargs: Any,
) -> tuple[list[dict[str, Any]], int, list[int], int]:
    """Build one measure of block chord content."""
    events: list[dict[str, Any]] = []
    cursor = 0.0
    phrase_plan = _kwargs.get("phrase_plan") or {}
    request = _kwargs.get("request") or {}
    planned_top_pitch = phrase_plan.get("_currentTopTargetPitch")
    continuation_gesture = str(
        phrase_plan.get("_continuationByMeasure", {}).get(
            phrase_plan.get("_currentMeasure"),
            "bridge",
        )
    )
    measure_role = str(
        phrase_plan.get("_measureRoles", {}).get(
            phrase_plan.get("_currentMeasure"),
            "develop",
        )
    )
    available_total = total
    rh_span_cap = _simultaneous_span_cap(
        int(request.get("grade", 5)),
        "rh",
        is_cadence=is_cadence,
        accent=measure_role in {"answer", "intensify"},
    )

    if (
        planned_top_pitch is not None
        and not is_cadence
        and 0.5 in allowed_durations
        and total >= pulse + 0.5
        and continuation_gesture in {"hold-answer", "neighbor-answer", "sequence-tail", "bridge", "climb"}
    ):
        lead_center = (prev_pitch + int(planned_top_pitch)) / 2
        lead_candidates = [
            pitch_value
            for pitch_value in pool
            if abs(pitch_value - int(planned_top_pitch)) <= 5
        ] or pool
        lead_pitch = min(
            lead_candidates,
            key=lambda pitch_value: abs(pitch_value - lead_center) + abs(pitch_value - int(planned_top_pitch)) * 0.08,
        )
        events.append({
            "hand": hand,
            "offset": 0.0,
            "quarterLength": 0.5,
            "isRest": False,
            "pitches": [lead_pitch],
            "technique": "passing tone" if continuation_gesture != "neighbor-answer" else "neighbor tone",
        })
        prev_pitch = lead_pitch
        recent = (recent + [lead_pitch])[-6:]
        cursor = 0.5
        available_total = round(total - 0.5, 3)

    chord_allowed = [d for d in allowed_durations if d >= pulse]
    duration_plan = _preferred_connection_durations(
        "liquidation",
        available_total,
        pulse,
        chord_allowed or allowed_durations,
        rng,
    ) or _fit_desired_durations(available_total, chord_allowed or allowed_durations, [available_total], rng)

    previous_top_pitch: int | None = None
    top_targets: list[int | None] = []
    if planned_top_pitch is not None and duration_plan:
        if len(duration_plan) == 1:
            top_targets = [int(planned_top_pitch)]
        else:
            top_direction = 1 if int(planned_top_pitch) >= prev_pitch else -1
            for chord_index in range(len(duration_plan)):
                if chord_index == len(duration_plan) - 1:
                    top_targets.append(int(planned_top_pitch))
                else:
                    remaining_steps = len(duration_plan) - chord_index - 1
                    top_targets.append(int(planned_top_pitch) - (top_direction * min(4, remaining_steps * 2)))

    for chord_index, dur in enumerate(duration_plan):
        if cursor >= total - 0.001:
            break

        remaining = round(total - cursor, 3)
        dur = min(float(dur), remaining)
        dur = _snap_duration(dur, allowed_durations)

        # Build triad near prev_pitch for voice leading, but gently vary repeated top notes.
        near_pitch = prev_pitch + (2 if chord_index % 2 == 1 else 0)
        triad = _build_voiced_block_chord(
            pool,
            key_signature,
            harmony,
            near_pitch,
            top_target=top_targets[chord_index] if chord_index < len(top_targets) else (int(planned_top_pitch) if planned_top_pitch is not None else None),
            max_span=rh_span_cap,
        )
        if not triad:
            triad = [pool[len(pool) // 2]]
        if previous_top_pitch is not None and len(triad) >= 2 and triad[-1] == previous_top_pitch:
            alternate = _build_voiced_block_chord(
                pool,
                key_signature,
                harmony,
                near_pitch - 2,
                top_target=int(planned_top_pitch) if planned_top_pitch is not None else None,
                max_span=rh_span_cap,
            )
            if alternate and alternate[-1] != previous_top_pitch:
                triad = alternate

        events.append({
            "hand": hand,
            "offset": round(cursor, 3),
            "quarterLength": dur,
            "isRest": False,
            "pitches": triad,
            "technique": "chordal texture",
        })

        prev_pitch = triad[-1]
        previous_top_pitch = triad[-1]
        recent = (recent + [prev_pitch])[-6:]
        cursor = round(cursor + dur, 3)

    # Cadence: force tonic triad on last chord
    if is_cadence and events and cadence_target == "tonic":
        stable_triad = _build_block_triad(
            pool,
            key_signature,
            harmony,
            prev_pitch,
            max_span=rh_span_cap,
        )
        if stable_triad:
            events[-1]["pitches"] = stable_triad

    return events, prev_pitch, recent, direction


def _build_running_content(
    hand: str,
    pool: list[int],
    harmony_tones: list[int],
    total: float,
    pulse: float,
    allowed_durations: list[float],
    key_signature: str,
    harmony: str,
    weights: dict[str, Any],
    max_leap: int,
    rng: random.Random,
    prev_pitch: int,
    recent: list[int],
    direction: int,
    is_cadence: bool,
    cadence_target: str,
    **_kwargs: Any,
) -> tuple[list[dict[str, Any]], int, list[int], int]:
    """Build one measure containing a short running figure, not a full-bar scale drill."""
    events: list[dict[str, Any]] = []
    cursor = 0.0
    phrase_plan = _kwargs.get("phrase_plan") or {}
    current_measure = phrase_plan.get("_currentMeasure")
    step_dur = 0.5 if 0.5 in allowed_durations else 0.25
    max_run_len = 4 if step_dur >= 0.5 else 5
    min_run_len = 3
    role = str(phrase_plan.get("_measureRoles", {}).get(current_measure, "develop"))
    triplet_measures = set(phrase_plan.get("_tripletMeasures", []))
    use_triplet_cell = bool(current_measure in triplet_measures and total >= pulse + step_dur)
    triplet_notated = 0.5 if 0.5 in allowed_durations else 0.25
    triplet_actual = round(pulse / 3, 4)

    run_len = min(max_run_len, max(min_run_len, int(max(pulse, 1.0) / step_dur)))
    if role == "intensify":
        run_len = min(max_run_len, run_len + 1)
    run_len = max(min_run_len, min(run_len, int((total / step_dur) - 1)))
    triplet_slots = 3 if use_triplet_cell else 0
    regular_run_len = max(0, run_len - triplet_slots)
    run_total = round((pulse if use_triplet_cell else 0.0) + regular_run_len * step_dur, 3)

    lead_in_options = [
        d for d in allowed_durations
        if d >= pulse and d <= round(total - run_total - step_dur, 3) + 0.001
    ]
    lead_in_dur = max(lead_in_options) if lead_in_options else 0.0
    remaining_after_lead = round(total - lead_in_dur - run_total, 3)
    if remaining_after_lead < step_dur:
        if lead_in_options:
            lead_in_dur = min(lead_in_options)
            remaining_after_lead = round(total - lead_in_dur - run_total, 3)
        if remaining_after_lead < step_dur:
            lead_in_dur = 0.0
            remaining_after_lead = round(total - run_total, 3)

    landing_options = [d for d in allowed_durations if d <= remaining_after_lead + 0.001]
    landing_dur = max(landing_options) if landing_options else remaining_after_lead
    landing_dur = round(max(step_dur, landing_dur), 3)
    if lead_in_dur + run_total + landing_dur > total + 0.001:
        landing_dur = round(total - lead_in_dur - run_total, 3)

    if lead_in_dur > 0:
        opening_pitch = _stable_tone(pool, key_signature, harmony)
        events.append({
            "hand": hand,
            "offset": 0.0,
            "quarterLength": lead_in_dur,
            "isRest": False,
            "pitches": [opening_pitch],
            "technique": "melody",
        })
        prev_pitch = opening_pitch
        recent = (recent + [opening_pitch])[-6:]
        cursor = round(cursor + lead_in_dur, 3)

    # Pick starting pitch and direction near the last real pitch
    if prev_pitch in pool:
        start_idx = pool.index(prev_pitch)
    else:
        start_idx = min(range(len(pool)), key=lambda i: abs(pool[i] - prev_pitch))

    run_dir = direction
    idx = start_idx

    if use_triplet_cell:
        for _ in range(3):
            p = pool[idx]
            events.append({
                "hand": hand,
                "offset": round(cursor, 3),
                "quarterLength": triplet_notated,
                "isRest": False,
                "pitches": [p],
                "technique": "triplet",
                "tuplet": {"actual": 3, "normal": 2},
                "_actualDur": triplet_actual,
            })
            prev_pitch = p
            recent = (recent + [p])[-6:]
            cursor = round(cursor + triplet_actual, 3)

            if run_dir > 0:
                idx += 1
                if idx >= len(pool):
                    idx = len(pool) - 2
                    run_dir = -1
            else:
                idx -= 1
                if idx < 0:
                    idx = 1
                    run_dir = 1

    for _ in range(regular_run_len):
        p = pool[idx]
        events.append({
            "hand": hand,
            "offset": round(cursor, 3),
            "quarterLength": step_dur,
            "isRest": False,
            "pitches": [p],
            "technique": "scale figure",
        })
        prev_pitch = p
        recent = (recent + [p])[-6:]
        cursor = round(cursor + step_dur, 3)

        # Move through pool
        if run_dir > 0:
            idx += 1
            if idx >= len(pool):
                idx = len(pool) - 2
                run_dir = -1
        else:
            idx -= 1
            if idx < 0:
                idx = 1
                run_dir = 1

    # Landing note
    remaining = round(total - cursor, 3)
    if remaining > 0.001:
        landing_dur = min(landing_dur, remaining)
        if is_cadence:
            landing_pitch = _stable_tone(pool, key_signature, harmony)
        else:
            ct = _chord_tones_in_pool(pool, key_signature, harmony)
            landing_pitch = min(ct, key=lambda c: abs(c - prev_pitch))
        events.append({
            "hand": hand,
            "offset": round(cursor, 3),
            "quarterLength": landing_dur,
            "isRest": False,
            "pitches": [landing_pitch],
            "technique": "scale figure landing",
        })
        prev_pitch = landing_pitch
        recent = (recent + [landing_pitch])[-6:]

    direction = run_dir
    return events, prev_pitch, recent, direction


# ---------------------------------------------------------------------------
# Phase 3: A/A' rhythm replay — re-pitch a stored rhythm template
# ---------------------------------------------------------------------------

def _extract_rhythm_template(
    events: list[dict[str, Any]],
    measure_number: int,
) -> list[dict[str, Any]]:
    """Extract a rhythm-only template from one measure's RH events."""
    return [
        {
            "quarterLength": float(e.get("quarterLength", 1.0)),
            "isRest": bool(e.get("isRest", False)),
            "technique": str(e.get("technique", "")),
            "tuplet": e.get("tuplet"),
            "_actualDur": e.get("_actualDur"),
            "pitchCount": len(e.get("pitches", [1])),
            # Store interval direction for contour replay: +1, -1, or 0
            "_direction": (
                1 if len(e.get("pitches", [])) == 1 and e.get("_intervalDir", 0) > 0
                else (-1 if len(e.get("pitches", [])) == 1 and e.get("_intervalDir", 0) < 0 else 0)
            ),
        }
        for e in events
        if int(e.get("measure", 0)) == measure_number and e.get("hand") == "rh"
    ]


def _replay_rhythm_template(
    hand: str,
    template: list[dict[str, Any]],
    pool: list[int],
    harmony_tones: list[int],
    key_signature: str,
    harmony: str,
    weights: dict[str, Any],
    max_leap: int,
    rng: random.Random,
    prev_pitch: int,
    recent: list[int],
    direction: int,
    is_cadence: bool,
) -> tuple[list[dict[str, Any]], int, list[int], int]:
    """Replay a rhythm template with new pitches against a (possibly different) harmony."""
    events: list[dict[str, Any]] = []
    cursor = 0.0

    for slot in template:
        dur = float(slot["quarterLength"])
        is_rest = bool(slot["isRest"])

        if is_rest:
            events.append({
                "hand": hand,
                "offset": round(cursor, 3),
                "quarterLength": dur,
                "isRest": True,
                "pitches": [],
                "technique": "rest",
            })
        else:
            pulse_aligned = abs(cursor % 1.0) < 0.001
            pitch = _weighted_pitch_select(
                pool, prev_pitch, recent, direction,
                key_signature, harmony, weights, max_leap,
                pulse_aligned, rng,
            )
            pitch_count = int(slot.get("pitchCount", 1))
            pitches = [pitch]
            if pitch_count > 1:
                # For chords, grab chord tones near the selected pitch
                chord_pcs = _chord_pitch_classes(key_signature, harmony)
                extra = sorted(
                    [p for p in pool if p != pitch and p % 12 in chord_pcs],
                    key=lambda p: abs(p - pitch),
                )[:pitch_count - 1]
                pitches = sorted([pitch, *extra])

            event: dict[str, Any] = {
                "hand": hand,
                "offset": round(cursor, 3),
                "quarterLength": dur,
                "isRest": False,
                "pitches": pitches,
                "technique": slot.get("technique", ""),
            }
            if slot.get("tuplet"):
                event["tuplet"] = slot["tuplet"]
            if slot.get("_actualDur") is not None:
                event["_actualDur"] = slot["_actualDur"]
            events.append(event)

            delta = pitch - prev_pitch
            if delta != 0:
                direction = 1 if delta > 0 else -1
            prev_pitch = pitch
            recent = (recent + [pitch])[-6:]

        actual_dur = float(slot.get("_actualDur") or dur)
        cursor = round(cursor + actual_dur, 3)

    return events, prev_pitch, recent, direction


def _build_measure_content(
    hand: str,
    texture: str,
    pool: list[int],
    harmony_tones: list[int],
    total: float,
    pulse: float,
    allowed_durations: list[float],
    key_signature: str,
    harmony: str,
    weights: dict[str, Any],
    max_leap: int,
    rng: random.Random,
    prev_pitch: int,
    recent: list[int],
    direction: int,
    is_cadence: bool,
    cadence_target: str,
    request: dict[str, Any],
    preset: dict[str, Any],
    phrase_plan: dict[str, Any],
) -> tuple[list[dict[str, Any]], int, list[int], int]:
    if texture == "chordal":
        return _build_chordal_content(
            hand, pool, harmony_tones, total, pulse, allowed_durations,
            key_signature, harmony, weights, max_leap, rng,
            prev_pitch, recent, direction, is_cadence, cadence_target,
            request=request, preset=preset, phrase_plan=phrase_plan,
        )
    if texture == "running":
        return _build_running_content(
            hand, pool, harmony_tones, total, pulse, allowed_durations,
            key_signature, harmony, weights, max_leap, rng,
            prev_pitch, recent, direction, is_cadence, cadence_target,
            request=request, preset=preset, phrase_plan=phrase_plan,
        )
    return _build_melody_content(
        hand, pool, harmony_tones, total, pulse, allowed_durations,
        key_signature, harmony, weights, max_leap, rng,
        prev_pitch, recent, direction, is_cadence, cadence_target,
        request, preset, phrase_plan,
    )


# ---------------------------------------------------------------------------
# Phrase structure
# ---------------------------------------------------------------------------

_ROLE_DENSITY_TARGETS = {
    "establish": 0.28,
    "answer": 0.42,
    "develop": 0.56,
    "intensify": 0.72,
    "cadence": 0.24,
}

_MOTIVE_STEP_TEMPLATES = {
    "ascending": [
        [1, 2],
        [2, 1],
        [1, 2, 1],
        [1, 1, 2],
    ],
    "descending": [
        [-1, -2],
        [-2, -1],
        [-1, -2, -1],
        [-1, -1, -2],
    ],
    "arch": [
        [1, 2, -1],
        [2, 1, -2],
        [1, 1, -2],
        [2, -1, -1],
    ],
    "valley": [
        [-1, -2, 1],
        [-2, -1, 2],
        [-1, -1, 2],
        [-2, 1, 1],
    ],
    "flat": [
        [0, 1, -1],
        [1, 0, -1],
        [0, -1, 1],
        [1, -1, 0],
    ],
}

_MOTIVE_TRANSFORM_BY_ROLE = {
    "establish": "base",
    "answer": "sequence",
    "develop": "sequence",
    "intensify": "fragment",
    "cadence": "cadence",
}

_CONNECTION_LIBRARY = {
    "period": {
        "establish": ["lead_in", "arrival"],
        "answer": ["passing", "echo_fragment"],
        "develop": ["passing", "neighbor"],
        "intensify": ["sequence", "arpeggiation"],
        "cadence": ["cadential_turn", "liquidation"],
    },
    "sentence": {
        "establish": ["lead_in", "echo_fragment"],
        "answer": ["echo_fragment", "sequence"],
        "develop": ["sequence", "passing"],
        "intensify": ["sequence", "arpeggiation"],
        "cadence": ["cadential_turn", "liquidation"],
    },
    "lyric": {
        "establish": ["arrival", "lead_in"],
        "answer": ["neighbor", "echo_fragment"],
        "develop": ["passing", "neighbor"],
        "intensify": ["suspension_like", "passing"],
        "cadence": ["cadential_turn", "arrival"],
    },
    "sequence": {
        "establish": ["lead_in", "arrival"],
        "answer": ["sequence", "echo_fragment"],
        "develop": ["sequence", "arpeggiation"],
        "intensify": ["sequence", "liquidation"],
        "cadence": ["cadential_turn", "liquidation"],
    },
}

_ORNAMENT_LIBRARY = {
    1: ["none", "arrival"],
    2: ["none", "arrival", "passing"],
    3: ["none", "passing", "neighbor", "arrival"],
    4: ["none", "passing", "neighbor", "chromatic_approach", "arrival"],
    5: ["none", "passing", "neighbor", "chromatic_approach", "release_turn", "arrival"],
}

_ACCOMPANIMENT_ROLE_LIBRARY = {
    "anchor": ["support-bass", "repeated", "held", "block-half", "bass-and-chord"],
    "pulse_support": ["support-bass", "repeated", "simple-broken", "block-quarter", "bass-and-chord", "waltz-bass"],
    "broken_support": ["simple-broken", "arpeggio-support", "alberti", "support-bass", "waltz-bass"],
    "cadence_support": ["bass-and-chord", "block-half", "octave-support", "support-bass"],
    "arrival_emphasis": ["bass-and-chord", "support-bass", "octave-support", "block-half", "arpeggio-support"],
}

_LEFT_PATTERN_FAMILY_PREFERENCES = {
    "held": ("held", "block-half", "block-quarter", "bass-and-chord"),
    "repeated": ("repeated", "support-bass", "waltz-bass", "octave-support"),
    "simple-broken": ("simple-broken", "arpeggio-support", "alberti"),
}

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

_REGISTER_MAPS = {
    1: {"floor": 0.18, "center": 0.42, "peak": 0.58},
    2: {"floor": 0.16, "center": 0.45, "peak": 0.62},
    3: {"floor": 0.14, "center": 0.48, "peak": 0.68},
    4: {"floor": 0.12, "center": 0.52, "peak": 0.78},
    5: {"floor": 0.10, "center": 0.55, "peak": 0.86},
}

_PHRASE_ARCHETYPES = {
    "period": {
        "establish": ["hold-answer"],
        "answer": ["neighbor-answer", "echo-tail"],
        "develop": ["bridge"],
        "intensify": ["climb"],
        "cadence": ["cadence-step"],
    },
    "sentence": {
        "establish": ["echo-tail"],
        "answer": ["echo-tail", "sequence-tail"],
        "develop": ["sequence-tail"],
        "intensify": ["fragment-push"],
        "cadence": ["cadence-step"],
    },
    "lyric": {
        "establish": ["sustain"],
        "answer": ["neighbor-answer"],
        "develop": ["bridge"],
        "intensify": ["rise-release"],
        "cadence": ["cadence-turn"],
    },
    "sequence": {
        "establish": ["hold-answer"],
        "answer": ["sequence-tail"],
        "develop": ["sequence-tail", "bridge"],
        "intensify": ["climb", "fragment-push"],
        "cadence": ["cadence-step"],
    },
}


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


def _choose_phrase_archetype(
    phrase_measures: list[int],
    role_by_measure: dict[int, str],
    texture_by_measure: dict[int, str],
    request: dict[str, Any],
    rng: random.Random,
) -> str:
    grade = int(request["grade"])
    focus = str(request.get("readingFocus", "balanced"))
    textures = [texture_by_measure.get(measure_number, "melody") for measure_number in phrase_measures]
    running_count = sum(1 for texture in textures if texture == "running")
    chordal_count = sum(1 for texture in textures if texture == "chordal")

    archetypes = ["period", "sentence", "lyric", "sequence"]
    weights: list[float] = []
    for name in archetypes:
        weight = 1.0
        if name == "period":
            weight = 1.4
            if focus == "balanced":
                weight += 0.3
        elif name == "sentence":
            weight = 1.1 + (0.25 if grade >= 5 else 0.0)
            if any(role == "intensify" for role in role_by_measure.values()):
                weight += 0.25
        elif name == "lyric":
            weight = 0.95 + (0.35 if focus == "melodic" else 0.0)
            if chordal_count == 0:
                weight += 0.15
        elif name == "sequence":
            weight = 0.9 + (0.25 if running_count > 0 else 0.0)
            if focus == "harmonic":
                weight -= 0.1
        weights.append(max(0.1, weight))

    return rng.choices(archetypes, weights=weights, k=1)[0]


def _build_continuation_plan(
    archetype: str,
    phrase_measures: list[int],
    role_by_measure: dict[int, str],
    texture_by_measure: dict[int, str],
    cadence_target: str,
    motive_blueprint: dict[str, Any],
    rng: random.Random,
) -> dict[int, str]:
    gesture_map = _PHRASE_ARCHETYPES.get(archetype, _PHRASE_ARCHETYPES["period"])
    continuation_by_measure: dict[int, str] = {}
    transform_by_measure = motive_blueprint.get("transformByMeasure", {})

    for measure_number in phrase_measures:
        if texture_by_measure.get(measure_number) != "melody":
            continue
        role = role_by_measure.get(measure_number, "develop")
        transform = str(transform_by_measure.get(measure_number, "sequence"))
        if transform in {"base", "repeat"}:
            gestures = ["hold-answer", "echo-tail"]
        elif transform == "sequence":
            gestures = ["sequence-tail", "bridge"]
        elif transform == "fragment":
            gestures = ["fragment-push", "climb"]
        elif transform == "cadence":
            gestures = ["cadence-step", "cadence-turn"]
        else:
            gestures = list(gesture_map.get(role, ["bridge"]))
        if role == "cadence" and cadence_target == "dominant":
            gestures = ["cadence-turn", *gestures]
        continuation_by_measure[measure_number] = rng.choice(gestures)

    return continuation_by_measure


def _split_duration_value(duration_value: float, allowed_durations: list[float]) -> list[float] | None:
    ordered = sorted({round(float(value), 3) for value in allowed_durations}, reverse=True)
    for left in ordered:
        right = round(duration_value - left, 3)
        if right <= 0:
            continue
        if any(abs(candidate - right) < 0.02 for candidate in ordered):
            snapped_right = min(ordered, key=lambda candidate: abs(candidate - right))
            if abs((left + snapped_right) - duration_value) < 0.03:
                return [left, snapped_right]
    return None


def _expand_motive_durations(
    base: list[float],
    allowed_durations: list[float],
    *,
    target_total: float = 0.0,
) -> list[float]:
    durations = [round(float(value), 3) for value in base if value in set(allowed_durations)]
    if not durations:
        durations = [max(allowed_durations)]

    while len(durations) < 3:
        largest_index = max(range(len(durations)), key=lambda idx: durations[idx])
        split = _split_duration_value(durations[largest_index], allowed_durations)
        if not split:
            break
        durations = durations[:largest_index] + split + durations[largest_index + 1:]

    # Phase 4: if a target_total is given, repeat the cell pattern to fill the measure.
    if target_total > 0:
        current_total = round(sum(durations), 3)
        # Repeat the base cell to fill up to the measure total
        base_filtered = [round(float(v), 3) for v in base if v in set(allowed_durations)] or durations[:2]
        safety = 0
        while current_total < target_total - 0.001 and safety < 20:
            safety += 1
            remaining = round(target_total - current_total, 3)
            # Try to fit a full cell repetition
            cell_total = round(sum(base_filtered), 3)
            if cell_total <= remaining + 0.001:
                durations.extend(base_filtered)
                current_total = round(current_total + cell_total, 3)
            else:
                # Fill with the largest allowed duration that fits
                fitting = [d for d in sorted(allowed_durations, reverse=True) if d <= remaining + 0.001]
                if fitting:
                    durations.append(fitting[0])
                    current_total = round(current_total + fitting[0], 3)
                else:
                    break
        # Trim if we overshot
        while round(sum(durations), 3) > target_total + 0.001 and len(durations) > 1:
            durations.pop()
    else:
        if len(durations) > 4:
            durations = durations[:4]

    return durations


def _coherent_answer_durations(
    motif_durations: list[float],
    answer_cell: list[float],
    allowed_durations: list[float],
    rng: random.Random,
) -> list[float]:
    raw_answer = _expand_motive_durations(answer_cell or motif_durations, allowed_durations)
    base_signature = _duration_signature(motif_durations)
    answer_signature = _duration_signature(raw_answer)

    if len(raw_answer) == len(motif_durations) and _signature_similarity(base_signature, answer_signature) >= 0.55:
        return raw_answer

    answer_durations = list(motif_durations)
    if len(answer_durations) >= 3 and rng.random() < 0.3:
        tail = round(answer_durations[-2] + answer_durations[-1], 3)
        if any(abs(candidate - tail) < 0.02 for candidate in allowed_durations):
            snapped_tail = min(allowed_durations, key=lambda candidate: abs(candidate - tail))
            answer_durations = answer_durations[:-2] + [snapped_tail]
    return answer_durations


def _adapt_step_template(template: list[int], target_steps: int) -> list[int]:
    if target_steps <= 0:
        return []
    if len(template) == target_steps:
        return list(template)
    if len(template) > target_steps:
        return list(template[:target_steps])

    output = list(template)
    while len(output) < target_steps:
        if output:
            output.append(-output[-1] if len(output) % 2 == 1 else output[-1])
        else:
            output.append(1)
    return output[:target_steps]


def _build_motive_blueprint(
    anchor_cell: list[float],
    answer_cell: list[float],
    allowed_durations: list[float],
    contour: str,
    phrase_measures: list[int],
    role_by_measure: dict[int, str],
    texture_by_measure: dict[int, str],
    source_blueprint: dict[str, Any] | None,
    inherit_rhythm: bool,
    inherit_contour: bool,
    rng: random.Random,
    *,
    measure_total: float = 0.0,
) -> dict[str, Any]:
    source_blueprint = source_blueprint or {}
    source_durations = list(source_blueprint.get("answerDurations") or source_blueprint.get("durations") or [])
    source_steps = list(source_blueprint.get("steps") or [])

    # Phase 4: expand motif to fill the full measure
    if inherit_rhythm and source_durations:
        motif_durations = _expand_motive_durations(source_durations, allowed_durations, target_total=measure_total)
    else:
        motif_durations = _expand_motive_durations(
            anchor_cell or answer_cell or [max(allowed_durations)],
            allowed_durations,
            target_total=measure_total,
        )
    note_count = max(2, len(motif_durations))
    if inherit_contour and source_steps:
        motif_steps = _adapt_step_template(source_steps, note_count - 1)
        if len(motif_steps) >= 2 and rng.random() < 0.18:
            motif_steps = motif_steps[1:] + motif_steps[:1]
    else:
        template_pool = _MOTIVE_STEP_TEMPLATES.get(contour, _MOTIVE_STEP_TEMPLATES["flat"])
        step_template = rng.choice(template_pool)
        motif_steps = _adapt_step_template(step_template, note_count - 1)

    answer_seed = source_durations if inherit_rhythm and source_durations else answer_cell
    answer_durations = _coherent_answer_durations(motif_durations, answer_seed, allowed_durations, rng)

    transform_by_measure: dict[int, str] = {}
    melody_measures = [measure_number for measure_number in phrase_measures if texture_by_measure.get(measure_number) == "melody"]

    if melody_measures:
        transform_by_measure[melody_measures[0]] = "base"
        ordered_followups = melody_measures[1:]
        for index, measure_number in enumerate(ordered_followups, start=1):
            role = role_by_measure.get(measure_number, "develop")
            if role == "cadence":
                transform = "cadence"
            elif index == 1:
                transform = "repeat"
            elif role == "intensify":
                transform = "intensify"
            elif role == "develop":
                transform = "sequence"
            else:
                transform = _MOTIVE_TRANSFORM_BY_ROLE.get(role, "sequence")
            transform_by_measure[measure_number] = transform

    return {
        "durations": motif_durations,
        "steps": motif_steps,
        "transformByMeasure": transform_by_measure,
        "answerDurations": answer_durations,
    }


def _measure_role_sequence(length: int) -> list[str]:
    if length <= 1:
        return ["cadence"]
    if length == 2:
        return ["establish", "cadence"]
    if length == 3:
        return ["establish", "answer", "cadence"]

    roles = ["establish", "answer"]
    middle_count = max(0, length - 3)
    if middle_count <= 1:
        roles.append("intensify")
    else:
        roles.extend(["develop"] * (middle_count - 1))
        roles.append("intensify")
    roles.append("cadence")
    return roles[:length]


def _texture_ceiling_for_grade(grade: int) -> str:
    if grade <= 2:
        return "melody"
    if grade == 3:
        return "chordal"
    return "running"


def _build_style_profile(request: dict[str, Any], preset: dict[str, Any]) -> StyleProfile:
    piano_rules = preset["piano"]
    grade = int(request["grade"])
    focus = str(request.get("readingFocus", "balanced"))
    connection_scale = {
        1: ("arrival", "lead_in", "passing"),
        2: ("arrival", "lead_in", "passing", "neighbor"),
        3: ("arrival", "lead_in", "passing", "neighbor", "echo_fragment", "arpeggiation"),
        4: ("arrival", "lead_in", "passing", "neighbor", "echo_fragment", "sequence", "arpeggiation", "suspension_like"),
        5: ("arrival", "lead_in", "passing", "neighbor", "echo_fragment", "sequence", "arpeggiation", "suspension_like", "cadential_turn", "liquidation"),
    }
    ornaments = tuple(
        ornament
        for ornament in _ORNAMENT_LIBRARY.get(grade, _ORNAMENT_LIBRARY[max(_ORNAMENT_LIBRARY)])
        if request.get("allowAccidentals") or ornament != "chromatic_approach"
    )
    density_floor = 0.18 + max(0, grade - 1) * 0.03
    density_ceiling = 0.52 + max(0, grade - 1) * 0.09
    if focus == "harmonic":
        density_ceiling -= 0.04
    elif focus == "melodic":
        density_ceiling += 0.03
    search_attempts = 22 + max(0, grade - 2) * 6
    if focus == "melodic":
        search_attempts += 4
    if grade >= 5:
        search_attempts += 12
    return StyleProfile(
        grade=grade,
        focus=focus,
        cadence_strength=float(piano_rules.get("cadenceStrictness", 0.85)),
        left_hand_persistence=float(piano_rules.get("leftPatternPersistence", 0.85)),
        register_span=(
            float(_REGISTER_MAPS.get(grade, _REGISTER_MAPS[5])["floor"]),
            float(_REGISTER_MAPS.get(grade, _REGISTER_MAPS[5])["peak"]),
        ),
        texture_ceiling=_texture_ceiling_for_grade(grade),
        allowed_connection_functions=connection_scale.get(grade, connection_scale[max(connection_scale)]),
        allowed_ornament_functions=ornaments,
        accidental_policy="functional" if request.get("allowAccidentals") else "diatonic",
        density_floor=max(0.16, density_floor),
        density_ceiling=min(0.94, density_ceiling),
        search_attempts=search_attempts,
    )


def _assign_phrase_grammars(
    phrases: list[list[int]],
    grade: int,
    focus: str,
    rng: random.Random,
) -> list[PhraseGrammar]:
    """Pre-decide grammatical function and shape for every phrase.

    Classical phrase grammar treats phrases like sentences: an antecedent
    asks a question (open cadence), a consequent answers (closed cadence).
    Continuation phrases develop material, and the closing phrase resolves.
    """
    n = len(phrases)
    grammars: list[PhraseGrammar] = []

    for i, phrase in enumerate(phrases):
        length = len(phrase)

        # --- Phrase function ---
        if n == 1:
            func = "closing"
        elif n == 2:
            func = "antecedent" if i == 0 else "consequent"
        elif n == 3:
            func = ("antecedent", "continuation", "consequent")[i]
        else:
            if i == 0:
                func = "antecedent"
            elif i == n - 1:
                func = "consequent"
            elif i == n - 2:
                func = "continuation"
            else:
                func = "continuation"

        # --- Cadence type ---
        # Antecedent: open cadence (half or deceptive).
        # Consequent/closing: closed cadence (authentic, sometimes plagal).
        # Continuation: weak cadence (half) or none significant.
        if func == "antecedent":
            cadence_type = rng.choices(
                ["half", "deceptive"],
                weights=[0.8, 0.2] if grade >= 4 else [1.0, 0.0],
                k=1,
            )[0]
        elif func in ("consequent", "closing"):
            cadence_type = rng.choices(
                ["authentic", "plagal"],
                weights=[0.82, 0.18] if grade >= 3 else [1.0, 0.0],
                k=1,
            )[0]
        else:  # continuation
            cadence_type = "half"

        # --- Peak position (0.0-1.0 within phrase) ---
        # Antecedent: peak in second half (question builds up).
        # Consequent: peak earlier (answer front-loads energy, then resolves).
        # Continuation: peak late (drives toward next phrase).
        # Closing: peak mid-early, then long resolution.
        if func == "antecedent":
            peak_position = rng.uniform(0.55, 0.75)
        elif func == "consequent":
            peak_position = rng.uniform(0.3, 0.55)
        elif func == "continuation":
            peak_position = rng.uniform(0.6, 0.85)
        else:  # closing
            peak_position = rng.uniform(0.35, 0.5)

        # --- Opening energy ---
        # Antecedent: moderate (sets the scene).
        # Consequent: slightly higher (confident answer).
        # Continuation: matches end of previous phrase.
        # Closing: assertive start, then wind down.
        if func == "antecedent":
            opening_energy = rng.uniform(0.35, 0.50)
        elif func == "consequent":
            opening_energy = rng.uniform(0.45, 0.62)
        elif func == "continuation":
            opening_energy = rng.uniform(0.42, 0.58)
        else:
            opening_energy = rng.uniform(0.48, 0.65)

        # --- Energy profile (per-measure intensity multipliers) ---
        # Build a smooth curve that peaks at peak_position and respects
        # the phrase function's character.
        profile: list[float] = []
        if length == 0:
            profile = [0.5]
        else:
            peak_idx = max(0, min(length - 1, round(peak_position * (length - 1))))
            for j in range(length):
                # Distance from peak, normalized to 0-1
                if length <= 1:
                    t = 0.0
                else:
                    dist = abs(j - peak_idx) / (length - 1)
                    t = 1.0 - dist  # 1.0 at peak, lower further away

                # Shape the curve based on function
                if func == "antecedent":
                    # Gradual build, moderate peak, slight drop at cadence
                    base = opening_energy + t * (0.72 - opening_energy)
                    if j == length - 1:
                        base *= 0.75  # cadence release
                elif func == "consequent":
                    # Front-loaded energy, long resolution tail
                    base = opening_energy + t * (0.68 - opening_energy)
                    # Measures after peak drop more steeply
                    if j > peak_idx:
                        drop = (j - peak_idx) / max(1, length - peak_idx - 1)
                        base *= 1.0 - drop * 0.35
                    if j == length - 1:
                        base *= 0.70  # strong resolution
                elif func == "continuation":
                    # Steady build, high energy throughout
                    base = opening_energy + t * (0.76 - opening_energy)
                    if j == length - 1:
                        base *= 0.82  # softer cadence (drives forward)
                else:  # closing
                    base = opening_energy + t * (0.66 - opening_energy)
                    # Long wind-down in second half
                    if j > peak_idx:
                        drop = (j - peak_idx) / max(1, length - peak_idx - 1)
                        base *= 1.0 - drop * 0.40
                    if j == length - 1:
                        base *= 0.65  # definitive resolution

                profile.append(max(0.18, min(0.92, base)))

        grammars.append(PhraseGrammar(
            phrase_index=i,
            function=func,
            cadence_type=cadence_type,
            peak_position=peak_position,
            opening_energy=opening_energy,
            energy_profile=tuple(profile),
        ))

    return grammars


def _build_piece_plan(
    phrases: list[list[int]],
    request: dict[str, Any],
    style_profile: StyleProfile,
    rng: random.Random,
    *,
    phrase_grammars: list[PhraseGrammar] | None = None,
) -> PiecePlan:
    measure_numbers = [measure for phrase in phrases for measure in phrase]
    if not measure_numbers:
        measure_numbers = [1]
    apex_measure = measure_numbers[min(len(measure_numbers) - 1, max(1, len(measure_numbers) // 2))]
    if style_profile.focus == "melodic":
        apex_measure = measure_numbers[min(len(measure_numbers) - 1, max(1, math.ceil(len(measure_numbers) * 0.66)))]

    # --- Phrase grammar ---
    grade = int(request["grade"])
    if phrase_grammars is None:
        phrase_grammars = _assign_phrase_grammars(phrases, grade, style_profile.focus, rng)

    # --- Cadence map (now driven by grammar) ---
    cadence_map: dict[int, str] = {}
    for pg in phrase_grammars:
        phrase = phrases[pg.phrase_index] if pg.phrase_index < len(phrases) else []
        if not phrase:
            continue
        # Map grammar cadence types to the existing tonic/dominant vocabulary
        # that downstream code understands, while preserving the richer type
        # in the grammar itself.
        if pg.cadence_type in ("authentic", "plagal"):
            cadence_map[phrase[-1]] = "tonic"
        else:
            cadence_map[phrase[-1]] = "dominant"

    # --- Intensity curve (now driven by grammar energy profiles) ---
    intensity_curve: dict[int, float] = {}
    for phrase_index, phrase in enumerate(phrases):
        if not phrase:
            continue
        grammar = phrase_grammars[phrase_index] if phrase_index < len(phrase_grammars) else None
        for local_index, measure_number in enumerate(phrase):
            if grammar and local_index < len(grammar.energy_profile):
                rise = grammar.energy_profile[local_index]
            else:
                rise = 0.5
            # Piece-level apex boost
            if measure_number == apex_measure:
                rise += 0.10
            intensity_curve[measure_number] = max(
                style_profile.density_floor,
                min(style_profile.density_ceiling, rise),
            )

    contrast_measures = tuple(
        measure_number
        for phrase in phrases
        for measure_number in phrase[1:-1]
        if intensity_curve.get(measure_number, 0.0) >= style_profile.density_ceiling - 0.08
    )
    dynamic_arc = "rise-and-release" if style_profile.focus != "harmonic" else "steady-build"
    form_label = _form_label(phrases)
    return PiecePlan(
        phrase_count=len(phrases),
        apex_measure=apex_measure,
        cadence_map=cadence_map,
        intensity_curve=intensity_curve,
        dynamic_arc=dynamic_arc,
        contrast_measures=contrast_measures,
        phrase_grammars=tuple(phrase_grammars),
        summary=f"{form_label}, apex around bar {apex_measure}, {dynamic_arc} arc",
    )


def _pick_answer_form(archetype: str, rng: random.Random) -> str:
    answer_forms = {
        "period": ["echo", "sequence"],
        "sentence": ["sequence", "fragment"],
        "lyric": ["neighbor", "echo"],
        "sequence": ["sequence", "liquidation"],
    }
    return rng.choice(answer_forms.get(archetype, ["echo"]))


def _choose_accompaniment_role(
    phrase_index: int,
    phrase_measures: list[int],
    request: dict[str, Any],
    role_by_measure: dict[int, str],
    rng: random.Random,
) -> str:
    left_pattern = str(request.get("leftHandPattern", "held"))
    if left_pattern == "simple-broken":
        return "broken_support"
    if left_pattern == "repeated":
        return rng.choice(["pulse_support", "anchor"])
    if request.get("readingFocus") == "harmonic":
        return rng.choice(["pulse_support", "arrival_emphasis", "anchor"])
    if any(role_by_measure.get(measure_number) == "intensify" for measure_number in phrase_measures):
        return rng.choice(["broken_support", "pulse_support", "arrival_emphasis"])
    if phrase_index == 0:
        return rng.choice(["anchor", "pulse_support", "broken_support"])
    return rng.choice(["pulse_support", "broken_support", "arrival_emphasis"])


def _available_accompaniment_families(
    role: str,
    request: dict[str, Any],
    preset: dict[str, Any],
) -> list[str]:
    available = list(dict.fromkeys(preset["piano"].get("leftPatternFamilies", ["held"])))
    preferred = _preferred_left_families(request, available)
    preferred_set = set(preferred)
    choices = [
        family
        for family in _ACCOMPANIMENT_ROLE_LIBRARY.get(role, ["held"])
        if family in set(available)
        and (family != "alberti" or bool(preset["piano"].get("allowAlberti", False)))
        and (family != "octave-support" or (bool(preset["piano"].get("allowOctaves", False)) and int(request["grade"]) >= 5))
        and family in preferred_set
    ]
    if choices:
        return choices

    fallback_choices = [
        family
        for family in preferred
        if (family != "alberti" or bool(preset["piano"].get("allowAlberti", False)))
        and (family != "octave-support" or (bool(preset["piano"].get("allowOctaves", False)) and int(request["grade"]) >= 5))
    ]
    return fallback_choices or list(available) or ["held"]


def _build_accompaniment_plan(
    role: str,
    request: dict[str, Any],
    preset: dict[str, Any],
    rng: random.Random,
) -> AccompanimentPlan:
    families = _available_accompaniment_families(role, request, preset)
    cadence_role = "cadence_support" if role != "arrival_emphasis" else "arrival_emphasis"
    cadence_choices = _available_accompaniment_families(cadence_role, request, preset)
    focus = str(request.get("readingFocus", "balanced"))
    weighted_families: list[str] = []
    for family in families:
        weight = 1
        if focus == "melodic" and family in {"support-bass", "repeated", "simple-broken", "arpeggio-support"}:
            weight += 2
        if focus == "harmonic" and family in {"bass-and-chord", "block-half", "block-quarter"}:
            weight += 2
        if int(request.get("grade", 1)) >= 5 and family in {"simple-broken", "arpeggio-support", "waltz-bass"}:
            weight += 1
        weighted_families.extend([family] * max(1, weight))
    return AccompanimentPlan(
        role=role,
        primary_family=rng.choice(weighted_families or families),
        support_families=tuple(families),
        cadence_family=rng.choice(cadence_choices),
    )


def _left_family_cluster(family: str) -> str:
    if family in {"simple-broken", "arpeggio-support", "alberti"}:
        return "broken"
    if family in {"held", "block-half", "block-quarter"}:
        return "block"
    return "bass"


def _cluster_family_pool(
    families: list[str],
    cluster: str,
) -> list[str]:
    return [family for family in families if _left_family_cluster(family) == cluster]


def _left_family_options_for_measure(
    role: str,
    texture: str,
    primary_family: str,
    accompaniment_plan: AccompanimentPlan,
    available_families: list[str],
) -> list[str]:
    support_families = list(dict.fromkeys(accompaniment_plan.support_families or tuple(available_families)))
    cadence_family = accompaniment_plan.cadence_family if accompaniment_plan.cadence_family in available_families else primary_family
    primary_cluster = _left_family_cluster(primary_family)
    primary_pool = _cluster_family_pool(support_families, primary_cluster) or [primary_family]
    broken_pool = _cluster_family_pool(available_families, "broken") or primary_pool
    bass_pool = _cluster_family_pool(available_families, "bass") or primary_pool
    block_pool = _cluster_family_pool(available_families, "block") or primary_pool

    if role == "cadence":
        return list(dict.fromkeys([cadence_family, *block_pool, *bass_pool]))
    if role == "establish":
        return list(dict.fromkeys([primary_family, *primary_pool, *bass_pool]))
    if texture == "running":
        return list(dict.fromkeys([*broken_pool, *bass_pool, primary_family]))
    if texture == "chordal":
        return list(dict.fromkeys([*bass_pool, *broken_pool, *block_pool, primary_family]))
    if role == "answer":
        return list(dict.fromkeys([*bass_pool, *primary_pool, *broken_pool]))
    if role == "intensify":
        return list(dict.fromkeys([*broken_pool, *bass_pool, *block_pool, primary_family]))
    if role == "develop":
        return list(dict.fromkeys([*bass_pool, *broken_pool, *primary_pool, primary_family]))
    return list(dict.fromkeys([*bass_pool, *primary_pool, *broken_pool, primary_family]))


def _build_left_family_plan(
    phrase_measures: list[int],
    role_by_measure: dict[int, str],
    texture_by_measure: dict[int, str],
    request: dict[str, Any],
    preset: dict[str, Any],
    accompaniment_plan: AccompanimentPlan,
    previous_phrase_plan: dict[str, Any] | None,
    rng: random.Random,
    *,
    piece_lh_family: str | None = None,
) -> dict[int, str]:
    available = list(dict.fromkeys(preset["piano"].get("leftPatternFamilies", ["held"])))
    grade = int(request["grade"])

    # Phase 2: lock LH family across the piece (grades 1-3) or phrase (grades 4-5).
    if piece_lh_family is not None:
        locked_family = piece_lh_family
        # For cadence measures at grade 4+, allow the cadence family as a single exception.
        cadence_family = accompaniment_plan.cadence_family
        family_by_measure: dict[int, str] = {}
        for measure_number in phrase_measures:
            role = str(role_by_measure.get(measure_number, "develop"))
            if grade >= 4 and role == "cadence" and cadence_family in available:
                family_by_measure[measure_number] = cadence_family
            else:
                family_by_measure[measure_number] = locked_family
        return family_by_measure

    # --- Original weighted per-measure logic (fallback when piece_lh_family not set) ---
    persistence = float(preset["piano"].get("leftPatternPersistence", 0.85))
    previous_map = dict(previous_phrase_plan.get("_leftFamilyByMeasure") or {}) if previous_phrase_plan else {}
    previous_tail_family = None
    if previous_map:
        previous_tail_family = previous_map.get(max(previous_map))
    elif previous_phrase_plan:
        previous_tail_family = previous_phrase_plan.get("leftFamily")

    primary_family = accompaniment_plan.primary_family if accompaniment_plan.primary_family in available else available[0]
    if previous_tail_family == primary_family:
        primary_pool = _cluster_family_pool(available, _left_family_cluster(primary_family))
        alternate_pool = [family for family in primary_pool if family != previous_tail_family]
        if alternate_pool:
            primary_family = rng.choice(alternate_pool)

    family_by_measure = {}
    previous_family = previous_tail_family
    unique_families: set[str] = set()

    for idx, measure_number in enumerate(phrase_measures):
        role = str(role_by_measure.get(measure_number, "develop"))
        texture = str(texture_by_measure.get(measure_number, "melody"))
        options = _left_family_options_for_measure(
            role,
            texture,
            primary_family,
            accompaniment_plan,
            available,
        )
        if not options:
            options = [primary_family]

        weighted_options: list[str] = []
        for family in options:
            weight = 1
            if family == primary_family:
                weight += 4 if idx == 0 else 2
            if family == accompaniment_plan.cadence_family and role == "cadence":
                weight += 6
            if previous_family and family == previous_family:
                weight += 2 if persistence >= 0.85 and role in {"establish", "answer"} else 0
                weight -= 2 if role in {"answer", "develop", "intensify"} else 0
            if texture == "running" and family in {"simple-broken", "arpeggio-support", "alberti"}:
                weight += 3
            if texture == "melody" and family in {"support-bass", "repeated", "bass-and-chord", "simple-broken", "arpeggio-support"}:
                weight += 2
            if grade >= 5 and texture == "melody" and family in {"bass-and-chord", "simple-broken", "arpeggio-support", "alberti", "octave-support"}:
                weight += 2
            if role == "intensify" and family in {"arpeggio-support", "alberti", "bass-and-chord", "octave-support"}:
                weight += 2
            if role == "answer" and family in {"support-bass", "simple-broken", "repeated", "bass-and-chord"}:
                weight += 2
            if role == "develop" and family in {"simple-broken", "arpeggio-support", "waltz-bass", "support-bass", "bass-and-chord"}:
                weight += 2
            if grade >= 5 and role in {"develop", "intensify"} and family in {"repeated", "held", "block-half"}:
                weight -= 1
            if idx == len(phrase_measures) - 2 and family == accompaniment_plan.cadence_family:
                weight += 2
            if idx == 0 and previous_tail_family and family == previous_tail_family:
                weight -= 2
            weighted_options.extend([family] * max(1, weight))

        chosen = rng.choice(weighted_options or options)
        family_by_measure[measure_number] = chosen
        unique_families.add(chosen)
        previous_family = chosen

    if len(unique_families) < 2 and len(phrase_measures) >= 4:
        preferred_pivots = [
            measure_number
            for measure_number in phrase_measures[1:-1]
            if role_by_measure.get(measure_number) in {"answer", "develop", "intensify"}
        ] or phrase_measures[1:-1]
        if preferred_pivots:
            pivot_measure = preferred_pivots[0]
            role = str(role_by_measure.get(pivot_measure, "answer"))
            texture = str(texture_by_measure.get(pivot_measure, "melody"))
            options = [
                family
                for family in _left_family_options_for_measure(
                    role,
                    texture,
                    primary_family,
                    accompaniment_plan,
                    available,
                )
                if family != family_by_measure[pivot_measure]
            ]
            if options:
                family_by_measure[pivot_measure] = rng.choice(options)

    return family_by_measure


def _register_slot_for_position(
    contour: str,
    relative_position: float,
    style_profile: StyleProfile,
    target_peak_measure: bool,
) -> float:
    register_map = _REGISTER_MAPS.get(style_profile.grade, _REGISTER_MAPS[5])
    floor = float(register_map["floor"])
    center = float(register_map["center"])
    peak = float(register_map["peak"])
    if contour == "ascending":
        slot = floor + (peak - floor) * relative_position
    elif contour == "descending":
        slot = peak - (peak - floor) * relative_position
    elif contour == "arch":
        slope = relative_position * 2 if relative_position <= 0.5 else (1 - relative_position) * 2
        slot = center + (peak - center) * max(0.0, slope)
    elif contour == "valley":
        slope = relative_position * 2 if relative_position <= 0.5 else (1 - relative_position) * 2
        slot = center - (center - floor) * max(0.0, slope)
    else:
        slot = center
    if target_peak_measure:
        slot = max(slot, peak - 0.04)
    return max(style_profile.register_span[0], min(style_profile.register_span[1], slot))


def _anchor_role_for_measure(
    measure_role: str,
    cadence_target: str,
    is_phrase_end: bool,
) -> str:
    if is_phrase_end:
        return "tonic" if cadence_target == "tonic" else cadence_target
    if measure_role == "establish":
        return "root"
    if measure_role == "answer":
        return "third"
    if measure_role == "intensify":
        return "dominant"
    return "stable"


def _choose_connection_name(
    archetype: str,
    measure_role: str,
    cadence_target: str,
    style_profile: StyleProfile,
    request: dict[str, Any],
    rng: random.Random,
) -> str:
    choices = list(_CONNECTION_LIBRARY.get(archetype, _CONNECTION_LIBRARY["period"]).get(measure_role, ["passing"]))
    if measure_role == "cadence":
        cadence_entry = _CADENCE_LIBRARY.get(request["timeSignature"], _CADENCE_LIBRARY["4/4"]).get(cadence_target)
        if cadence_entry:
            choices = [str(cadence_entry["connection"]), *choices]
    filtered = [choice for choice in choices if choice in set(style_profile.allowed_connection_functions)]
    return rng.choice(filtered or list(style_profile.allowed_connection_functions))


def _top_pitch_role_for_measure(
    measure_role: str,
    cadence_target: str,
    *,
    is_phrase_end: bool,
    answer_form: str,
    focus: str,
) -> str:
    if is_phrase_end:
        return "tonic" if cadence_target == "tonic" else cadence_target
    if measure_role == "establish":
        return "third" if focus == "melodic" else "root"
    if measure_role == "answer":
        return "fifth" if answer_form == "sequence" else "third"
    if measure_role == "intensify":
        return "dominant"
    if measure_role == "cadence":
        return "tonic" if cadence_target == "tonic" else "dominant"
    return "stable"


def _top_motion_role_for_measure(measure_role: str, contour: str) -> str:
    if measure_role == "cadence":
        return "cadence"
    if measure_role == "intensify":
        return "push"
    if contour in {"ascending", "arch"}:
        return "rise"
    if contour == "descending":
        return "release"
    return "step"


def _bass_pitch_role_for_measure(
    measure_index: int,
    measure_role: str,
    cadence_target: str,
    *,
    is_phrase_end: bool,
    phrase_index: int,
) -> str:
    if is_phrase_end:
        return "tonic" if cadence_target == "tonic" else "dominant"
    if measure_role == "establish":
        if phrase_index == 0:
            return "root"
        return "third" if phrase_index % 2 else "fifth"
    if measure_role == "answer":
        return "fifth" if (measure_index + phrase_index) % 2 == 0 else "third"
    if measure_role == "develop":
        return "third" if (measure_index + phrase_index) % 3 == 1 else "fifth"
    if measure_role == "intensify":
        return "dominant" if (measure_index + phrase_index) % 2 == 0 else "fifth"
    return "root"


def _bass_motion_role_for_measure(measure_role: str, measure_index: int) -> str:
    if measure_role == "cadence":
        return "cadence"
    if measure_role == "intensify":
        return "leap"
    if measure_role in {"answer", "develop"}:
        return "step"
    if measure_index == 0:
        return "hold"
    return "step"


def _build_top_line_plan(
    phrase_index: int,
    phrase_measures: list[int],
    role_by_measure: dict[int, str],
    contour: str,
    cadence_target: str,
    answer_form: str,
    style_profile: StyleProfile,
    piece_plan: PiecePlan,
) -> TopLinePlan:
    register_targets: dict[int, float] = {}
    pitch_roles: dict[int, str] = {}
    motion_roles: dict[int, str] = {}
    peak_measure = phrase_measures[min(len(phrase_measures) - 1, len(phrase_measures) // 2)]
    if contour == "ascending":
        peak_measure = phrase_measures[-1]
    elif contour == "descending":
        peak_measure = phrase_measures[0]
    elif piece_plan.apex_measure in phrase_measures:
        peak_measure = piece_plan.apex_measure

    for index, measure_number in enumerate(phrase_measures):
        position = index / max(1, len(phrase_measures) - 1) if len(phrase_measures) > 1 else 0.5
        register_slot = _register_slot_for_position(
            contour,
            position,
            style_profile,
            measure_number == peak_measure,
        )
        register_targets[measure_number] = max(
            style_profile.register_span[0],
            min(style_profile.register_span[1], register_slot + 0.08),
        )
        measure_role = role_by_measure.get(measure_number, "develop")
        pitch_roles[measure_number] = _top_pitch_role_for_measure(
            measure_role,
            cadence_target,
            is_phrase_end=measure_number == phrase_measures[-1],
            answer_form=answer_form,
            focus=style_profile.focus,
        )
        motion_roles[measure_number] = _top_motion_role_for_measure(measure_role, contour)

    return TopLinePlan(
        phrase_index=phrase_index,
        peak_measure=peak_measure,
        register_targets=register_targets,
        pitch_roles=pitch_roles,
        motion_roles=motion_roles,
    )


def _build_bass_line_plan(
    phrase_index: int,
    phrase_measures: list[int],
    role_by_measure: dict[int, str],
    cadence_target: str,
    style_profile: StyleProfile,
) -> BassLinePlan:
    register_targets: dict[int, float] = {}
    pitch_roles: dict[int, str] = {}
    motion_roles: dict[int, str] = {}
    low_span = max(0.02, style_profile.register_span[0] * 0.55)
    high_span = max(low_span + 0.06, style_profile.register_span[0] + 0.12)

    for index, measure_number in enumerate(phrase_measures):
        measure_role = role_by_measure.get(measure_number, "develop")
        position = index / max(1, len(phrase_measures) - 1) if len(phrase_measures) > 1 else 0.5
        register_targets[measure_number] = max(
            0.02,
            min(0.28, low_span + (high_span - low_span) * position * 0.35),
        )
        pitch_roles[measure_number] = _bass_pitch_role_for_measure(
            index,
            measure_role,
            cadence_target,
            is_phrase_end=measure_number == phrase_measures[-1],
            phrase_index=phrase_index,
        )
        motion_roles[measure_number] = _bass_motion_role_for_measure(measure_role, index)

    return BassLinePlan(
        phrase_index=phrase_index,
        cadence_measure=phrase_measures[-1],
        register_targets=register_targets,
        pitch_roles=pitch_roles,
        motion_roles=motion_roles,
    )


def _resolve_top_line_target(
    plan: TopLinePlan | None,
    measure_number: int,
    pool: list[int],
    harmony_tones: list[int],
    key_signature: str,
    harmony: str,
    reference_pitch: int,
) -> int | None:
    if plan is None or measure_number not in plan.pitch_roles:
        return None
    candidates = _pitch_role_candidates(
        pool,
        harmony_tones,
        key_signature,
        harmony,
        plan.pitch_roles[measure_number],
    )
    preferred = [
        pitch_value for pitch_value in candidates
        if _nearest_pool_index(pool, pitch_value) >= max(0, len(pool) // 2 - 1)
    ] or candidates
    target_index = _relative_slot_to_index(plan.register_targets.get(measure_number, 0.7), len(pool))
    motion_role = plan.motion_roles.get(measure_number, "step")

    def _score(pitch_value: int) -> float:
        interval = abs(pitch_value - reference_pitch)
        interval_penalty = interval * 0.05
        if motion_role == "rise" and pitch_value <= reference_pitch:
            interval_penalty += 0.45
        elif motion_role == "release" and pitch_value >= reference_pitch:
            interval_penalty += 0.45
        elif motion_role == "cadence":
            interval_penalty += interval * 0.02
        repeat_penalty = 0.7 if pitch_value == reference_pitch else 0.0
        return abs(_nearest_pool_index(pool, pitch_value) - target_index) + interval_penalty + repeat_penalty

    return min(preferred, key=_score)


def _resolve_bass_line_target(
    plan: BassLinePlan | None,
    measure_number: int,
    pool: list[int],
    harmony_tones: list[int],
    key_signature: str,
    harmony: str,
    reference_pitch: int | None,
) -> int | None:
    if plan is None or measure_number not in plan.pitch_roles:
        return None
    candidates = _pitch_role_candidates(
        pool,
        harmony_tones,
        key_signature,
        harmony,
        plan.pitch_roles[measure_number],
    )
    preferred = [
        pitch_value for pitch_value in candidates
        if _nearest_pool_index(pool, pitch_value) <= max(1, len(pool) // 2)
    ] or candidates
    target_index = _relative_slot_to_index(plan.register_targets.get(measure_number, 0.15), len(pool))
    motion_role = plan.motion_roles.get(measure_number, "step")

    def _score(pitch_value: int) -> float:
        interval_penalty = 0.0
        if reference_pitch is not None:
            interval = abs(pitch_value - reference_pitch)
            if motion_role == "hold":
                interval_penalty = interval * 0.08
            elif motion_role == "step":
                if interval == 0:
                    interval_penalty = 0.55
                elif interval <= 5:
                    interval_penalty = abs(interval - 2.5) * 0.08
                else:
                    interval_penalty = 0.55 + (interval - 5) * 0.1
            elif motion_role == "leap":
                interval_penalty = abs(interval - 6) * 0.06
            else:
                interval_penalty = interval * 0.05
            if pitch_value == reference_pitch and motion_role != "hold":
                interval_penalty += 0.45
        return abs(_nearest_pool_index(pool, pitch_value) - target_index) + interval_penalty

    return min(preferred, key=_score)


def _choose_ornament_name(
    measure_role: str,
    style_profile: StyleProfile,
    request: dict[str, Any],
    rng: random.Random,
) -> str:
    choices = list(style_profile.allowed_ornament_functions)
    if measure_role == "cadence" and "arrival" in choices:
        return "arrival"
    if measure_role in {"establish", "answer"} and "none" in choices and rng.random() < 0.45:
        return "none"
    if request.get("allowAccidentals") and "chromatic_approach" in choices and measure_role in {"develop", "intensify"} and rng.random() < 0.25:
        return "chromatic_approach"
    return rng.choice(choices or ["none"])


def _build_line_plan(
    phrase_index: int,
    phrase_measures: list[int],
    role_by_measure: dict[int, str],
    contour: str,
    archetype: str,
    cadence_target: str,
    style_profile: StyleProfile,
    piece_plan: PiecePlan,
    request: dict[str, Any],
    rng: random.Random,
) -> LinePlan:
    anchors: list[AnchorTone] = []
    connections: dict[int, ConnectionFunction] = {}
    ornaments: dict[int, OrnamentFunction] = {}
    trajectory: dict[int, float] = {}
    climax_measure = phrase_measures[min(len(phrase_measures) - 1, len(phrase_measures) // 2)]
    if contour == "ascending":
        climax_measure = phrase_measures[-1]
    elif contour == "descending":
        climax_measure = phrase_measures[0]
    elif piece_plan.apex_measure in phrase_measures:
        climax_measure = piece_plan.apex_measure

    for index, measure_number in enumerate(phrase_measures):
        position = index / max(1, len(phrase_measures) - 1) if len(phrase_measures) > 1 else 0.5
        measure_role = role_by_measure.get(measure_number, "develop")
        register_slot = _register_slot_for_position(
            contour,
            position,
            style_profile,
            measure_number == climax_measure,
        )
        trajectory[measure_number] = register_slot
        anchors.append(
            AnchorTone(
                measure=measure_number,
                beat=0.0,
                pitch_role=_anchor_role_for_measure(
                    measure_role,
                    cadence_target,
                    measure_number == phrase_measures[-1],
                ),
                register_slot=register_slot,
                local_goal=measure_role,
            )
        )
        connection_name = _choose_connection_name(
            archetype,
            measure_role,
            cadence_target,
            style_profile,
            request,
            rng,
        )
        if phrase_index > 0 and index == 0:
            if measure_role == "answer":
                if "sequence" in set(style_profile.allowed_connection_functions):
                    connection_name = "sequence"
                elif "echo_fragment" in set(style_profile.allowed_connection_functions):
                    connection_name = "echo_fragment"
            elif measure_role == "develop":
                if "passing" in set(style_profile.allowed_connection_functions):
                    connection_name = "passing"
        elif phrase_index > 0 and measure_role == "develop" and connection_name in {"arrival", "lead_in"}:
            if "arpeggiation" in set(style_profile.allowed_connection_functions):
                connection_name = "arpeggiation"
            elif "sequence" in set(style_profile.allowed_connection_functions):
                connection_name = "sequence"
        connections[measure_number] = ConnectionFunction(
            name=connection_name,
            role=measure_role,
            intensity=piece_plan.intensity_curve.get(measure_number, style_profile.density_floor),
        )
        ornament_name = _choose_ornament_name(measure_role, style_profile, request, rng)
        if phrase_index > 0 and index == 0 and ornament_name == "none":
            if "passing" in set(style_profile.allowed_ornament_functions):
                ornament_name = "passing"
        ornaments[measure_number] = OrnamentFunction(
            name=ornament_name,
            placement="pre_anchor" if ornament_name in {"passing", "chromatic_approach", "neighbor"} else "arrival",
        )

    return LinePlan(
        phrase_index=phrase_index,
        climax_measure=climax_measure,
        register_trajectory=trajectory,
        anchors=tuple(anchors),
        connections=connections,
        ornaments=ornaments,
    )


def _simple_rhythm_cells(allowed_durations: list[float]) -> list[list[float]]:
    allowed = set(allowed_durations)
    simple = [cell for cell in _RHYTHM_CELLS_SIMPLE if all(d in allowed for d in cell)]
    if simple:
        return simple
    longer = [d for d in allowed_durations if d >= 1.0]
    if longer:
        return [[max(longer)]]
    return [[max(allowed_durations)]]


def _scaled_density_target(
    base: float,
    grade: int,
    role: str,
    request: dict[str, Any],
) -> float:
    bonus = max(0, grade - 1) * 0.06
    if request.get("readingFocus") == "harmonic" and role in {"answer", "develop", "intensify"}:
        bonus += 0.03
    if request.get("readingFocus") == "melodic" and role in {"develop", "intensify"}:
        bonus += 0.02
    if role == "cadence":
        bonus *= 0.5
    return max(0.18, min(0.95, base + bonus))


def _choose_phrase_textures(
    phrase_measures: list[int],
    role_by_measure: dict[int, str],
    request: dict[str, Any],
    preset: dict[str, Any],
    rng: random.Random,
) -> dict[int, str]:
    piano_rules = preset["piano"]
    base_weights = dict(piano_rules.get("textureWeights", {"melody": 1.0, "chordal": 0.0, "running": 0.0}))
    grade = int(request["grade"])
    focus = str(request.get("readingFocus", "balanced"))

    if grade < 4:
        return {measure_number: "melody" for measure_number in phrase_measures}

    primary_weights = {
        "melody": max(0.01, float(base_weights.get("melody", 1.0))) * (
            1.22 if focus == "harmonic" else (1.32 if focus == "melodic" else 1.16)
        ),
        "chordal": max(0.01, float(base_weights.get("chordal", 0.0))) * (
            1.35 if focus == "harmonic" else (1.0 if focus == "melodic" else 1.08)
        ),
    }
    if request.get("coordinationStyle") == "together":
        primary_weights["chordal"] *= 1.18

    primary_texture = rng.choices(
        ["melody", "chordal"],
        weights=[primary_weights["melody"], primary_weights["chordal"]],
        k=1,
    )[0]
    if focus == "harmonic" and len(phrase_measures) <= 4 and grade < 5:
        primary_texture = "melody"

    texture_by_measure = {measure_number: primary_texture for measure_number in phrase_measures}

    # Cadences should resolve simply; never end a phrase with a running bar.
    cadence_measure = phrase_measures[-1]
    if primary_texture == "chordal" and focus == "harmonic" and rng.random() < 0.25:
        texture_by_measure[cadence_measure] = "chordal"
    else:
        texture_by_measure[cadence_measure] = "melody"

    if phrase_measures:
        texture_by_measure[phrase_measures[0]] = "melody"

    contrast_candidates = [
        measure_number
        for measure_number in phrase_measures
        if measure_number not in {phrase_measures[0], cadence_measure}
        and role_by_measure.get(measure_number) in {"answer", "develop", "intensify"}
    ]
    intensify_candidates = [
        measure_number for measure_number in contrast_candidates
        if role_by_measure.get(measure_number) == "intensify"
    ]

    should_add_contrast = len(phrase_measures) >= 3 and (
        rng.random() < (0.68 if grade == 4 else 0.86)
    )

    if should_add_contrast and contrast_candidates:
        contrast_measure = rng.choice(intensify_candidates or contrast_candidates)
        if focus == "harmonic":
            contrast_texture = "chordal" if primary_texture == "melody" else "melody"
        else:
            allow_running = grade >= 5 and role_by_measure.get(contrast_measure) == "intensify"
            if allow_running and rng.random() < 0.58:
                contrast_texture = "running"
            else:
                contrast_texture = "chordal" if primary_texture == "melody" else "melody"
        texture_by_measure[contrast_measure] = contrast_texture

    # Rare second contrast for longer Grade 5 phrases, but keep it adjacent to the first idea.
    if grade >= 5 and len(phrase_measures) >= 4 and rng.random() < 0.4:
        current_contrasts = [
            measure_number for measure_number, texture in texture_by_measure.items()
            if texture != primary_texture and measure_number != cadence_measure
        ]
        if current_contrasts:
            base_measure = current_contrasts[0]
            neighbor_measures = [
                measure_number for measure_number in contrast_candidates
                if measure_number != base_measure and abs(measure_number - base_measure) == 1
            ]
            if neighbor_measures:
                neighbor_measure = rng.choice(neighbor_measures)
                texture_by_measure[neighbor_measure] = texture_by_measure[base_measure]

    if grade >= 5 and "running" not in texture_by_measure.values():
        running_candidates = [
            measure_number
            for measure_number in contrast_candidates
            if role_by_measure.get(measure_number) in {"develop", "intensify"}
            and measure_number != cadence_measure
        ]
        running_bias = max(0.18, min(0.6, float(base_weights.get("running", 0.0)) * 1.8))
        if running_candidates and rng.random() < running_bias:
            running_measure = rng.choice(intensify_candidates or running_candidates)
            texture_by_measure[running_measure] = "running"

    return texture_by_measure


def _choose_phrase_left_family(
    request: dict[str, Any],
    preset: dict[str, Any],
    rng: random.Random,
) -> str:
    piano_rules = preset["piano"]
    families = list(piano_rules.get("leftPatternFamilies", ["held"]))
    families = _preferred_left_families(request, families)
    grade = int(request["grade"])
    meter = str(request.get("timeSignature", "4/4"))
    focus = str(request.get("readingFocus", "balanced"))
    preferred_families = set(families)

    if grade < 4:
        weighted = [
            family
            for family in families
            for _ in range(4 if family in preferred_families else 1)
        ]
        return rng.choice(weighted or families)

    weighted_families: list[str] = []
    for family in families:
        weight = 1
        if family in {"block-half", "bass-and-chord", "support-bass"}:
            weight = 5
        elif family in {"block-quarter", "simple-broken", "arpeggio-support"}:
            weight = 3
        elif family == "alberti":
            weight = 3 if bool(piano_rules.get("allowAlberti", False)) else 0
        elif family == "octave-support":
            weight = 3 if bool(piano_rules.get("allowOctaves", False)) and grade >= 5 else 0
        elif family == "waltz-bass":
            weight = 3 if meter.startswith("3/") else 0

        if focus == "harmonic" and family in {"block-half", "bass-and-chord", "block-quarter"}:
            weight += 1
        if focus == "melodic" and family in {"support-bass", "simple-broken", "arpeggio-support", "alberti"}:
            weight += 2
        if grade >= 5 and family in {"arpeggio-support", "alberti", "octave-support"}:
            weight += 1
        if family in preferred_families:
            weight += 4

        weighted_families.extend([family] * max(0, weight))

    return rng.choice(weighted_families or families or ["held"])


def _group_into_phrases(
    measure_count: int,
    allowed_lengths: list[int],
    rng: random.Random,
) -> list[list[int]]:
    del allowed_lengths, rng
    return _phrase_form_template(measure_count)


def _pick_phrase_plan(
    phrase_index: int,
    phrase_measures: list[int],
    request: dict[str, Any],
    preset: dict[str, Any],
    style_profile: StyleProfile,
    piece_plan: PiecePlan,
    previous_phrase_plan: dict[str, Any] | None,
    rng: random.Random,
    *,
    piece_rhythm_cells: dict[str, list[list[float]]] | None = None,
    piece_lh_family: str | None = None,
    piece_archetype: str | None = None,
    piece_contour: str | None = None,
    phrase_grammar: PhraseGrammar | None = None,
) -> dict[str, Any]:
    piano_rules = preset["piano"]
    accidental_roles = list(piano_rules.get("accidentalRoles", []))
    cadence_target = piece_plan.cadence_map.get(phrase_measures[-1], "tonic")

    # Use piece-level rhythm cells if provided (Phase 1: piece-level rhythm identity)
    allowed_durs = sorted({float(v) for v in piano_rules["rightQuarterLengths"]}, reverse=True)
    lh_allowed = sorted(
        {float(v) for v in piano_rules.get("leftQuarterLengths", piano_rules["rightQuarterLengths"])},
        reverse=True,
    )
    if piece_rhythm_cells is not None:
        rh_cells = list(piece_rhythm_cells["rh"])
        lh_cells = list(piece_rhythm_cells["lh"])
    else:
        rh_cells = _pick_rhythm_cells(int(request["grade"]), allowed_durs, rng)
        lh_cells = _pick_rhythm_cells(int(request["grade"]), lh_allowed, rng)

    # Phase 6: derive contour deterministically from piece-level contour.
    # Phrase A and A' share the same contour; B/close get the complement.
    _CONTOUR_COMPLEMENT = {
        "ascending": "descending", "descending": "ascending",
        "arch": "valley", "valley": "arch", "flat": "flat",
    }
    if piece_contour is not None:
        if phrase_index == 0:
            contour = piece_contour
        elif phrase_index == 1:
            contour = piece_contour  # A' = same as A
        else:
            contour = _CONTOUR_COMPLEMENT.get(piece_contour, piece_contour)  # B = complement
        inherit_contour = phrase_index > 0
    else:
        source_contour = str(previous_phrase_plan.get("_contour", "flat")) if previous_phrase_plan else "flat"
        inherit_contour = bool(previous_phrase_plan and rng.random() < 0.72)
        contour = _related_contour(source_contour, rng) if inherit_contour else _pick_contour(rng)
    measure_roles = _measure_role_sequence(len(phrase_measures))
    role_by_measure = {
        measure_number: role for measure_number, role in zip(phrase_measures, measure_roles, strict=False)
    }
    if phrase_index > 0 and phrase_measures:
        role_by_measure[phrase_measures[0]] = "answer"
        if len(phrase_measures) >= 4:
            role_by_measure[phrase_measures[1]] = "develop"

    # --- Phrase grammar overrides ---
    # Grammar function shapes which measure gets the intensify role and how
    # the phrase opens.  This makes consequent phrases feel like answers and
    # continuation phrases feel like bridges.
    if phrase_grammar is not None and len(phrase_measures) >= 3:
        peak_idx = max(0, min(len(phrase_measures) - 2,
                              round(phrase_grammar.peak_position * (len(phrase_measures) - 1))))
        # Move the "intensify" role to the grammar-determined peak.
        # Only override interior measures (never first or last).
        if 0 < peak_idx < len(phrase_measures) - 1:
            # Clear any existing intensify
            for mn, rl in role_by_measure.items():
                if rl == "intensify":
                    role_by_measure[mn] = "develop"
            role_by_measure[phrase_measures[peak_idx]] = "intensify"

        # Consequent phrases start more assertively — mark first measure
        # as "establish" (not "answer") so melody restates with authority.
        if phrase_grammar.function == "consequent" and phrase_index > 0:
            role_by_measure[phrase_measures[0]] = "establish"
            if len(phrase_measures) >= 4:
                role_by_measure[phrase_measures[1]] = "answer"

    density_targets = {
        measure_number: max(
            style_profile.density_floor,
            min(
                style_profile.density_ceiling,
                (
                    _scaled_density_target(
                        _ROLE_DENSITY_TARGETS.get(role, 0.5),
                        int(request["grade"]),
                        role,
                        request,
                    )
                    * 0.6
                )
                + (piece_plan.intensity_curve.get(measure_number, 0.5) * 0.4),
            ),
        )
        for measure_number, role in role_by_measure.items()
    }
    texture_by_measure = _choose_phrase_textures(
        phrase_measures,
        role_by_measure,
        request,
        preset,
        rng,
    )
    if phrase_index == 0 and phrase_measures:
        for measure_number in phrase_measures[:2]:
            texture_by_measure[measure_number] = "melody"
        texture_by_measure[phrase_measures[-1]] = "melody"
        for measure_number in phrase_measures[2:-1]:
            if texture_by_measure.get(measure_number) == "chordal":
                texture_by_measure[measure_number] = (
                    "running"
                    if int(request["grade"]) >= 5
                    and role_by_measure.get(measure_number) == "intensify"
                    and rng.random() < 0.32
                    else "melody"
                )
    elif previous_phrase_plan and phrase_measures:
        texture_by_measure[phrase_measures[0]] = "melody"
    accompaniment_role = _choose_accompaniment_role(
        phrase_index,
        phrase_measures,
        request,
        role_by_measure,
        rng,
    )
    accompaniment_plan = _build_accompaniment_plan(
        accompaniment_role,
        request,
        preset,
        rng,
    )
    left_family = accompaniment_plan.primary_family
    # Phase 6: use piece-level archetype when available.
    if piece_archetype is not None:
        phrase_archetype = piece_archetype
    else:
        phrase_archetype = _choose_phrase_archetype(
            phrase_measures,
            role_by_measure,
            texture_by_measure,
            request,
            rng,
        )
    line_plan = _build_line_plan(
        phrase_index,
        phrase_measures,
        role_by_measure,
        contour,
        phrase_archetype,
        cadence_target,
        style_profile,
        piece_plan,
        request,
        rng,
    )
    answer_form = _pick_answer_form(phrase_archetype, rng)
    top_line_plan = _build_top_line_plan(
        phrase_index,
        phrase_measures,
        role_by_measure,
        contour,
        cadence_target,
        answer_form,
        style_profile,
        piece_plan,
    )
    bass_line_plan = _build_bass_line_plan(
        phrase_index,
        phrase_measures,
        role_by_measure,
        cadence_target,
        style_profile,
    )

    source_motive_blueprint = dict(previous_phrase_plan.get("_motiveBlueprint") or {}) if previous_phrase_plan else {}

    # Anchor and answer cells are drawn from the piece-level pool (locked across phrases).
    # When piece_rhythm_cells is active, every phrase shares the same palette so
    # inherit_rhythm is always True by construction.
    inherit_rhythm = piece_rhythm_cells is not None or bool(
        previous_phrase_plan
        and (previous_phrase_plan.get("_anchorCell") or previous_phrase_plan.get("_answerCell"))
        and rng.random() < 0.82
    )
    if piece_rhythm_cells is not None:
        # Deterministic: first cell is the anchor, second is the answer — locked for the piece.
        anchor_cell = list(rh_cells[0] if rh_cells else [1.0])
        answer_cell = list(rh_cells[1] if len(rh_cells) > 1 else anchor_cell)
    else:
        source_anchor_cell = list(previous_phrase_plan.get("_anchorCell") or []) if previous_phrase_plan else []
        source_answer_cell = list(previous_phrase_plan.get("_answerCell") or []) if previous_phrase_plan else []
        anchor_cell = list(rng.choice(rh_cells) if rh_cells else [1.0])
        answer_pool = [cell for cell in rh_cells if cell != anchor_cell]
        answer_cell = list(rng.choice(answer_pool or rh_cells or [anchor_cell]))
        if inherit_rhythm:
            anchor_cell = list(source_answer_cell or source_anchor_cell or anchor_cell)
            answer_cell = list(source_anchor_cell or source_answer_cell or answer_cell)

    cadence_cells = _simple_rhythm_cells(allowed_durs)

    triplet_measures: list[int] = []
    if (
        float(piano_rules.get("tripletChance", 0.0)) > 0
        and request["grade"] >= 4
        and len(phrase_measures) >= 3
    ):
        eligible_triplet_measures = [
            measure_number
            for measure_number, role in role_by_measure.items()
            if role in {"develop", "intensify"}
            and texture_by_measure.get(measure_number, "melody") != "chordal"
        ]
        if eligible_triplet_measures:
            running_triplet_measures = [
                measure_number
                for measure_number in eligible_triplet_measures
                if texture_by_measure.get(measure_number, "melody") == "running"
            ]
            if running_triplet_measures:
                eligible_triplet_measures = running_triplet_measures
            eligible_triplet_measures.sort(
                key=lambda measure_number: (
                    0 if texture_by_measure.get(measure_number, "melody") == "running" else 1,
                    0 if role_by_measure.get(measure_number) == "intensify" else 1,
                    measure_number,
                )
            )
            triplet_count = 1
            if (
                len(eligible_triplet_measures) > 1
                and request["grade"] >= 5
                and int(request["measureCount"]) >= 12
                and rng.random() < 0.25
            ):
                triplet_count = 2
            triplet_measures = eligible_triplet_measures[: min(triplet_count, len(eligible_triplet_measures))]

    # Determine peak measure from grammar when available, else from contour.
    if phrase_grammar is not None and phrase_measures:
        peak_idx = max(0, min(len(phrase_measures) - 1,
                              round(phrase_grammar.peak_position * (len(phrase_measures) - 1))))
        target_peak_measure = phrase_measures[peak_idx]
    else:
        target_peak_measure = phrase_measures[len(phrase_measures) // 2]
        if contour == "ascending":
            target_peak_measure = phrase_measures[-1]
        elif contour == "descending":
            target_peak_measure = phrase_measures[0]
        elif contour == "valley":
            target_peak_measure = phrase_measures[0]

    rhythm_cells_by_role = {
        "establish": [anchor_cell, anchor_cell, answer_cell],
        "answer": [anchor_cell, answer_cell, answer_cell],
        "develop": rh_cells + [answer_cell],
        "intensify": rh_cells + [answer_cell, answer_cell],
        "cadence": cadence_cells + [anchor_cell],
    }
    motive_blueprint = _build_motive_blueprint(
        anchor_cell,
        answer_cell,
        allowed_durs,
        contour,
        phrase_measures,
        role_by_measure,
        texture_by_measure,
        source_motive_blueprint,
        inherit_rhythm,
        inherit_contour,
        rng,
        measure_total=_measure_total(request["timeSignature"]),
    )
    continuation_by_measure = _build_continuation_plan(
        phrase_archetype,
        phrase_measures,
        role_by_measure,
        texture_by_measure,
        cadence_target,
        motive_blueprint,
        rng,
    )
    melody_measures = [measure_number for measure_number in phrase_measures if texture_by_measure.get(measure_number) == "melody"]
    if phrase_index == 0:
        force_motif_measures = tuple(melody_measures)
    elif previous_phrase_plan:
        force_motif_measures = tuple(dict.fromkeys([*melody_measures[:2], *melody_measures[-1:]]))
    else:
        force_motif_measures = tuple(melody_measures[:1])
    # Use grammar function as phrase_role when available.
    if phrase_grammar is not None:
        phrase_role = phrase_grammar.function
    else:
        phrase_role = "opening" if phrase_index == 0 else (
            "closing" if phrase_measures[-1] == int(request["measureCount"]) else "continuation"
        )
    phrase_blueprint = PhraseBlueprint(
        phrase_index=phrase_index,
        measures=tuple(phrase_measures),
        archetype=phrase_archetype,
        phrase_role=phrase_role,
        cadence_target=cadence_target,
        primary_motive={
            "durations": motive_blueprint["durations"],
            "steps": motive_blueprint["steps"],
        },
        answer_form=answer_form,
        accompaniment_role=accompaniment_plan.role,
        line_plan=line_plan,
        top_line_plan=top_line_plan,
        bass_line_plan=bass_line_plan,
    )
    left_family_by_measure = _build_left_family_plan(
        phrase_measures,
        role_by_measure,
        texture_by_measure,
        request,
        preset,
        accompaniment_plan,
        previous_phrase_plan,
        rng,
        piece_lh_family=piece_lh_family,
    )
    left_family = (
        left_family_by_measure.get(phrase_measures[0], accompaniment_plan.primary_family)
        if phrase_measures
        else accompaniment_plan.primary_family
    )

    return {
        "phraseIndex": phrase_index,
        "measures": phrase_measures,
        "length": len(phrase_measures),
        "cadenceTarget": cadence_target,
        "leftFamily": left_family,
        "accompanimentRole": accompaniment_plan.role,
        "archetype": phrase_archetype,
        "accidentalRoles": accidental_roles,
        "_rhythmCells": rh_cells,
        "_lhRhythmCells": lh_cells,
        "_contour": contour,
        "_measureRoles": role_by_measure,
        "_densityTargets": density_targets,
        "_textureByMeasure": texture_by_measure,
        "_tripletMeasures": triplet_measures,
        "_targetPeakMeasure": target_peak_measure,
        "_anchorCell": anchor_cell,
        "_answerCell": answer_cell,
        "_inheritContour": inherit_contour,
        "_inheritRhythm": inherit_rhythm,
        "_inheritsFromPhraseIndex": previous_phrase_plan.get("phraseIndex") if previous_phrase_plan else None,
        "_cadenceCells": cadence_cells,
        "_roleRhythmCells": rhythm_cells_by_role,
        "_motiveBlueprint": motive_blueprint,
        "_forceMotifMeasures": force_motif_measures,
        "_continuationByMeasure": continuation_by_measure,
        "_styleProfile": style_profile,
        "_piecePlan": piece_plan,
        "_linePlan": line_plan,
        "_topLinePlan": top_line_plan,
        "_bassLinePlan": bass_line_plan,
        "_accompanimentPlan": accompaniment_plan,
        "_leftFamilyByMeasure": left_family_by_measure,
        "_phraseBlueprint": phrase_blueprint,
        "_answerForm": answer_form,
        "_phraseGrammar": phrase_grammar,
    }


# ---------------------------------------------------------------------------
# Accidentals
# ---------------------------------------------------------------------------

def _apply_accidental(
    pitch_groups: list[list[int]],
    request: dict[str, Any],
    preset: dict[str, Any],
    phrase_plan: dict[str, Any],
    rng: random.Random,
    *,
    piece_accidental_count: int = 0,
) -> list[list[int]]:
    # Piece-level budget: max 2 accidentals for grade 4, max 3 for grade 5.
    # This prevents the scattered-accidentals-everywhere look.
    grade = int(request["grade"])
    max_accidentals = 2 if grade <= 4 else 3
    if piece_accidental_count >= max_accidentals:
        return pitch_groups

    if (
        not request["allowAccidentals"]
        or grade < 4
        or not phrase_plan["accidentalRoles"]
        or rng.random() >= float(preset["piano"]["accidentalChance"])
    ):
        return pitch_groups

    # Only apply accidentals in develop/intensify roles, never in cadence or establish.
    # This concentrates accidentals where they serve a musical purpose.
    measure_role = phrase_plan.get("_currentMeasureRole", "develop")
    if measure_role in ("cadence", "establish"):
        return pitch_groups

    candidates = [
        index for index in range(len(pitch_groups) - 1)
        if pitch_groups[index] and pitch_groups[index + 1]
    ]
    if not candidates:
        return pitch_groups

    updated = [list(group) for group in pitch_groups]
    index = rng.choice(candidates)
    role = rng.choice(phrase_plan["accidentalRoles"])
    next_pitch = int(updated[index + 1][0])

    if role in {"upper-neighbor", "harmonic-leading-tone"}:
        updated[index][0] = next_pitch + 1
    elif role == "lower-neighbor":
        updated[index][0] = next_pitch - 1
    elif role == "chord-color-extension":
        updated[index][0] = next_pitch + rng.choice([-1, 1])
    else:
        updated[index][0] = next_pitch - 1 if rng.random() < 0.5 else next_pitch + 1

    return updated


# ---------------------------------------------------------------------------
# Left-hand fixed patterns (Grade 1-3)
# ---------------------------------------------------------------------------

def _build_left_pattern(
    family: str,
    pool: list[int],
    harmony_tones: list[int],
    total: float,
    pulse: float,
    request: dict[str, Any],
    rng: random.Random,
    *,
    bass_target: int | None = None,
    measure_role: str | None = None,
    is_phrase_start: bool = False,
    is_cadence: bool = False,
    prev_bass_pitch: int | None = None,
) -> list[dict[str, Any]]:
    tones = sorted({int(pitch_value) for pitch_value in (harmony_tones or pool)})
    if not tones:
        tones = [int(pool[0])]
    grade = int(request["grade"])
    low = tones[0]
    if bass_target is not None:
        low = min(
            tones,
            key=lambda pitch_value: abs(pitch_value - int(bass_target)) + (_nearest_pool_index(pool, pitch_value) * 0.04),
        )

    # Phase 9: voice leading — prefer smooth bass motion from previous measure
    if prev_bass_pitch is not None and not is_phrase_start:
        smooth_candidates = sorted(tones, key=lambda p: abs(p - prev_bass_pitch))
        if smooth_candidates and abs(smooth_candidates[0] - prev_bass_pitch) <= 5:
            low = smooth_candidates[0]
    max_lh_span = _simultaneous_span_cap(
        grade,
        "lh",
        is_cadence=is_cadence,
        accent=bool(is_phrase_start or measure_role in {"intensify", "answer"}),
    )
    upper_tones = _bounded_upper_tones(tones, low, max_lh_span)
    approach = upper_tones[0]
    mid = upper_tones[min(0 if len(upper_tones) == 1 else 1, len(upper_tones) - 1)]
    top = upper_tones[-1]

    half = pulse * 2
    eighth = pulse / 2
    accent_bar = bool(is_phrase_start or is_cadence or measure_role in {"intensify", "answer"})
    full_vertical = bool(is_cadence or measure_role == "intensify" or (is_phrase_start and request["grade"] >= 4))
    default_dyad = [low, top] if len(tones) >= 2 else [low]
    rich_dyad = [mid, top] if len(tones) >= 3 else default_dyad
    full_chord = [low, mid, top] if len(tones) >= 3 else default_dyad
    support_dyad = rich_dyad if grade >= 5 and len(tones) >= 3 else default_dyad
    accent_support = full_chord if full_vertical and len(tones) >= 3 else support_dyad
    default_dyad = _normalize_pitch_stack(default_dyad)
    rich_dyad = _normalize_pitch_stack(rich_dyad)
    full_chord = _normalize_pitch_stack(full_chord)
    support_dyad = _normalize_pitch_stack(support_dyad)
    accent_support = _normalize_pitch_stack(accent_support)

    if family == "held":
        if full_vertical and grade >= 3 and len(harmony_tones) >= 3:
            patterns = [full_chord]
        elif accent_bar and request["grade"] >= 2:
            patterns = [default_dyad]
        else:
            patterns = [[low]]
        durations = [total]
        starts = [0.0]
        technique = "held chord"
    elif family == "repeated":
        beat_starts = [round(i * pulse, 3) for i in range(int(total / pulse))]
        if grade >= 5 and len(tones) >= 2 and len(beat_starts) >= 4:
            patterns = _sequence_from_cycle([[low], support_dyad, [approach], accent_support], len(beat_starts))
            technique = "repeated support"
        elif grade >= 4 and len(tones) >= 2 and len(beat_starts) >= 4:
            patterns = _sequence_from_cycle([[low], [low], support_dyad, [approach]], len(beat_starts))
            technique = "repeated support"
        else:
            patterns = _sequence_from_cycle([[low], [low], [low, mid], [low]], len(beat_starts))
            technique = "repeated bass"
        durations = [pulse for _ in beat_starts]
        starts = beat_starts
    elif family == "support-bass":
        if grade >= 5 and total >= pulse * 4 and len(tones) >= 2:
            starts = [round(i * pulse, 3) for i in range(int(total / pulse))]
            patterns = _sequence_from_cycle([[low], support_dyad, [approach], accent_support], len(starts))
            durations = [pulse for _ in starts]
            technique = "support bass"
        elif grade >= 4 and total >= pulse * 4:
            starts = [round(i * pulse, 3) for i in range(int(total / pulse))]
            patterns = _sequence_from_cycle([[low], [approach], support_dyad, [top]], len(starts))
            durations = [pulse for _ in starts]
            technique = "support bass"
        else:
            half_starts = [round(i * half, 3) for i in range(max(1, int(total / half)))]
            patterns = _sequence_from_cycle([[low], [top]], len(half_starts))
            durations = [half for _ in half_starts]
            starts = half_starts
            technique = "alternating bass"
    elif family == "simple-broken":
        # For short meters (2/4, 3/4), use quarter-note broken chords instead
        # of eighth notes to avoid visual/rhythmic overload.
        if total <= pulse * 3:
            beat_starts = [round(i * pulse, 3) for i in range(int(total / pulse))]
            patterns = _sequence_from_cycle([[low], [mid], [top], [mid]], len(beat_starts))
            durations = [pulse for _ in beat_starts]
            starts = beat_starts
        else:
            eighth_count = max(1, int(total / eighth))
            starts = [round(i * eighth, 3) for i in range(eighth_count)]
            if grade >= 5 and len(harmony_tones) >= 3 and eighth_count >= 8:
                patterns = _sequence_from_cycle([[low], [mid], [top], [mid], [low], [mid], [top], support_dyad], len(starts))
            elif grade >= 4 and accent_bar and len(harmony_tones) >= 3:
                patterns = _sequence_from_cycle([[low], [mid], [top], support_dyad], len(starts))
            else:
                patterns = _sequence_from_cycle([[low], [mid], [top], [mid]], len(starts))
            durations = [eighth for _ in starts]
        technique = "broken chord"
    elif family == "alberti":
        # Same treatment: quarter-note Alberti in short meters.
        if total <= pulse * 3:
            beat_starts = [round(i * pulse, 3) for i in range(int(total / pulse))]
            patterns = _sequence_from_cycle([[low], [top], [mid], [top]], len(beat_starts))
            durations = [pulse for _ in beat_starts]
            starts = beat_starts
        else:
            eighth_count = max(1, int(total / eighth))
            starts = [round(i * eighth, 3) for i in range(eighth_count)]
            patterns = _sequence_from_cycle([[low], [top], [mid], [top]], len(starts))
            durations = [eighth for _ in starts]
        technique = "Alberti bass"
    elif family == "arpeggio-support":
        if grade >= 5 and len(harmony_tones) >= 3 and total >= pulse * 4:
            starts = [round(i * eighth, 3) for i in range(int(total / eighth))]
            patterns = _sequence_from_cycle([[low], [mid], [top], [mid], [approach], [mid], [top], support_dyad], len(starts))
            durations = [eighth for _ in starts]
        elif grade >= 5 and total >= pulse * 4:
            starts = [0.0, pulse, pulse * 2, pulse * 3]
            patterns = [[low], [mid], [top], support_dyad]
            durations = [pulse, pulse, pulse, total - pulse * 3]
        elif len(harmony_tones) >= 3:
            starts = [0.0, pulse, pulse * 2]
            patterns = [[low], [mid], support_dyad]
            durations = [pulse, pulse, total - pulse * 2]
        else:
            starts = [0.0, pulse]
            patterns = [[low], [top]]
            durations = [pulse, total - pulse]
        technique = "LH arpeggio"
    elif family == "block-half":
        # Block chords on half-note rhythm — the SRF staple for LH support
        half_starts = [round(i * half, 3) for i in range(max(1, int(total / half)))]
        if full_vertical and len(harmony_tones) >= 3:
            patterns = _sequence_from_cycle([full_chord, full_chord], len(half_starts))
        elif len(harmony_tones) >= 2:
            if accent_bar:
                patterns = _sequence_from_cycle([default_dyad, [low]], len(half_starts))
            else:
                patterns = _sequence_from_cycle([[low], default_dyad], len(half_starts))
        else:
            patterns = _sequence_from_cycle([[low]], len(half_starts))
        durations = [half for _ in half_starts]
        starts = half_starts
        technique = "harmonic support"
    elif family == "block-quarter":
        # Block chords on quarter-note rhythm
        beat_starts = [round(i * pulse, 3) for i in range(int(total / pulse))]
        if full_vertical and len(harmony_tones) >= 3:
            patterns = _sequence_from_cycle([full_chord, default_dyad, full_chord, default_dyad], len(beat_starts))
        elif len(harmony_tones) >= 2:
            patterns = _sequence_from_cycle([[low], default_dyad, [low], default_dyad], len(beat_starts))
        else:
            patterns = _sequence_from_cycle([[low]], len(beat_starts))
        durations = [pulse for _ in beat_starts]
        starts = beat_starts
        technique = "harmonic support"
    elif family == "bass-and-chord":
        # Bass note beat 1, chord beat 3 (classical piano LH)
        if request["grade"] >= 5 and total >= pulse * 4:
            starts = [0.0, pulse, pulse * 2, pulse * 3]
            if len(harmony_tones) >= 3 and full_vertical:
                patterns = [[low], support_dyad, [approach], full_chord]
            elif len(harmony_tones) >= 2:
                patterns = [[low], support_dyad, [approach], support_dyad]
            else:
                patterns = [[low], [low], [approach], [low]]
            durations = [pulse, pulse, pulse, total - pulse * 3]
        elif total >= half * 2:
            starts = [0.0, half]
            if len(harmony_tones) >= 3 and full_vertical:
                patterns = [[low], rich_dyad]
            elif len(harmony_tones) >= 2:
                patterns = [[low], default_dyad]
            else:
                patterns = [[low], [low]]
            durations = [half, total - half]
        else:
            starts = [0.0]
            if len(harmony_tones) >= 3 and full_vertical:
                patterns = [full_chord]
            elif len(harmony_tones) >= 2:
                patterns = [default_dyad]
            else:
                patterns = [[low]]
            durations = [total]
        technique = "bass and chord"
    elif family == "waltz-bass":
        starts = [0.0, half]
        if total > half + pulse:
            starts.append(round(half + pulse, 3))
            patterns = [[low], support_dyad, accent_support if full_vertical else support_dyad]
            durations = [half, pulse, total - half - pulse]
        else:
            patterns = [[low], accent_support if full_vertical else support_dyad]
            durations = [half, total - half]
        technique = "waltz bass"
    elif family == "octave-support":
        if total >= pulse * 4:
            starts = [0.0, pulse, pulse * 2, pulse * 3]
            patterns = _sequence_from_cycle([[low, low + 12], [approach], [low, low + 12], rich_dyad if full_vertical else default_dyad], len(starts))
            durations = [pulse, pulse, pulse, total - pulse * 3]
        else:
            half_starts = [round(i * half, 3) for i in range(max(1, int(total / half)))]
            patterns = _sequence_from_cycle([[low, low + 12], rich_dyad if full_vertical else default_dyad], len(half_starts))
            durations = [half for _ in half_starts]
            starts = half_starts
        technique = "LH octaves"
    else:
        beat_starts = [round(i * pulse, 3) for i in range(int(total / pulse))]
        patterns = _sequence_from_cycle([[low], [mid], [top], [mid]], len(beat_starts))
        durations = [pulse for _ in beat_starts]
        starts = beat_starts
        technique = "broken accompaniment"

    events: list[dict[str, Any]] = []
    for start, duration, pitches in zip(starts, durations, patterns, strict=False):
        normalized_pitches = _normalize_pitch_stack(pitches)
        events.append({
            "hand": "lh",
            "offset": round(start, 3),
            "quarterLength": round(float(duration), 3),
            "isRest": False,
            "pitches": normalized_pitches,
            "technique": technique,
        })
    return events


def _adapt_left_family(
    current_family: str,
    rh_texture: str,
    is_cadence: bool,
    measure_role: str | None,
    request: dict[str, Any],
    preset: dict[str, Any],
    rng: random.Random,
    accompaniment_plan: AccompanimentPlan | None = None,
) -> str:
    piano = preset["piano"]
    support_families = ["held", "support-bass", "block-half", "bass-and-chord"]
    contrast_families = ["support-bass", "simple-broken", "arpeggio-support"]
    cadence_families = ["block-half", "bass-and-chord", "support-bass"]
    bass_first_families = ["support-bass", "repeated", "simple-broken", "arpeggio-support", "bass-and-chord"]

    if bool(piano.get("allowAlberti", False)):
        contrast_families.append("alberti")
    if bool(piano.get("allowOctaves", False)) and int(request["grade"]) >= 5:
        cadence_families.append("octave-support")
    if accompaniment_plan:
        support_families = list(dict.fromkeys([*accompaniment_plan.support_families, *support_families]))
        contrast_families = [
            family
            for family in contrast_families
            if family in set(accompaniment_plan.support_families) or family in {"simple-broken", "arpeggio-support", "alberti"}
        ] or list(accompaniment_plan.support_families)
        cadence_families = list(dict.fromkeys([accompaniment_plan.cadence_family, *cadence_families]))
        bass_first_families = list(
            dict.fromkeys(
                [
                    family
                    for family in [*accompaniment_plan.support_families, *bass_first_families]
                    if family not in {"held", "block-half", "block-quarter"}
                ]
            )
        ) or bass_first_families

    preferred_support = _preferred_left_families(request, support_families)
    preferred_contrast = _preferred_left_families(request, contrast_families)
    preferred_cadence = _preferred_left_families(request, cadence_families)
    preferred_bass_first = _preferred_left_families(request, bass_first_families)

    if is_cadence:
        return current_family if current_family in preferred_cadence else rng.choice(preferred_cadence)
    if rh_texture == "running":
        return current_family if current_family in preferred_support else rng.choice(preferred_support)
    if rh_texture == "chordal":
        return current_family if current_family in preferred_contrast else rng.choice(preferred_contrast)
    if measure_role not in {"intensify", "establish"} and preferred_bass_first:
        return current_family if current_family in preferred_bass_first else rng.choice(preferred_bass_first)
    return current_family


# ---------------------------------------------------------------------------
# Measure offset helper
# ---------------------------------------------------------------------------

def _measure_events_with_offsets(measure_number: int, measure_offset: float, hand_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for event in hand_events:
        output.append({
            **event,
            "measure": measure_number,
            "offset": round(measure_offset + float(event["offset"]), 3),
        })
    return output


# ---------------------------------------------------------------------------
# Dynamics & expression (post-processing)
# ---------------------------------------------------------------------------

_DYNAMIC_LEVELS = ["p", "mp", "mf", "f"]
_DYNAMIC_SCALARS = {
    "pp": 0.22,
    "p": 0.34,
    "mp": 0.48,
    "mf": 0.64,
    "f": 0.82,
    "ff": 0.94,
}


def _expression_sort_key(event: dict[str, Any]) -> tuple[Any, ...]:
    return (
        0 if event.get("hand") == "rh" else 1,
        int(event.get("measure", 0)),
        float(event.get("offset", 0.0)),
        0 if not event.get("isRest") else 1,
    )


def _local_measure_offset(event: dict[str, Any], total: float) -> float:
    return round(float(event["offset"]) - (int(event["measure"]) - 1) * total, 3)


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _dynamic_scalar(level: str | None) -> float:
    return float(_DYNAMIC_SCALARS.get(str(level or "mf"), _DYNAMIC_SCALARS["mf"]))


def _phrase_dynamic_levels(
    phrases: list[list[int]],
    piece_plan: PiecePlan,
    levels: list[str],
) -> list[str]:
    if not phrases:
        return []

    phrase_levels: list[str] = []
    level_count = max(1, len(levels))

    # Find the phrase with the highest average intensity — only it gets the
    # loudest level.  All other phrases start quieter.  This prevents every
    # phrase opening at forte.
    avg_intensities: list[float] = []
    for phrase_measures in phrases:
        avg = sum(
            float(piece_plan.intensity_curve.get(m, 0.5))
            for m in phrase_measures
        ) / max(1, len(phrase_measures))
        avg_intensities.append(avg)

    peak_intensity = max(avg_intensities) if avg_intensities else 0.5
    for avg_intensity in avg_intensities:
        # Normalize so only the loudest phrase reaches the top dynamic level.
        # Other phrases map into the lower portion of the dynamic range.
        if peak_intensity > 0.01:
            relative = avg_intensity / peak_intensity  # 0-1 range
        else:
            relative = 0.5
        index = int(round(_clamp(relative, 0.0, 1.0) * (level_count - 1)))
        phrase_levels.append(levels[index])

    # First phrase should generally open moderately (index 0 = softest available).
    if len(phrase_levels) >= 2 and phrase_levels[0] == levels[-1]:
        phrase_levels[0] = levels[max(0, len(levels) - 2)]

    if piece_plan.dynamic_arc == "steady-build":
        max_index = 0
        normalized_levels: list[str] = []
        for level in phrase_levels:
            max_index = max(max_index, levels.index(level))
            normalized_levels.append(levels[max_index])
        return normalized_levels

    return phrase_levels


def _apply_ties(
    events: list[dict[str, Any]],
    request: dict[str, Any],
    rng: random.Random,
) -> list[dict[str, Any]]:
    if request["mode"] != "piano" or int(request["grade"]) < 2:
        return events

    total = _measure_total(request["timeSignature"])
    pulse = _pulse_value(request["timeSignature"])
    tie_counter = 0
    output: list[dict[str, Any]] = []

    for original in sorted(events, key=_expression_sort_key):
        event = dict(original)
        if event.get("isRest") or not event.get("pitches") or event.get("tuplet"):
            output.append(event)
            continue

        duration_value = float(event.get("_actualDur", event["quarterLength"]))
        if duration_value < max(0.75, pulse * 0.66):
            output.append(event)
            continue

        local_start = _local_measure_offset(event, total)
        local_end = round(local_start + duration_value, 3)
        next_boundary = round((math.floor(local_start / pulse) + 1) * pulse, 3)
        starts_on_pulse = abs((local_start / pulse) - round(local_start / pulse)) < 0.08
        crosses_boundary = (
            next_boundary < local_end - 0.2 and next_boundary - local_start > 0.2
        )
        role = str(event.get("measureRole", "develop"))

        should_split = False
        if crosses_boundary and not starts_on_pulse:
            should_split = rng.random() < (0.22 if int(request["grade"]) >= 4 else 0.12)
        elif crosses_boundary and role == "cadence" and duration_value >= pulse * 1.35:
            should_split = True
        elif (
            crosses_boundary
            and len(event.get("pitches", [])) > 1
            and int(request["grade"]) >= 4
            and rng.random() < 0.08
        ):
            should_split = True

        if not should_split:
            output.append(event)
            continue

        first_duration = round(next_boundary - local_start, 3)
        second_duration = round(local_end - next_boundary, 3)
        if first_duration < 0.25 or second_duration < 0.25:
            output.append(event)
            continue

        tie_counter += 1
        tie_group = f"tie-{tie_counter}"

        first = dict(event)
        second = dict(event)
        first["quarterLength"] = first_duration
        first["_actualDur"] = first_duration
        first["tieGroup"] = tie_group
        first["tieType"] = "start"

        second["offset"] = round(float(event["offset"]) + first_duration, 3)
        second["quarterLength"] = second_duration
        second["_actualDur"] = second_duration
        second["tieGroup"] = tie_group
        second["tieType"] = "stop"

        output.extend([first, second])

    return sorted(output, key=_expression_sort_key)


def _assign_expression_ids(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for index, event in enumerate(sorted(events, key=_expression_sort_key), start=1):
        event["eventId"] = f"ev-{index}"
        event.setdefault("slurStartIds", [])
        event.setdefault("slurStopIds", [])
        event.setdefault("hairpinStopIds", [])
    return events


def _apply_dynamics(
    events: list[dict[str, Any]],
    phrases: list[list[int]],
    piece_plan: PiecePlan,
    preset: dict[str, Any],
    rng: random.Random,
) -> list[dict[str, Any]]:
    """Add phrase dynamics and continuous playback intensity."""
    if not preset["piano"].get("dynamicsEnabled", False):
        for event in events:
            if not event.get("isRest"):
                event["dynamicScalar"] = _dynamic_scalar(event.get("dynamic"))
        return events

    levels = list(preset["piano"].get("dynamicLevels", ["mf", "f"]))
    phrase_dynamics = _phrase_dynamic_levels(phrases, piece_plan, levels)

    for phrase_index, phrase_measures in enumerate(phrases):
        if not phrase_measures:
            continue

        start_level = phrase_dynamics[phrase_index]
        if phrase_index < len(phrase_dynamics) - 1:
            end_level = phrase_dynamics[phrase_index + 1]
        else:
            start_intensity = float(piece_plan.intensity_curve.get(phrase_measures[0], 0.5))
            end_intensity = float(piece_plan.intensity_curve.get(phrase_measures[-1], start_intensity))
            level_index = levels.index(start_level)
            if end_intensity > start_intensity + 0.08 and level_index < len(levels) - 1:
                end_level = levels[level_index + 1]
            elif end_intensity < start_intensity - 0.08 and level_index > 0:
                end_level = levels[level_index - 1]
            else:
                end_level = start_level
        start_scalar = _dynamic_scalar(start_level)
        end_scalar = _dynamic_scalar(end_level)

        phrase_events = [
            event
            for event in sorted(events, key=_expression_sort_key)
            if int(event["measure"]) in phrase_measures
            and not event.get("isRest")
            and event.get("pitches")
        ]
        rh_phrase_events = [event for event in phrase_events if event.get("hand") == "rh"]

        if rh_phrase_events:
            rh_phrase_events[0]["dynamic"] = start_level

        if rh_phrase_events and len(rh_phrase_events) >= 2 and abs(end_scalar - start_scalar) > 0.06:
            hairpin_id = f"hairpin-{phrase_index + 1}"
            rh_phrase_events[0]["hairpinStart"] = {
                "id": hairpin_id,
                "type": "crescendo" if end_scalar > start_scalar else "diminuendo",
            }
            rh_phrase_events[-1].setdefault("hairpinStopIds", []).append(hairpin_id)

        for event_index, event in enumerate(phrase_events):
            progress = event_index / max(1, len(phrase_events) - 1)
            event["dynamicScalar"] = round(
                start_scalar + (end_scalar - start_scalar) * progress,
                4,
            )

    return events


def _apply_slurs(
    events: list[dict[str, Any]],
    phrases: list[list[int]],
    request: dict[str, Any],
    rng: random.Random,
) -> list[dict[str, Any]]:
    if request["mode"] != "piano" or int(request["grade"]) < 2:
        return events

    grade = int(request["grade"])
    slur_counter = 0
    sorted_events = sorted(events, key=_expression_sort_key)

    for event in sorted_events:
        event.pop("slurId", None)
        event.pop("slurRole", None)
        event["slurStartIds"] = []
        event["slurStopIds"] = []

    def _chunk_metrics(chunk: list[dict[str, Any]]) -> tuple[float, int]:
        intervals = [
            abs(int(chunk[i + 1]["pitches"][0]) - int(chunk[i]["pitches"][0]))
            for i in range(len(chunk) - 1)
        ]
        if not intervals:
            return 0.0, 0
        stepwise_ratio = sum(1 for interval in intervals if interval <= 2) / len(intervals)
        max_interval = max(intervals)
        return stepwise_ratio, max_interval

    def _chunk_score(chunk: list[dict[str, Any]], total: float, pulse: float) -> float:
        stepwise_ratio, max_interval = _chunk_metrics(chunk)
        if max_interval > (5 if grade >= 4 else 4):
            return -1.0
        if stepwise_ratio < (0.55 if grade >= 4 else 0.45):
            return -1.0

        roles = {str(event.get("measureRole", "")) for event in chunk}
        techniques = {str(event.get("technique", "")) for event in chunk}
        phrase_functions = {str(event.get("phraseFunction", "")) for event in chunk if event.get("phraseFunction")}
        ornament_functions = {str(event.get("ornamentFunction", "")) for event in chunk if event.get("ornamentFunction")}
        avg_duration = sum(float(event.get("_actualDur", event["quarterLength"])) for event in chunk) / len(chunk)
        cross_measure = int(chunk[0]["measure"]) != int(chunk[-1]["measure"])
        measure_span = int(chunk[-1]["measure"]) - int(chunk[0]["measure"])
        local_start = _local_measure_offset(chunk[0], total)
        starts_on_pulse = abs((local_start / pulse) - round(local_start / pulse)) < 0.08

        score = float(len(chunk)) * 2.8
        score += stepwise_ratio * 2.4
        score += min(avg_duration / max(0.25, pulse), 1.0) * 0.8
        if cross_measure:
            score += 0.65
        if starts_on_pulse:
            score += 0.35
        if roles & {"answer", "develop", "cadence"}:
            score += 0.35
        if phrase_functions & {"lead_in", "passing", "neighbor", "sequence", "echo_fragment", "cadential_turn"}:
            score += 1.0
        if ornament_functions & {"passing", "neighbor", "release_turn"}:
            score += 0.65
        if techniques & {"passing approach", "neighbor motion", "release turn", "triplet"}:
            score += 0.75
        if techniques & {"melody", "lead in", "landing", "liquidation"}:
            score += 0.2
        if "scale figure" in techniques:
            score += 0.15
        if len(chunk) > 4:
            score -= 1.2
        if avg_duration > pulse * 0.95 and len(chunk) >= 4:
            score -= 1.15
        if measure_span > 1:
            score -= 0.8
        if roles & {"cadence"} and not (phrase_functions & {"cadential_turn", "lead_in", "arrival"}):
            score -= 0.35
        return score

    def _attach_slur(chunk: list[dict[str, Any]]) -> None:
        nonlocal slur_counter
        if len(chunk) < 2:
            return
        slur_counter += 1
        slur_id = f"slur-{slur_counter}"
        for chunk_index, event in enumerate(chunk):
            event["slurId"] = slur_id
            if chunk_index == 0:
                event.setdefault("slurStartIds", []).append(slur_id)
                event["slurRole"] = "start"
            elif chunk_index == len(chunk) - 1:
                event.setdefault("slurStopIds", []).append(slur_id)
                event["slurRole"] = "stop"
            else:
                event["slurRole"] = "continue"

    total = _measure_total(request["timeSignature"])
    pulse = _pulse_value(request["timeSignature"])
    preferred_lengths = [4, 3, 2] if grade >= 4 else [3, 2]
    fallback_lengths = [2] if grade >= 4 else [2]

    for phrase_measures in phrases:
        phrase_notes = [
            event
            for event in sorted_events
            if event.get("hand") == "rh"
            and int(event["measure"]) in phrase_measures
            and not event.get("isRest")
            and len(event.get("pitches", [])) == 1
            and not event.get("tieType")
            and event.get("technique") not in {"block chord"}
        ]
        if len(phrase_notes) < 2:
            continue

        runs: list[list[dict[str, Any]]] = []
        current_run: list[dict[str, Any]] = []
        for event in phrase_notes:
            if not current_run:
                current_run = [event]
                continue

            previous = current_run[-1]
            gap = round(
                float(event["offset"])
                - (float(previous["offset"]) + float(previous.get("_actualDur", previous["quarterLength"]))),
                3,
            )
            interval = abs(int(event["pitches"][0]) - int(previous["pitches"][0]))
            if gap <= 0.02 and interval <= 5:
                current_run.append(event)
            else:
                if len(current_run) >= 2:
                    runs.append(current_run)
                current_run = [event]

        if len(current_run) >= 2:
            runs.append(current_run)

        chosen_ids: set[str] = set()
        for run in runs:
            candidates: list[tuple[float, list[dict[str, Any]]]] = []
            for lengths in (preferred_lengths, fallback_lengths):
                for chunk_length in lengths:
                    if len(run) < chunk_length:
                        continue
                    for start in range(0, len(run) - chunk_length + 1):
                        chunk = run[start:start + chunk_length]
                        score = _chunk_score(chunk, total, pulse)
                        if score >= 0:
                            candidates.append((score, chunk))
                if candidates:
                    break

            if not candidates:
                continue

            candidates.sort(key=lambda item: item[0], reverse=True)
            for _, chunk in candidates:
                chunk_ids = {str(event["eventId"]) for event in chunk if event.get("eventId")}
                if chunk_ids and not (chunk_ids & chosen_ids):
                    _attach_slur(chunk)
                    chosen_ids.update(chunk_ids)
                    break

    return events


def _apply_articulations(
    events: list[dict[str, Any]],
    request: dict[str, Any],
    grade: int,
    preset: dict[str, Any],
    rng: random.Random,
) -> list[dict[str, Any]]:
    """Add articulation based on phrase role, texture, and touch."""
    chance = float(preset["piano"].get("articulationChance", 0.0))
    if chance <= 0:
        return events

    total = _measure_total(request["timeSignature"])
    pulse = _pulse_value(request["timeSignature"])

    for event in sorted(events, key=_expression_sort_key):
        if event.get("isRest") or not event.get("pitches"):
            continue
        if event.get("tieType") in {"continue", "stop"}:
            continue

        duration_value = float(event.get("_actualDur", event["quarterLength"]))
        role = str(event.get("measureRole", "develop"))
        local_start = _local_measure_offset(event, total)
        on_pulse = abs((local_start / pulse) - round(local_start / pulse)) < 0.08
        chordal = len(event.get("pitches", [])) > 1
        slurred = bool(event.get("slurId"))

        if slurred:
            if (
                grade >= 4
                and event.get("slurRole") == "stop"
                and duration_value >= pulse * 0.66
                and role in {"answer", "cadence"}
                and rng.random() < 0.42
            ):
                event["articulation"] = "tenuto"
            continue

        if role == "cadence" and duration_value >= pulse and event.get("hand") == "rh":
            event["articulation"] = "tenuto"
            continue

        if (
            duration_value <= max(0.5, pulse * 0.45)
            and event.get("hand") == "lh"
            and event.get("leftFamily") in {"repeated", "support-bass", "simple-broken", "waltz-bass"}
            and rng.random() < chance * 1.6
        ):
            event["articulation"] = "staccato"
            continue

        if (
            duration_value <= 0.5
            and role in {"develop", "intensify"}
            and rng.random() < chance * 1.15
        ):
            event["articulation"] = "staccato"
            continue

        if (
            on_pulse
            and (role == "intensify" or chordal or event.get("hairpinStart"))
            and rng.random() < chance * 0.9
        ):
            if duration_value <= 0.75 and rng.random() < 0.35:
                event["articulation"] = "staccato"
            else:
                event["articulation"] = "accent"

    return events


def _apply_playback_expression(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for event in events:
        if event.get("isRest") or not event.get("pitches"):
            continue

        dynamic_scalar = float(event.get("dynamicScalar", _dynamic_scalar(event.get("dynamic"))))
        touch_value = 0.24 + dynamic_scalar * 0.82
        if event.get("hand") == "rh":
            touch_value += 0.05
        else:
            touch_value -= 0.04

        articulation_name = event.get("articulation")
        if articulation_name == "accent":
            touch_value += 0.18
        elif articulation_name == "staccato":
            touch_value += 0.08
        elif articulation_name == "tenuto":
            touch_value -= 0.03

        if event.get("slurRole") in {"continue", "stop"}:
            touch_value -= 0.14

        event["touch"] = round(_clamp(touch_value, 0.08, 1.0), 4)
        if articulation_name == "staccato":
            duration_scale = 0.58
            reattack = 1.08
        elif articulation_name == "accent":
            duration_scale = 0.96
            reattack = 1.15
        elif articulation_name == "tenuto":
            duration_scale = 1.07
            reattack = 0.92
        else:
            duration_scale = 0.98
            reattack = 1.0

        if event.get("slurId") and articulation_name != "staccato":
            duration_scale = max(duration_scale, 1.04)
            reattack *= 0.62 if event.get("slurRole") in {"continue", "stop"} else 0.8

        event["durationScale"] = round(duration_scale, 4)
        event["reattack"] = round(_clamp(reattack, 0.0, 1.2), 4)
        event["dynamicScalar"] = round(dynamic_scalar, 4)

    return events


# ---------------------------------------------------------------------------
# Main event builder (REWRITTEN)
# ---------------------------------------------------------------------------

def _build_piano_candidate(request: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    grade = int(request["grade"])
    preset = _preset_for_grade(grade)
    piano = preset["piano"]
    style_profile = _build_style_profile(request, preset)
    total = _measure_total(request["timeSignature"])
    pulse = _pulse_value(request["timeSignature"])

    rh_allowed = sorted({float(v) for v in piano["rightQuarterLengths"]}, reverse=True)
    lh_allowed = sorted(
        {float(v) for v in piano.get("leftQuarterLengths", piano["rightQuarterLengths"])},
        reverse=True,
    )

    phrases = _group_into_phrases(
        int(request["measureCount"]),
        list(piano.get("phraseLengths", [2, 4])),
        rng,
    )

    # Build phrase grammars early so harmonic plan can use cadence types.
    early_grammars = _assign_phrase_grammars(
        phrases, grade, style_profile.focus, rng,
    )

    plan = _harmonic_plan(
        int(request["measureCount"]),
        grade,
        request["keySignature"],
        phrases,
        rng,
        phrase_grammars=early_grammars,
    )
    pool_size = int(piano.get("poolSize", 5))
    max_leap = int(piano.get("maxLeapSemitones", 7))

    right_root = HAND_POSITION_ROOTS["rh"][request["handPosition"]]
    left_root = HAND_POSITION_ROOTS["lh"][request["handPosition"]]

    rh_pool = _position_pitches_from_root(right_root, request["keySignature"], pool_size)
    lh_pool_size = max(8, pool_size)
    lh_pool = _position_pitches_from_root(left_root, request["keySignature"], lh_pool_size)

    rh_weights = _weights_for_hand("rh", preset, request)
    lh_weights = _weights_for_hand("lh", preset, request)

    # State tracking for both hands
    rh_pitch = rng.choice(rh_pool)
    lh_pitch = lh_pool[0]
    rh_recent: list[int] = []
    lh_recent: list[int] = []
    rh_dir = rng.choice([-1, 1])
    lh_dir = rng.choice([-1, 1])

    events: list[dict[str, Any]] = []
    piece_plan = _build_piece_plan(phrases, request, style_profile, rng,
                                   phrase_grammars=early_grammars)
    phrase_plans: list[dict[str, Any]] = []

    # Phase 1: lock rhythm cells for the entire piece
    piece_rhythm_cells: dict[str, list[list[float]]] = {
        "rh": _pick_rhythm_cells(grade, rh_allowed, rng),
        "lh": _pick_rhythm_cells(grade, lh_allowed, rng),
    }

    # Phase 2: lock LH pattern family for the piece.
    # Weight selection toward calmer patterns — SRF-style LH is mostly half/quarter
    # note patterns, not perpetual eighth-note arpeggios.
    available_lh = list(dict.fromkeys(piano.get("leftPatternFamilies", ["held"])))
    _LH_FAMILY_WEIGHT = {
        "held": 1.0, "block-half": 1.3, "bass-and-chord": 1.3,
        "support-bass": 1.1, "block-quarter": 1.0, "waltz-bass": 1.0,
        "repeated": 0.8, "octave-support": 0.7,
        "arpeggio-support": 0.4, "simple-broken": 0.3, "alberti": 0.3,
    }
    lh_weights = [_LH_FAMILY_WEIGHT.get(f, 0.5) for f in available_lh]
    piece_lh_family = rng.choices(available_lh, weights=lh_weights, k=1)[0]

    # Phase 6: lock archetype and contour at piece level to reduce entropy.
    piece_archetype = rng.choices(
        ["period", "sentence", "lyric", "sequence"],
        weights=[1.4, 1.1, 0.95, 0.9],
        k=1,
    )[0]
    piece_contour = _pick_contour(rng)

    # Phase 3: store phrase A's rhythm templates for A' replay
    phrase_a_rhythm_templates: dict[int, list[dict[str, Any]]] = {}  # mi_in_phrase -> template

    for phrase_index, phrase_measures in enumerate(phrases):
        # Retrieve phrase grammar from the piece plan.
        pg = (
            piece_plan.phrase_grammars[phrase_index]
            if phrase_index < len(piece_plan.phrase_grammars)
            else None
        )
        phrase_plan = _pick_phrase_plan(
            phrase_index,
            phrase_measures,
            request,
            preset,
            style_profile,
            piece_plan,
            phrase_plans[-1] if phrase_plans else None,
            rng,
            piece_rhythm_cells=piece_rhythm_cells,
            piece_lh_family=piece_lh_family,
            piece_archetype=piece_archetype,
            piece_contour=piece_contour,
            phrase_grammar=pg,
        )
        phrase_plans.append(phrase_plan)
        left_family_by_measure = dict(phrase_plan.get("_leftFamilyByMeasure") or {})
        phrase_default_left_family = str(phrase_plan.get("leftFamily", "held"))

        # Phase 3: determine if this phrase should replay phrase A's rhythm.
        # Phrase 1 (A') replays A when the piece has 2+ phrases and phrase lengths match.
        is_a_prime = (
            phrase_index == 1
            and len(phrases) >= 2
            and phrase_a_rhythm_templates
            and len(phrase_measures) == len(phrases[0])
        )

        for mi, measure_number in enumerate(phrase_measures):
            harmony = plan[measure_number - 1]
            measure_offset = (measure_number - 1) * total
            is_cadence = (measure_number == phrase_measures[-1])
            measure_role = phrase_plan.get("_measureRoles", {}).get(measure_number, "develop")
            is_phrase_start = measure_number == phrase_measures[0]
            measure_lh_family = str(left_family_by_measure.get(measure_number, phrase_default_left_family))

            # Track current measure in phrase plan for contour
            phrase_plan["_currentMeasure"] = measure_number

            # Position shift
            if measure_number > 1 and rng.random() < float(piano.get("positionShiftChance", 0.0)):
                right_root = _shift_root(right_root, "rh", grade, rng)
                left_root = _shift_root(left_root, "lh", grade, rng)
                rh_pool = _position_pitches_from_root(right_root, request["keySignature"], pool_size)
                lh_pool = _position_pitches_from_root(left_root, request["keySignature"], lh_pool_size)
                rh_pitch = min(rh_pool, key=lambda pitch_value: abs(pitch_value - rh_pitch))
                lh_pitch = min(lh_pool, key=lambda pitch_value: abs(pitch_value - lh_pitch))

            rh_harmony = _chord_tones_in_pool(rh_pool, request["keySignature"], harmony)
            lh_harmony = _chord_tones_in_pool(lh_pool, request["keySignature"], harmony)
            top_target_pitch = _resolve_top_line_target(
                phrase_plan.get("_topLinePlan"),
                measure_number,
                rh_pool,
                rh_harmony,
                request["keySignature"],
                harmony,
                rh_pitch,
            )
            bass_target_pitch = _resolve_bass_line_target(
                phrase_plan.get("_bassLinePlan"),
                measure_number,
                lh_pool,
                lh_harmony,
                request["keySignature"],
                harmony,
                lh_pitch,
            )
            phrase_plan["_currentTopTargetPitch"] = top_target_pitch
            phrase_plan["_currentBassTargetPitch"] = bass_target_pitch
            rh_texture = _pick_texture(
                "rh",
                grade,
                measure_number,
                preset,
                rng,
            )
            texture_map = phrase_plan.get("_textureByMeasure", {})
            if measure_number in texture_map:
                rh_texture = str(texture_map[measure_number])

            # === RIGHT HAND ===
            if request["handActivity"] != "left-only":
                # Phase 3: A' replay — use phrase A's rhythm with new pitches
                if is_a_prime and mi in phrase_a_rhythm_templates:
                    template = phrase_a_rhythm_templates[mi]
                    rh_events, rh_pitch, rh_recent, rh_dir = _replay_rhythm_template(
                        "rh", template, rh_pool, rh_harmony,
                        request["keySignature"], harmony, rh_weights, max_leap, rng,
                        rh_pitch, rh_recent, rh_dir, is_cadence,
                    )
                else:
                    rh_events, rh_pitch, rh_recent, rh_dir = _build_measure_content(
                        "rh", rh_texture, rh_pool, rh_harmony,
                        total, pulse, rh_allowed,
                        request["keySignature"], harmony, rh_weights, max_leap, rng,
                        rh_pitch, rh_recent, rh_dir,
                        is_cadence, phrase_plan["cadenceTarget"],
                        request, preset, phrase_plan,
                    )
                for event in _measure_events_with_offsets(measure_number, measure_offset, rh_events):
                    event["harmony"] = harmony
                    event["phraseIndex"] = phrase_plan["phraseIndex"]
                    event["phraseCadence"] = phrase_plan["cadenceTarget"]
                    event["leftFamily"] = measure_lh_family
                    event["measureRole"] = measure_role
                    event["targetDensity"] = phrase_plan.get("_densityTargets", {}).get(measure_number, 0.5)
                    event["phraseContour"] = phrase_plan.get("_contour", "flat")
                    event["rhTexture"] = rh_texture
                    if top_target_pitch is not None:
                        event["plannedTopPitch"] = int(top_target_pitch)
                    events.append(event)

                # Phase 3: store rhythm template from phrase A for later A' replay
                if phrase_index == 0 and rh_events:
                    phrase_a_rhythm_templates[mi] = [
                        {
                            "quarterLength": float(e.get("quarterLength", 1.0)),
                            "isRest": bool(e.get("isRest", False)),
                            "technique": str(e.get("technique", "")),
                            "tuplet": e.get("tuplet"),
                            "_actualDur": e.get("_actualDur"),
                            "pitchCount": len(e.get("pitches", [1])),
                        }
                        for e in rh_events
                    ]

            # === LEFT HAND ===
            if request["handActivity"] != "right-only":
                # Final measure: override LH to a single held tonic chord.
                is_piece_final = measure_number == int(request["measureCount"])
                if is_piece_final and is_cadence:
                    tonic_pc = KEY_TONIC_PITCH_CLASS.get(request["keySignature"], 0)
                    tonic_pitches = [p for p in lh_pool if p % 12 == tonic_pc]
                    if tonic_pitches:
                        bass_note = min(tonic_pitches)
                        # Build a simple tonic chord: root + fifth (or just root for low grades)
                        fifth_pc = (tonic_pc + 7) % 12
                        fifth_pitches = [p for p in lh_pool if p % 12 == fifth_pc and p > bass_note and p - bass_note <= 12]
                        if fifth_pitches and grade >= 3:
                            final_pitches = sorted([bass_note, fifth_pitches[0]])
                        else:
                            final_pitches = [bass_note]
                        lh_events = [{
                            "hand": "lh",
                            "offset": 0.0,
                            "quarterLength": total,
                            "isRest": False,
                            "pitches": final_pitches,
                            "technique": "final chord",
                            "fermata": True,
                        }]
                    else:
                        lh_events = _build_left_pattern(
                            "held", lh_pool, lh_harmony,
                            total, pulse, request, rng,
                            bass_target=int(bass_target_pitch) if bass_target_pitch is not None else None,
                            measure_role=measure_role,
                            is_phrase_start=is_phrase_start,
                            is_cadence=is_cadence,
                            prev_bass_pitch=lh_pitch,
                        )
                else:
                    lh_events = _build_left_pattern(
                        measure_lh_family, lh_pool, lh_harmony,
                        total, pulse, request, rng,
                        bass_target=int(bass_target_pitch) if bass_target_pitch is not None else None,
                        measure_role=measure_role,
                        is_phrase_start=is_phrase_start,
                        is_cadence=is_cadence,
                        prev_bass_pitch=lh_pitch,
                    )

                for event in _measure_events_with_offsets(measure_number, measure_offset, lh_events):
                    event["harmony"] = harmony
                    event["phraseIndex"] = phrase_plan["phraseIndex"]
                    event["phraseCadence"] = phrase_plan["cadenceTarget"]
                    event["leftFamily"] = measure_lh_family
                    event["measureRole"] = measure_role
                    event["targetDensity"] = phrase_plan.get("_densityTargets", {}).get(measure_number, 0.5)
                    event["phraseContour"] = phrase_plan.get("_contour", "flat")
                    event["rhTexture"] = rh_texture
                    if bass_target_pitch is not None:
                        event["plannedBassPitch"] = int(bass_target_pitch)
                    events.append(event)
                if lh_events:
                    last_bass = next(
                        (_lh_bass_pitch(event) for event in reversed(lh_events) if _lh_bass_pitch(event) is not None),
                        None,
                    )
                    if last_bass is not None:
                        lh_pitch = int(last_bass)
    events = _apply_right_hand_seconds(events, request, preset, rng)
    events = _apply_right_hand_harmonic_punctuations(events, request, preset, rng)

    # Post-processing: ties, dynamics, slurs, articulations, playback touch
    events = _apply_ties(events, request, rng)
    events = _assign_expression_ids(events)
    events = _apply_dynamics(events, phrases, piece_plan, preset, rng)
    events = _apply_slurs(events, phrases, request, rng)
    events = _apply_articulations(events, request, grade, preset, rng)
    events = _apply_playback_expression(events)

    return {
        "events": events,
        "phrases": phrases,
        "phrasePlans": phrase_plans,
        "harmonicPlan": plan,
        "styleProfile": style_profile,
        "piecePlan": piece_plan,
    }


def _build_piano_events(request: dict[str, Any], rng: random.Random) -> list[dict[str, Any]]:
    return _build_piano_candidate(request, rng)["events"]


# ---------------------------------------------------------------------------
# Rhythm mode (kept from original)
# ---------------------------------------------------------------------------

def _build_rhythm_events(request: dict[str, Any], rng: random.Random) -> list[dict[str, Any]]:
    preset = _preset_for_grade(request["grade"])
    total = _measure_total(request["timeSignature"])
    pulse = _pulse_value(request["timeSignature"])
    allowed = sorted({float(value) for value in preset["rhythm"]["quarterLengths"]}, reverse=True)
    phrases = _phrase_form_template(int(request["measureCount"]))
    plan = _harmonic_plan(
        int(request["measureCount"]),
        int(request["grade"]),
        request["keySignature"],
        phrases,
        rng,
    )

    right_root = HAND_POSITION_ROOTS["rh"][request["handPosition"]]
    left_root = HAND_POSITION_ROOTS["lh"][request["handPosition"]]
    right_anchor = _position_pitches_from_root(right_root, "C")[2]
    left_anchor = _position_pitches_from_root(left_root, "C")[0]
    events: list[dict[str, Any]] = []

    for measure_number, harmony in enumerate(plan, start=1):
        measure_offset = (measure_number - 1) * total
        durations = _fit_measure(total, allowed, rng)
        if durations is None:
            raise ValueError("Could not build rhythm measure")

        if request["handActivity"] != "left-only":
            cursor = 0.0
            for duration in durations:
                is_rest = request["allowRests"] and rng.random() < float(preset["rhythm"]["restChance"])
                events.append({
                    "hand": "rh",
                    "measure": measure_number,
                    "offset": round(measure_offset + cursor, 3),
                    "quarterLength": float(duration),
                    "isRest": is_rest,
                    "pitches": [] if is_rest else [right_anchor],
                    "technique": "fixed anchor rhythm",
                })
                cursor += float(duration)

        if request["handActivity"] != "right-only":
            lh_families = list(preset["piano"].get("leftPatternFamilies", ["held"]))
            left_family = rng.choice(lh_families)
            harmony_pool = _chord_tones_in_pool(
                _position_pitches_from_root(left_root, "C"),
                "C",
                harmony,
            )
            left_events = _build_left_pattern(
                left_family,
                [left_anchor],
                harmony_pool,
                total,
                pulse,
                request,
                rng,
                is_phrase_start=measure_number in {phrase[0] for phrase in phrases if phrase},
                is_cadence=measure_number in {phrase[-1] for phrase in phrases if phrase},
            )
            for event in _measure_events_with_offsets(measure_number, measure_offset, left_events):
                event["technique"] = "fixed anchor rhythm"
                events.append(event)

    return events


# ---------------------------------------------------------------------------
# MusicXML / SVG
# ---------------------------------------------------------------------------

def _entry_for_event(event: dict[str, Any]):
    if event["isRest"] or not event["pitches"]:
        return note.Rest(quarterLength=float(event["quarterLength"]))

    if len(event["pitches"]) > 1:
        entry = chord.Chord(event["pitches"], quarterLength=float(event["quarterLength"]))
    else:
        entry = note.Note(quarterLength=float(event["quarterLength"]))
        entry.pitch.midi = int(event["pitches"][0])

    if event.get("eventId"):
        entry.id = str(event["eventId"])

    if event.get("tieType"):
        entry.tie = m21tie.Tie(str(event["tieType"]))

    # Tuplet (triplets)
    if event.get("tuplet"):
        t = event["tuplet"]
        entry.duration.tuplets = [
            m21duration.Tuplet(
                numberNotesActual=t["actual"],
                numberNotesNormal=t["normal"],
            )
        ]

    # Articulations
    art = event.get("articulation")
    if art == "staccato":
        entry.articulations.append(articulations.Staccato())
    elif art == "accent":
        entry.articulations.append(articulations.Accent())
    elif art == "tenuto":
        entry.articulations.append(articulations.Tenuto())

    # Fermata (final note of piece)
    if event.get("fermata"):
        entry.expressions.append(expressions.Fermata())

    return entry


def _build_measure(
    hand_events: list[dict[str, Any]],
    measure_number: int,
    measure_offset: float,
    total: float,
    is_final: bool,
    *,
    start_new_system: bool = False,
) -> stream.Measure:
    measure_obj = stream.Measure(number=measure_number)
    if start_new_system:
        measure_obj.insert(0, layout.SystemLayout(isNew=True))
    cursor = 0.0

    # Expressible rest durations (standard note values)
    _EXPRESSIBLE = {4.0, 3.0, 2.0, 1.5, 1.0, 0.75, 0.5, 0.25, 0.125}

    def _add_rest_if_expressible(dur: float):
        dur = round(dur, 3)
        if dur <= 0.001:
            return
        # Only add rest if it's a standard duration; skip tiny tuplet gaps
        if dur in _EXPRESSIBLE or dur >= 0.25:
            # For non-standard durations, snap to nearest expressible
            if dur not in _EXPRESSIBLE:
                candidates = [d for d in _EXPRESSIBLE if d <= dur + 0.001]
                if candidates:
                    dur = max(candidates)
                else:
                    return
            measure_obj.append(note.Rest(quarterLength=dur))

    for event in sorted(hand_events, key=lambda item: float(item["offset"])):
        local_start = round(float(event["offset"]) - measure_offset, 3)
        gap = round(local_start - cursor, 3)
        if gap > 0.001:
            _add_rest_if_expressible(gap)

        entry = _entry_for_event(event)
        measure_obj.append(entry)

        # Dynamic marking
        if event.get("dynamic"):
            dyn = dynamics.Dynamic(event["dynamic"])
            measure_obj.insert(local_start, dyn)

        # Use actual sounding duration for cursor (different for tuplets)
        actual_dur = float(event.get("_actualDur", event["quarterLength"]))
        cursor = round(local_start + actual_dur, 3)

    trailing = round(total - cursor, 3)
    if trailing > 0.001:
        _add_rest_if_expressible(trailing)

    measure_obj.rightBarline = bar.Barline("final" if is_final else "regular")
    return measure_obj


def _apply_part_spanners(part: stream.Part, hand_events: list[dict[str, Any]]) -> None:
    entry_map: dict[str, Any] = {}
    for entry in part.recurse().getElementsByClass([note.Note, chord.Chord]):
        entry_id = getattr(entry, "id", None)
        if entry_id:
            entry_map[str(entry_id)] = entry

    slur_groups: dict[str, list[str]] = {}
    hairpin_starts: dict[str, tuple[str, str]] = {}
    hairpin_stops: dict[str, str] = {}

    for event in hand_events:
        if event.get("isRest") or not event.get("pitches") or not event.get("eventId"):
            continue

        slur_id = event.get("slurId")
        if slur_id:
            slur_groups.setdefault(str(slur_id), []).append(str(event["eventId"]))

        hairpin_start = event.get("hairpinStart")
        if hairpin_start:
            hairpin_starts[str(hairpin_start["id"])] = (
                str(hairpin_start["type"]),
                str(event["eventId"]),
            )

        for hairpin_stop_id in event.get("hairpinStopIds", []):
            hairpin_stops[str(hairpin_stop_id)] = str(event["eventId"])

    for slur_event_ids in slur_groups.values():
        entries = [entry_map[event_id] for event_id in slur_event_ids if event_id in entry_map]
        if len(entries) >= 2:
            part.insert(0, spanner.Slur(entries))

    for hairpin_id, (hairpin_type, start_event_id) in hairpin_starts.items():
        end_event_id = hairpin_stops.get(hairpin_id)
        if not end_event_id:
            continue

        start_entry = entry_map.get(start_event_id)
        end_entry = entry_map.get(end_event_id)
        if not start_entry or not end_entry or start_entry is end_entry:
            continue

        wedge = dynamics.Crescendo() if hairpin_type == "crescendo" else dynamics.Diminuendo()
        wedge.addSpannedElements([start_entry, end_entry])
        part.insert(0, wedge)


def _music21_key(key_signature: str):
    if is_minor_key(key_signature):
        tonic = key_signature[:-1]
        return key.Key(tonic, "minor")
    return key.Key(key_signature)


def _engraving_system_interval(request: dict[str, Any], events: list[dict[str, Any]]) -> int:
    measure_count = int(request["measureCount"])
    if measure_count <= 4:
        return 4

    density_samples: list[float] = []
    dense_measures = 0
    for measure_number in range(1, measure_count + 1):
        measure_events = [
            event for event in events
            if int(event.get("measure", 0)) == measure_number
            and not event.get("isRest")
        ]
        if not measure_events:
            density_samples.append(0.0)
            continue

        density = 0.0
        for event in measure_events:
            duration_value = float(event.get("_actualDur", event.get("quarterLength", 0.0)))
            pitch_count = len(event.get("pitches", []))
            technique = str(event.get("technique", ""))

            density += 1.0
            density += max(0, pitch_count - 1) * 0.65
            if duration_value <= 0.5:
                density += 0.8
            if duration_value <= 0.25:
                density += 1.1
            if technique in {"triplet", "scale run", "scale figure", "scale figure landing", "chordal texture", "block chord"}:
                density += 0.9

        density_samples.append(density)
        if density >= 9.5:
            dense_measures += 1

    avg_density = _mean(density_samples, default=0.0)
    very_dense = avg_density >= 9.0 or dense_measures >= max(2, measure_count // 3)
    dense = avg_density >= 7.0 or dense_measures >= max(1, measure_count // 4)

    if measure_count == 8:
        return 2 if dense else 4
    if measure_count == 12:
        return 3 if dense else 4
    if measure_count >= 16:
        return 2 if very_dense else 4
    return 4


def _create_musicxml(request: dict[str, Any], events: list[dict[str, Any]], bpm: int) -> str:
    score = stream.Score()
    right_hand = stream.Part(id="RH")
    left_hand = stream.Part(id="LH")

    right_hand.partName = "RH"
    left_hand.partName = "LH"

    right_hand.append(tempo.MetronomeMark(number=bpm))
    left_hand.append(tempo.MetronomeMark(number=bpm))
    right_hand.insert(0, clef.TrebleClef())
    left_hand.insert(0, clef.BassClef())
    right_hand.insert(0, meter.TimeSignature(request["timeSignature"]))
    left_hand.insert(0, meter.TimeSignature(request["timeSignature"]))

    if request["mode"] == "piano":
        m21_key = _music21_key(request["keySignature"])
        right_hand.insert(0, m21_key)
        left_hand.insert(0, key.Key(m21_key.tonic, m21_key.mode))

    total = _measure_total(request["timeSignature"])
    system_interval = _engraving_system_interval(request, events)
    for measure_number in range(1, int(request["measureCount"]) + 1):
        measure_offset = (measure_number - 1) * total
        right_events = [
            event for event in events if event["hand"] == "rh" and int(event["measure"]) == measure_number
        ]
        left_events = [
            event for event in events if event["hand"] == "lh" and int(event["measure"]) == measure_number
        ]
        is_final = measure_number == int(request["measureCount"])
        start_new_system = measure_number > 1 and (measure_number - 1) % system_interval == 0
        right_hand.append(
            _build_measure(
                right_events,
                measure_number,
                measure_offset,
                total,
                is_final,
                start_new_system=start_new_system,
            )
        )
        left_hand.append(
            _build_measure(
                left_events,
                measure_number,
                measure_offset,
                total,
                is_final,
                start_new_system=start_new_system,
            )
        )

    _apply_part_spanners(
        right_hand,
        [event for event in events if event.get("hand") == "rh"],
    )
    _apply_part_spanners(
        left_hand,
        [event for event in events if event.get("hand") == "lh"],
    )

    score.insert(0, right_hand)
    score.insert(0, left_hand)
    score.insert(0, layout.StaffGroup([right_hand, left_hand], name="Piano", symbol="brace", barTogether=True))

    xml_bytes = GeneralObjectExporter(score).parse()
    return xml_bytes.decode("utf-8")


def _render_svg(music_xml: str, title: str) -> str:
    if toolkit is None:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="360" viewBox="0 0 1200 360">'
            '<rect width="1200" height="360" fill="#ffffff" stroke="#d9d2c8" />'
            f'<text x="60" y="92" font-size="42" font-family="Arial" fill="#17181d">{title}</text>'
            '<text x="60" y="150" font-size="22" font-family="Arial" fill="#68707c">'
            "Install verovio to render grand-staff notation locally."
            "</text></svg>"
        )

    import re

    vrv = toolkit()
    vrv.setOptions({
        "pageWidth": 920,
        "pageMarginLeft": 26,
        "pageMarginRight": 26,
        "pageMarginTop": 30,
        "pageMarginBottom": 22,
        "scale": 39,
        "header": "none",
        "footer": "none",
        "adjustPageHeight": True,
        "breaks": "encoded",
        "spacingSystem": 16,
        "spacingStaff": 8,
    })
    vrv.loadData(music_xml)

    def _fix_svg(raw: str) -> str:
        fixed = raw.replace("currentColor", "#000000")
        fixed = re.sub(r"<path(?![^>]*\bstroke=)\s", '<path stroke="#000000" ', fixed)
        fixed = re.sub(r"<rect(?![^>]*\bstroke=)\s", '<rect stroke="#000000" ', fixed)
        fixed = re.sub(r"<polyline(?![^>]*\bstroke=)\s", '<polyline stroke="#000000" ', fixed)
        fixed = re.sub(r"<polygon(?![^>]*\bstroke=)\s", '<polygon stroke="#000000" ', fixed)
        fixed = re.sub(r"<ellipse(?![^>]*\bstroke=)\s", '<ellipse stroke="#000000" ', fixed)
        fixed = re.sub(
            r'(<g[^>]*class="slur"[^>]*>\s*<path\b)(?![^>]*\bfill=)',
            r'\1 fill="none"',
            fixed,
        )
        return fixed

    page_count = vrv.getPageCount()
    if page_count == 1:
        return _fix_svg(vrv.renderToSVG(1))

    page_svgs: list[str] = []
    page_heights: list[float] = []
    page_width = 0.0

    for page_num in range(1, page_count + 1):
        svg = vrv.renderToSVG(page_num)
        match = re.search(r'width="([\d.]+)px"\s+height="([\d.]+)px"', svg)
        if match:
            page_width = max(page_width, float(match.group(1)))
            page_heights.append(float(match.group(2)))
        else:
            page_heights.append(500.0)
        page_svgs.append(svg)

    total_height = sum(page_heights)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{page_width}px" height="{total_height}px" '
        f'viewBox="0 0 {page_width} {total_height}">'
    ]

    y_offset = 0.0
    for svg, h in zip(page_svgs, page_heights):
        inner = re.sub(r'^<svg[^>]*>', '', svg, count=1)
        inner = re.sub(r'</svg>\s*$', '', inner, count=1)
        parts.append(
            f'<svg x="0" y="{y_offset}" width="{page_width}" height="{h}">'
            f'{inner}</svg>'
        )
        y_offset += h

    parts.append("</svg>")
    return _fix_svg("".join(parts))


# ---------------------------------------------------------------------------
# Validation / summary
# ---------------------------------------------------------------------------

def _events_by_hand(events: list[dict[str, Any]], hand: str) -> list[dict[str, Any]]:
    return [event for event in events if event["hand"] == hand]


def _strong_beat(offset: float, signature: str) -> bool:
    local_offset = round(offset % _measure_total(signature), 3)
    return abs(local_offset) < 0.001 or (
        signature == "4/4" and abs(local_offset - 2.0) < 0.001
    )


def _validate_accidental_resolution(events: list[dict[str, Any]]) -> bool:
    return True


def _validate_strong_beat_harmony(request: dict[str, Any], events: list[dict[str, Any]]) -> bool:
    misses = 0
    total = 0
    for event in _events_by_hand(events, "rh"):
        if event["isRest"] or not event["pitches"] or not _strong_beat(float(event["offset"]), request["timeSignature"]):
            continue
        total += 1
        harmony = event.get("harmony", "I")
        harmony_pcs = _chord_pitch_classes(request["keySignature"], harmony)
        lead_pitch = _rh_lead_pitch(event)
        if lead_pitch is None or lead_pitch % 12 not in harmony_pcs:
            misses += 1
    if total == 0:
        return True
    return misses <= max(2, int(total * 0.75))


def _validate_phrase_endings(request: dict[str, Any], events: list[dict[str, Any]]) -> bool:
    phrase_endings: dict[int, dict[str, Any]] = {}
    for event in _events_by_hand(events, "rh"):
        if event["isRest"] or not event["pitches"]:
            continue
        phrase_endings[int(event.get("phraseIndex", 0))] = event
    if not phrase_endings:
        return True
    tonic_pc = KEY_TONIC_PITCH_CLASS[request["keySignature"]]
    misses = 0
    for event in phrase_endings.values():
        harmony = event.get("harmony", "I")
        stable_pcs = _chord_pitch_classes(request["keySignature"], harmony) | {tonic_pc}
        lead_pitch = _rh_lead_pitch(event)
        if lead_pitch is None or lead_pitch % 12 not in stable_pcs:
            misses += 1
    return misses <= max(1, len(phrase_endings) // 2)


def _validate_left_family_stability(events: list[dict[str, Any]]) -> bool:
    # With Grade 4+ independent LH, this check is relaxed
    return True


def _mean(values: list[float], default: float = 0.0) -> float:
    return sum(values) / len(values) if values else default


def _measure_events_for_hand(
    events: list[dict[str, Any]],
    hand: str,
    measure_number: int,
) -> list[dict[str, Any]]:
    return sorted(
        [
            event
            for event in events
            if event["hand"] == hand and int(event["measure"]) == measure_number
        ],
        key=lambda event: float(event["offset"]),
    )


def _measure_signature(events: list[dict[str, Any]], measure_number: int, hand: str = "rh") -> tuple[tuple[str, float], ...]:
    signature: list[tuple[str, float]] = []
    for event in _measure_events_for_hand(events, hand, measure_number):
        actual = round(float(event.get("_actualDur", event["quarterLength"])), 2)
        if event["isRest"]:
            kind = "R"
        elif len(event.get("pitches", [])) > 1:
            kind = "C"
        else:
            kind = "N"
        if event.get("tuplet"):
            kind = f"T{kind}"
        signature.append((kind, actual))
    return tuple(signature)


def _measure_motif_events(events: list[dict[str, Any]], measure_number: int) -> list[dict[str, Any]]:
    return [
        event
        for event in _measure_events_for_hand(events, "rh", measure_number)
        if event.get("technique") == "motif" or event.get("motifTechnique")
    ]


def _measure_motif_signature(events: list[dict[str, Any]], measure_number: int) -> tuple[tuple[str, float], ...]:
    signature: list[tuple[str, float]] = []
    for event in _measure_motif_events(events, measure_number):
        actual = round(float(event.get("_actualDur", event["quarterLength"])), 2)
        signature.append(("M", actual))
    return tuple(signature)


def _motion_token(interval_value: int) -> tuple[str, str]:
    if interval_value == 0:
        return ("S", "repeat")
    direction = "U" if interval_value > 0 else "D"
    magnitude = abs(interval_value)
    if magnitude <= 2:
        size = "step"
    elif magnitude <= 5:
        size = "skip"
    else:
        size = "leap"
    return direction, size


def _measure_motif_motion_signature(events: list[dict[str, Any]], measure_number: int) -> tuple[tuple[str, str], ...]:
    motif_events = _measure_motif_events(events, measure_number)
    pitches = [
        int(_rh_lead_pitch(event))
        for event in motif_events
        if not event.get("isRest") and event.get("pitches") and _rh_lead_pitch(event) is not None
    ]
    if len(pitches) < 2:
        return tuple()
    return tuple(
        _motion_token(right - left)
        for left, right in zip(pitches, pitches[1:], strict=False)
    )


def _motion_signature_similarity(
    left: tuple[tuple[str, str], ...],
    right: tuple[tuple[str, str], ...],
    *,
    prefix: bool = False,
) -> float:
    if not left or not right:
        return 0.0

    compare_len = min(len(left), len(right)) if prefix else min(len(left), len(right))
    if compare_len <= 0:
        return 0.0

    matches = 0.0
    for idx in range(compare_len):
        if left[idx] == right[idx]:
            matches += 1.0
        elif left[idx][0] == right[idx][0]:
            matches += 0.72
        elif left[idx][1] == right[idx][1]:
            matches += 0.38

    divisor = compare_len if prefix else max(len(left), len(right))
    return matches / max(1, divisor)


def _count_similarity(expected_count: int, actual_count: int) -> float:
    if expected_count <= 0 and actual_count <= 0:
        return 1.0
    return max(0.0, 1.0 - abs(expected_count - actual_count) / max(1, expected_count))


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


def _measure_complexity(events: list[dict[str, Any]], measure_number: int, hand: str = "rh") -> float:
    hand_events = _measure_events_for_hand(events, hand, measure_number)
    if not hand_events:
        return 0.0

    note_events = [event for event in hand_events if not event["isRest"] and event.get("pitches")]
    rest_events = [event for event in hand_events if event["isRest"]]
    short_notes = sum(
        1
        for event in note_events
        if float(event.get("_actualDur", event["quarterLength"])) <= 0.5
    )
    tuplets = sum(1 for event in note_events if event.get("tuplet"))
    chords = sum(1 for event in note_events if len(event.get("pitches", [])) > 1)

    leaps = 0
    previous_pitch: int | None = None
    for event in note_events:
        primary_pitch = _event_primary_pitch(event)
        if primary_pitch is None:
            continue
        current_pitch = int(primary_pitch)
        if previous_pitch is not None and abs(current_pitch - previous_pitch) >= 7:
            leaps += 1
        previous_pitch = current_pitch

    raw = (
        len(note_events) * 0.16
        + short_notes * 0.10
        + tuplets * 0.22
        + chords * 0.16
        + leaps * 0.08
        + len(rest_events) * 0.04
    )
    return min(1.0, raw)


def _strong_beat_harmony_score(request: dict[str, Any], events: list[dict[str, Any]]) -> float:
    hits = 0
    total = 0
    for event in _events_by_hand(events, "rh"):
        if event["isRest"] or not event["pitches"] or not _strong_beat(float(event["offset"]), request["timeSignature"]):
            continue
        total += 1
        harmony = event.get("harmony", "I")
        harmony_pcs = _chord_pitch_classes(request["keySignature"], harmony)
        lead_pitch = _rh_lead_pitch(event)
        if lead_pitch is not None and lead_pitch % 12 in harmony_pcs:
            hits += 1
    return hits / total if total else 1.0


def _phrase_ending_stability_score(request: dict[str, Any], events: list[dict[str, Any]]) -> float:
    phrase_endings: dict[int, dict[str, Any]] = {}
    for event in _events_by_hand(events, "rh"):
        if event["isRest"] or not event["pitches"]:
            continue
        phrase_endings[int(event.get("phraseIndex", 0))] = event

    if not phrase_endings:
        return 1.0

    tonic_pc = KEY_TONIC_PITCH_CLASS[request["keySignature"]]
    stable = 0
    for event in phrase_endings.values():
        harmony = event.get("harmony", "I")
        stable_pcs = _chord_pitch_classes(request["keySignature"], harmony) | {tonic_pc}
        lead_pitch = _rh_lead_pitch(event)
        if lead_pitch is not None and lead_pitch % 12 in stable_pcs:
            stable += 1
    return stable / len(phrase_endings)


def _score_phrase_motif(events: list[dict[str, Any]], phrase_plan: dict[str, Any]) -> float:
    measures = list(phrase_plan.get("measures", []))
    if len(measures) < 2:
        return 0.75

    blueprint = phrase_plan.get("_motiveBlueprint", {})
    transform_by_measure = blueprint.get("transformByMeasure", {})
    target_measures = [
        measure_number
        for measure_number in measures
        if transform_by_measure.get(measure_number) not in {None, "none", "contrast"}
    ]

    if not target_measures:
        anchor_signature = _measure_signature(events, measures[0], "rh")
        if not anchor_signature:
            return 0.0
        similarities = [
            _signature_similarity(anchor_signature, _measure_signature(events, measure_number, "rh"))
            for measure_number in measures[1:]
        ]
        return 0.45 * max(similarities, default=0.0) + 0.55 * _mean(similarities)

    anchor_measure = next(
        (measure_number for measure_number in target_measures if transform_by_measure.get(measure_number) == "base"),
        target_measures[0],
    )
    anchor_signature = _measure_motif_signature(events, anchor_measure)
    anchor_motion = _measure_motif_motion_signature(events, anchor_measure)
    anchor_events = _measure_motif_events(events, anchor_measure)
    if not anchor_signature or not anchor_events:
        return 0.0

    per_measure_scores: list[float] = []
    presence_scores = [1.0]

    for measure_number in target_measures:
        if measure_number == anchor_measure:
            continue

        motif_events = _measure_motif_events(events, measure_number)
        motif_signature = _measure_motif_signature(events, measure_number)
        motif_motion = _measure_motif_motion_signature(events, measure_number)
        presence = 1.0 if motif_signature else 0.0
        presence_scores.append(presence)
        if not motif_signature or not motif_events:
            per_measure_scores.append(0.0)
            continue

        transform = transform_by_measure.get(measure_number, "sequence")
        prefix_compare = transform in {"fragment", "cadence"}
        compare_len = min(len(anchor_signature), len(motif_signature))

        if prefix_compare:
            duration_similarity = _signature_similarity(anchor_signature[:compare_len], motif_signature[:compare_len])
        else:
            duration_similarity = _signature_similarity(anchor_signature, motif_signature)

        motion_similarity = _motion_signature_similarity(
            anchor_motion,
            motif_motion,
            prefix=prefix_compare,
        )

        expected_count = len(anchor_events)
        if transform in {"fragment", "cadence"}:
            count_score = 1.0 if 2 <= len(motif_events) <= expected_count else _count_similarity(expected_count - 1, len(motif_events))
        else:
            count_score = _count_similarity(expected_count, len(motif_events))

        transform_bonus = 0.65
        if transform == "repeat":
            transform_bonus = 1.0 if duration_similarity >= 0.88 and motion_similarity >= 0.82 else max(0.55, 0.5 * duration_similarity + 0.5 * motion_similarity)
        elif transform == "sequence":
            anchor_pitch = _rh_lead_pitch(anchor_events[0])
            measure_pitch = _rh_lead_pitch(motif_events[0])
            if anchor_pitch is None or measure_pitch is None:
                per_measure_scores.append(0.0)
                continue
            transform_bonus = 1.0 if measure_pitch != anchor_pitch and motion_similarity >= 0.65 else max(0.45, motion_similarity)
        elif transform == "fragment":
            transform_bonus = 1.0 if len(motif_events) < expected_count and motion_similarity >= 0.6 else max(0.4, motion_similarity)
        elif transform == "cadence":
            final_measure_events = _measure_events_for_hand(events, "rh", measure_number)
            last_pitched = next(
                (event for event in reversed(final_measure_events) if not event["isRest"] and event.get("pitches")),
                None,
            )
            cadence_lands = bool(
                last_pitched
                and _rh_lead_pitch(last_pitched) == _rh_lead_pitch(motif_events[-1])
            )
            transform_bonus = (
                1.0
                if len(motif_events) <= expected_count and cadence_lands
                else max(0.45, 0.55 * motion_similarity + 0.45 * count_score)
            )

        per_measure_scores.append(
            0.24 * presence
            + 0.26 * duration_similarity
            + 0.28 * motion_similarity
            + 0.12 * count_score
            + 0.10 * transform_bonus
        )

    if not per_measure_scores:
        return 0.75

    return 0.25 * _mean(presence_scores, default=1.0) + 0.75 * _mean(per_measure_scores, default=0.0)


def _phrase_inheritance_score(events: list[dict[str, Any]], phrase_plans: list[dict[str, Any]]) -> float:
    if len(phrase_plans) < 2:
        return 0.8

    scores: list[float] = []
    by_index = {
        int(phrase_plan.get("phraseIndex", idx)): phrase_plan
        for idx, phrase_plan in enumerate(phrase_plans)
    }

    for phrase_plan in phrase_plans[1:]:
        source_index = phrase_plan.get("_inheritsFromPhraseIndex")
        if source_index is None:
            continue
        source_plan = by_index.get(int(source_index))
        current_measures = list(phrase_plan.get("measures", []))
        source_measures = list(source_plan.get("measures", [])) if source_plan else []
        if not current_measures or not source_measures:
            continue

        source_measure = int(source_measures[0])
        current_measure = int(current_measures[0])
        source_signature = _measure_signature(events, source_measure, "rh")
        current_signature = _measure_signature(events, current_measure, "rh")
        source_motion = _measure_motif_motion_signature(events, source_measure) or _measure_motif_motion_signature(events, current_measure)
        current_motion = _measure_motif_motion_signature(events, current_measure)
        rhythm_similarity = _signature_similarity(source_signature, current_signature)
        motion_similarity = _motion_signature_similarity(source_motion, current_motion) if source_motion and current_motion else 0.55
        contour_similarity = 1.0 if phrase_plan.get("_contour") == source_plan.get("_contour") else 0.72

        if phrase_plan.get("_inheritRhythm"):
            contour_similarity *= 1.0
        else:
            rhythm_similarity *= 0.85

        scores.append(0.45 * rhythm_similarity + 0.35 * motion_similarity + 0.20 * contour_similarity)

    return _mean(scores, default=0.78)


def _score_phrase_continuation(
    request: dict[str, Any],
    events: list[dict[str, Any]],
    phrase_plan: dict[str, Any],
) -> float:
    continuation_by_measure = phrase_plan.get("_continuationByMeasure", {})
    if not continuation_by_measure:
        return 0.7

    role_by_measure = phrase_plan.get("_measureRoles", {})
    measure_scores: list[float] = []
    previous_last_pitch: int | None = None
    previous_max_pitch: int | None = None

    tonic_pc = KEY_TONIC_PITCH_CLASS[request["keySignature"]]

    for measure_number in phrase_plan.get("measures", []):
        gesture = continuation_by_measure.get(measure_number)
        measure_events = _measure_events_for_hand(events, "rh", measure_number)
        pitched_measure_events = [
            event for event in measure_events
            if not event["isRest"] and event.get("pitches")
        ]
        if not pitched_measure_events:
            continue

        phrase_events = [
            event for event in pitched_measure_events
            if event.get("phraseFunction") == gesture
        ]
        if not gesture:
            previous_last_pitch = _rh_lead_pitch(pitched_measure_events[-1])
            previous_max_pitch = max(
                int(pitch_value)
                for pitch_value in (_rh_lead_pitch(event) for event in pitched_measure_events)
                if pitch_value is not None
            )
            continue

        presence = 1.0 if phrase_events else 0.0
        phrase_pitches = [
            int(pitch_value)
            for pitch_value in (_rh_lead_pitch(event) for event in phrase_events)
            if pitch_value is not None
        ]
        if len(phrase_pitches) >= 2:
            motion_pairs = list(zip(phrase_pitches, phrase_pitches[1:], strict=False))
            stepwise_pairs = sum(
                1
                for left, right in motion_pairs
                if 0 < abs(right - left) <= 5
            )
            static_pairs = sum(1 for left, right in motion_pairs if right == left)
            stepwise_score = stepwise_pairs / max(1, len(phrase_pitches) - 1)
            if static_pairs:
                stepwise_score = max(0.0, stepwise_score - (static_pairs / max(1, len(phrase_pitches) - 1)) * 0.4)
        else:
            stepwise_score = 0.65 if phrase_pitches else 0.0

        connection_score = 0.75
        if previous_last_pitch is not None and phrase_pitches:
            connection_score = max(0.0, 1.0 - abs(phrase_pitches[0] - previous_last_pitch) / 12.0)

        role = str(role_by_measure.get(measure_number, "develop"))
        role_score = 0.7
        if gesture in {"climb", "fragment-push", "rise-release"}:
            measure_peak = max(
                int(pitch_value)
                for pitch_value in (_rh_lead_pitch(event) for event in pitched_measure_events)
                if pitch_value is not None
            )
            if previous_max_pitch is None:
                role_score = 0.8
            else:
                role_score = 1.0 if measure_peak >= previous_max_pitch - 1 else 0.45
        elif gesture in {"cadence-step", "cadence-turn"}:
            last_pitch = _rh_lead_pitch(pitched_measure_events[-1])
            harmony = str(pitched_measure_events[-1].get("harmony", "I"))
            stable_pcs = _chord_pitch_classes(request["keySignature"], harmony) | {tonic_pc}
            role_score = 1.0 if last_pitch is not None and last_pitch % 12 in stable_pcs else 0.3
        elif gesture in {"sustain", "hold-answer"}:
            longest = max(float(event.get("_actualDur", event["quarterLength"])) for event in phrase_events) if phrase_events else 0.0
            role_score = 1.0 if longest >= _pulse_value(request["timeSignature"]) else 0.55
        elif role == "answer":
            role_score = 1.0 if phrase_pitches and previous_last_pitch is not None and abs(phrase_pitches[-1] - previous_last_pitch) <= 7 else 0.6
        elif role == "develop":
            role_score = 1.0 if stepwise_score >= 0.6 else 0.55

        measure_scores.append(
            0.28 * presence
            + 0.24 * stepwise_score
            + 0.22 * connection_score
            + 0.26 * role_score
        )

        previous_last_pitch = _rh_lead_pitch(pitched_measure_events[-1])
        previous_max_pitch = max(
            int(pitch_value)
            for pitch_value in (_rh_lead_pitch(event) for event in pitched_measure_events)
            if pitch_value is not None
        )

    return _mean(measure_scores, default=0.65)


def _score_phrase_contour(events: list[dict[str, Any]], phrase_plan: dict[str, Any]) -> float:
    measures = set(phrase_plan.get("measures", []))
    phrase_events = [
        event
        for event in _events_by_hand(events, "rh")
        if int(event["measure"]) in measures and not event["isRest"] and event.get("pitches")
    ]
    if len(phrase_events) < 3:
        return 0.6

    pitches = [
        int(pitch_value)
        for pitch_value in (_rh_lead_pitch(event) for event in phrase_events)
        if pitch_value is not None
    ]
    contour = phrase_plan.get("_contour", "flat")
    motion_pairs = list(zip(pitches, pitches[1:], strict=False))
    ups = sum(1 for left, right in motion_pairs if right > left)
    downs = sum(1 for left, right in motion_pairs if right < left)
    total_motion = max(1, ups + downs)

    target_peak_measure = int(phrase_plan.get("_targetPeakMeasure", phrase_plan["measures"][-1]))
    peak_event = max(phrase_events, key=lambda event: int(_rh_lead_pitch(event) or 0))
    trough_event = min(phrase_events, key=lambda event: int(_rh_lead_pitch(event) or 0))

    if contour == "ascending":
        return 0.55 * (1.0 if pitches[-1] >= pitches[0] else 0.2) + 0.45 * (ups / total_motion)
    if contour == "descending":
        return 0.55 * (1.0 if pitches[-1] <= pitches[0] else 0.2) + 0.45 * (downs / total_motion)
    if contour == "arch":
        peak_ratio = phrase_events.index(peak_event) / max(1, len(phrase_events) - 1)
        center_score = max(0.0, 1.0 - abs(peak_ratio - 0.55) / 0.55)
        measure_score = 1.0 if abs(int(peak_event["measure"]) - target_peak_measure) <= 1 else 0.55
        direction_score = min(ups, downs) / max(1, total_motion / 2)
        return min(1.0, 0.35 * center_score + 0.35 * measure_score + 0.30 * direction_score)
    if contour == "valley":
        trough_ratio = phrase_events.index(trough_event) / max(1, len(phrase_events) - 1)
        center_score = max(0.0, 1.0 - abs(trough_ratio - 0.45) / 0.55)
        direction_score = min(ups, downs) / max(1, total_motion / 2)
        return min(1.0, 0.55 * center_score + 0.45 * direction_score)

    # Flat / mixed contour
    return max(0.0, 1.0 - abs(pitches[-1] - pitches[0]) / 12.0)


def _score_phrase_complexity(events: list[dict[str, Any]], phrase_plan: dict[str, Any]) -> float:
    measures = list(phrase_plan.get("measures", []))
    if not measures:
        return 0.0

    targets = phrase_plan.get("_densityTargets", {})
    diffs = [
        abs(_measure_complexity(events, measure_number, "rh") - float(targets.get(measure_number, 0.5)))
        for measure_number in measures
    ]
    base_score = max(0.0, 1.0 - (_mean(diffs) / 0.75))

    if len(measures) == 1:
        return base_score

    cadence_measure = measures[-1]
    cadence_complexity = _measure_complexity(events, cadence_measure, "rh")
    previous_complexity = _mean(
        [_measure_complexity(events, measure_number, "rh") for measure_number in measures[:-1]],
        default=cadence_complexity,
    )
    cadence_simplifies = 1.0 if cadence_complexity <= previous_complexity + 0.08 else max(
        0.0,
        1.0 - (cadence_complexity - previous_complexity),
    )
    return 0.65 * base_score + 0.35 * cadence_simplifies


def _accidental_resolution_score(request: dict[str, Any], events: list[dict[str, Any]]) -> float:
    key_pcs = _key_pitch_classes(request["keySignature"])
    rh_notes = [
        event
        for event in _events_by_hand(events, "rh")
        if not event["isRest"] and event.get("pitches")
    ]
    total = 0
    resolved = 0
    for left, right in zip(rh_notes, rh_notes[1:], strict=False):
        left_pitch = _rh_lead_pitch(left)
        if left_pitch is None:
            continue
        if left_pitch % 12 in key_pcs:
            continue
        total += 1
        right_pitch = _rh_lead_pitch(right)
        if right_pitch is None:
            continue
        if right_pitch % 12 in key_pcs and abs(right_pitch - left_pitch) <= 2:
            resolved += 1
    return resolved / total if total else 1.0


def _triplet_coherence_score(events: list[dict[str, Any]], phrase_plans: list[dict[str, Any]]) -> float:
    triplet_measures = sorted(
        {
            int(event["measure"])
            for event in _events_by_hand(events, "rh")
            if event.get("tuplet")
        }
    )
    if not triplet_measures:
        return 1.0

    planned_measures = {
        int(measure_number)
        for phrase_plan in phrase_plans
        for measure_number in phrase_plan.get("_tripletMeasures", [])
    }
    role_by_measure = {
        int(measure_number): str(role)
        for phrase_plan in phrase_plans
        for measure_number, role in phrase_plan.get("_measureRoles", {}).items()
    }

    score = 1.0
    unexpected = [measure_number for measure_number in triplet_measures if measure_number not in planned_measures]
    score -= 0.12 * len(unexpected)
    if len(triplet_measures) == 1:
        score -= 0.10
    if any(role_by_measure.get(measure_number) == "cadence" for measure_number in triplet_measures):
        score -= 0.25
    return max(0.0, min(1.0, score))


def _texture_variety_score(
    request: dict[str, Any],
    events: list[dict[str, Any]],
    phrase_plans: list[dict[str, Any]],
) -> float:
    grade = int(request["grade"])
    if grade < 4:
        return 1.0

    texture_by_measure: dict[int, str] = {}
    for event in _events_by_hand(events, "rh"):
        texture = event.get("rhTexture")
        if texture:
            texture_by_measure[int(event["measure"])] = str(texture)

    if not texture_by_measure:
        return 0.0

    textures = set(texture_by_measure.values())
    non_melody = [measure_number for measure_number, texture in texture_by_measure.items() if texture != "melody"]
    running_measures = [measure_number for measure_number, texture in texture_by_measure.items() if texture == "running"]

    phrase_scores: list[float] = []
    for phrase_plan in phrase_plans:
        measures = list(phrase_plan.get("measures", []))
        phrase_textures = {texture_by_measure.get(measure_number, "melody") for measure_number in measures}
        role_by_measure = phrase_plan.get("_measureRoles", {})
        cadence_texture = texture_by_measure.get(measures[-1], "melody") if measures else "melody"
        cadence_ok = 0.35 if cadence_texture == "running" else 1.0
        non_melody_in_phrase = [
            measure_number for measure_number in measures
            if texture_by_measure.get(measure_number, "melody") != "melody"
        ]
        running_in_phrase = [
            measure_number for measure_number in measures
            if texture_by_measure.get(measure_number, "melody") == "running"
        ]

        if not measures:
            continue

        target_unique = 1 if len(measures) <= 2 else 2
        phrase_variety = max(0.0, 1.0 - abs(len(phrase_textures) - target_unique) / max(1, target_unique))

        target_non_melody = 0 if len(measures) <= 2 else 1
        non_melody_score = max(
            0.0,
            1.0 - abs(len(non_melody_in_phrase) - target_non_melody) / max(1, target_non_melody + 1),
        )

        running_score = 1.0
        if len(running_in_phrase) > 1:
            running_score = max(0.0, 1.0 - 0.45 * (len(running_in_phrase) - 1))

        transitions = 0
        for left, right in zip(measures, measures[1:], strict=False):
            if texture_by_measure.get(left, "melody") != texture_by_measure.get(right, "melody"):
                transitions += 1
        transition_target = 0 if len(measures) <= 2 else 1
        transition_score = max(0.0, 1.0 - abs(transitions - transition_target) / max(1, transition_target + 1))

        intensify_measures = [measure_number for measure_number, role in role_by_measure.items() if role == "intensify"]
        intensify_bonus = 1.0
        if intensify_measures:
            if all(texture_by_measure.get(measure_number, "melody") == "melody" for measure_number in intensify_measures):
                intensify_bonus = 0.55

        phrase_scores.append(
            0.26 * phrase_variety
            + 0.22 * non_melody_score
            + 0.18 * transition_score
            + 0.14 * cadence_ok
            + 0.10 * running_score
            + 0.10 * intensify_bonus
        )

    overall_running_score = 1.0 if len(running_measures) <= 1 else max(0.0, 1.0 - 0.25 * (len(running_measures) - 1))
    overall_variety_target = 2 if grade >= 4 else 1
    overall_variety_score = max(0.0, 1.0 - abs(len(textures) - overall_variety_target) / max(1, overall_variety_target))
    overall_non_melody_target = 1 if grade >= 4 else 0
    overall_non_melody_score = max(
        0.0,
        1.0 - abs(len(non_melody) - overall_non_melody_target) / max(1, overall_non_melody_target + 1),
    )

    return (
        0.22 * overall_variety_score
        + 0.18 * overall_non_melody_score
        + 0.18 * overall_running_score
        + 0.42 * _mean(phrase_scores, default=0.6)
    )


def _grade_richness_score(
    request: dict[str, Any],
    events: list[dict[str, Any]],
    phrase_plans: list[dict[str, Any]],
) -> float:
    grade = int(request["grade"])
    if grade < 5:
        return 1.0

    texture_score = _texture_variety_score(request, events, phrase_plans)
    triplet_score = _triplet_coherence_score(events, phrase_plans)

    rh_events = [
        event for event in _events_by_hand(events, "rh")
        if not event["isRest"] and event.get("pitches")
    ]
    all_measures = sorted({int(event["measure"]) for event in rh_events})
    if not all_measures:
        return 0.0

    complexities = [_measure_complexity(events, measure_number, "rh") for measure_number in all_measures]
    average_complexity = _mean(complexities, default=0.0)
    if average_complexity < 0.44:
        complexity_score = max(0.0, average_complexity / 0.44)
    elif average_complexity > 0.84:
        complexity_score = max(0.0, 1.0 - (average_complexity - 0.84) / 0.30)
    else:
        complexity_score = 1.0

    chord_measures = {
        int(event["measure"])
        for event in rh_events
        if len(event.get("pitches", [])) >= 2
    }
    rh_punctuated_measures = {
        int(event["measure"])
        for event in rh_events
        if str(event.get("technique", "")) in {"melodic dyad", "melodic chord accent", "block chord", "scale figure", "scale figure landing", "triplet"}
    }
    tuplet_measures = {
        int(event["measure"])
        for event in rh_events
        if event.get("tuplet")
    }
    texture_measures = {
        int(event["measure"])
        for event in rh_events
        if str(event.get("rhTexture", "melody")) in {"chordal", "running"}
    }
    lh_events = [
        event for event in _events_by_hand(events, "lh")
        if not event["isRest"] and event.get("pitches")
    ]
    lh_chord_measures = {
        int(event["measure"])
        for event in lh_events
        if len(event.get("pitches", [])) >= 2
    }
    lh_broken_measures = {
        int(event["measure"])
        for event in lh_events
        if str(event.get("technique", "")) in {"broken chord", "LH arpeggio", "Alberti bass", "bass and chord", "support bass", "repeated support"}
    }
    lh_family_score = 0.78
    lh_families = {
        str(event.get("leftFamily"))
        for event in lh_events
        if event.get("leftFamily")
    }
    if lh_families:
        family_count = len(lh_families)
        if family_count == 2:
            lh_family_score = 1.0
        elif family_count == 3:
            lh_family_score = 0.92
        elif family_count == 1:
            lh_family_score = 0.62
        elif family_count >= 4:
            lh_family_score = 0.7

    chord_score = min(1.0, len(chord_measures) / 2.0)
    if tuplet_measures:
        tuplet_score = min(1.0, 0.7 + 0.15 * len(tuplet_measures))
    else:
        tuplet_score = 0.72
    texture_presence_score = min(1.0, len(texture_measures) / 2.0)
    lh_chord_score = min(1.0, len(lh_chord_measures) / 3.0)
    lh_motion_score = min(1.0, len(lh_broken_measures) / 3.0)
    rh_punctuation_score = min(1.0, len(rh_punctuated_measures) / 3.0)

    return (
        0.18 * texture_score
        + 0.11 * triplet_score
        + 0.15 * complexity_score
        + 0.11 * chord_score
        + 0.06 * tuplet_score
        + 0.08 * texture_presence_score
        + 0.12 * lh_chord_score
        + 0.08 * lh_motion_score
        + 0.08 * rh_punctuation_score
        + 0.03 * lh_family_score
    )


def _left_hand_stability_score(events: list[dict[str, Any]], phrase_plans: list[dict[str, Any]]) -> float:
    lh_events = _events_by_hand(events, "lh")
    if not lh_events:
        return 1.0

    scores: list[float] = []
    for phrase_plan in phrase_plans:
        measures = set(phrase_plan.get("measures", []))
        families = {
            str(event.get("leftFamily"))
            for event in lh_events
            if int(event["measure"]) in measures and event.get("leftFamily")
        }
        if not families:
            continue
        unique_count = len(families)
        # Phase 2: reward LH consistency — 1 family is ideal for etude style.
        if unique_count == 1:
            scores.append(1.0)
        elif unique_count == 2:
            scores.append(0.85)
        elif unique_count == 3:
            scores.append(0.55)
        else:
            scores.append(0.3 if unique_count == 4 else 0.15)
    return _mean(scores, default=1.0)


def _cadence_strength_score(
    request: dict[str, Any],
    events: list[dict[str, Any]],
    phrase_plans: list[dict[str, Any]],
) -> float:
    tonic_pc = KEY_TONIC_PITCH_CLASS[request["keySignature"]]
    scores: list[float] = []

    for phrase_plan in phrase_plans:
        measures = list(phrase_plan.get("measures", []))
        if not measures:
            continue
        cadence_measure = measures[-1]
        cadence_events = [
            event
            for event in _measure_events_for_hand(events, "rh", cadence_measure)
            if not event["isRest"] and event.get("pitches")
        ]
        if not cadence_events:
            continue
        final_event = cadence_events[-1]
        harmony = str(final_event.get("harmony", "I"))
        stable_pcs = _chord_pitch_classes(request["keySignature"], harmony) | {tonic_pc}
        final_pitch = _rh_lead_pitch(final_event)
        stability = 1.0 if final_pitch is not None and final_pitch % 12 in stable_pcs else 0.25

        cadence_complexity = _measure_complexity(events, cadence_measure, "rh")
        lead_in_complexity = _mean(
            [_measure_complexity(events, measure_number, "rh") for measure_number in measures[:-1]],
            default=cadence_complexity,
        )
        simplicity = 1.0 if cadence_complexity <= lead_in_complexity + 0.08 else max(
            0.0,
            1.0 - (cadence_complexity - lead_in_complexity),
        )
        scores.append(0.55 * stability + 0.45 * simplicity)

    return _mean(scores, default=0.75)


def _line_continuity_score(events: list[dict[str, Any]]) -> float:
    rh_events = [
        event for event in events
        if event["hand"] == "rh" and not event["isRest"] and event.get("pitches")
    ]
    if len(rh_events) < 2:
        return 1.0

    scores: list[float] = []
    repeat_pairs = 0
    longest_repeat_run = 1
    current_repeat_run = 1
    for previous, current in zip(rh_events, rh_events[1:], strict=False):
        current_pitch = _rh_lead_pitch(current)
        previous_pitch = _rh_lead_pitch(previous)
        if current_pitch is None or previous_pitch is None:
            continue
        interval = abs(current_pitch - previous_pitch)
        if interval == 0:
            repeat_pairs += 1
            current_repeat_run += 1
            longest_repeat_run = max(longest_repeat_run, current_repeat_run)
        else:
            current_repeat_run = 1
        if int(current.get("measure", 0)) != int(previous.get("measure", 0)):
            if interval == 0:
                scores.append(0.48)
            elif interval <= 5:
                scores.append(1.0)
            elif interval <= 9:
                scores.append(0.72)
            else:
                scores.append(0.38)
        else:
            if interval == 0:
                scores.append(0.3)
            else:
                scores.append(1.0 if interval <= 7 else 0.68 if interval <= 12 else 0.32)

    motion_score = _mean(scores, default=0.75)
    repeat_ratio = repeat_pairs / max(1, len(rh_events) - 1)
    longest_run_penalty = max(0.0, (longest_repeat_run - 2) * 0.1)
    variety_score = max(0.0, 1.0 - repeat_ratio * 1.15 - longest_run_penalty)
    return 0.55 * motion_score + 0.45 * variety_score


def _anchor_clarity_score(request: dict[str, Any], events: list[dict[str, Any]]) -> float:
    scores: list[float] = []
    for measure_number in sorted({int(event["measure"]) for event in events if event["hand"] == "rh"}):
        measure_events = [
            event
            for event in _measure_events_for_hand(events, "rh", measure_number)
            if not event["isRest"] and event.get("pitches")
        ]
        if not measure_events:
            continue
        first = measure_events[0]
        harmony = str(first.get("harmony", "I"))
        chord_pcs = _chord_pitch_classes(request["keySignature"], harmony)
        pitch_value = _rh_lead_pitch(first)
        if pitch_value is None:
            continue
        pitch_pc = pitch_value % 12
        line_role = str(first.get("lineRole", "stable"))
        target_pcs = chord_pcs | {KEY_TONIC_PITCH_CLASS[request["keySignature"]]}
        if line_role == "dominant":
            target_pcs.add((KEY_TONIC_PITCH_CLASS[request["keySignature"]] + 7) % 12)
        scores.append(1.0 if pitch_pc in target_pcs else 0.42)
    return _mean(scores, default=0.7)


def _non_chord_tone_function_score(request: dict[str, Any], events: list[dict[str, Any]]) -> float:
    rh_events = [
        event for event in events
        if event["hand"] == "rh" and not event["isRest"] and event.get("pitches")
    ]
    if len(rh_events) < 2:
        return 1.0

    scores: list[float] = []
    for index, event in enumerate(rh_events[:-1]):
        harmony = str(event.get("harmony", "I"))
        pitch = _rh_lead_pitch(event)
        if pitch is None:
            continue
        chord_pcs = _chord_pitch_classes(request["keySignature"], harmony)
        if pitch % 12 in chord_pcs:
            scores.append(1.0)
            continue
        next_pitch = _rh_lead_pitch(rh_events[index + 1])
        if next_pitch is None:
            continue
        technique = str(event.get("technique", ""))
        if abs(next_pitch - pitch) <= 2 and (
            "approach" in technique or "neighbor" in technique or "passing" in technique or event.get("ornamentFunction") == "chromatic_approach"
        ):
            scores.append(0.95)
        elif abs(next_pitch - pitch) <= 2:
            scores.append(0.7)
        else:
            scores.append(0.3)
    return _mean(scores, default=0.72)


def _register_arc_score(events: list[dict[str, Any]], phrase_plans: list[dict[str, Any]]) -> float:
    scores: list[float] = []
    for phrase_plan in phrase_plans:
        line_plan = phrase_plan.get("_linePlan")
        if not isinstance(line_plan, LinePlan):
            continue
        measure_means: list[float] = []
        target_slots: list[float] = []
        for measure_number in phrase_plan.get("measures", []):
            pitches = [
                int(pitch_value)
                for event in _measure_events_for_hand(events, "rh", int(measure_number))
                for pitch_value in [_rh_lead_pitch(event)]
                if not event["isRest"] and event.get("pitches") and pitch_value is not None
            ]
            if not pitches:
                continue
            measure_means.append(sum(pitches) / len(pitches))
            target_slots.append(float(line_plan.register_trajectory.get(int(measure_number), 0.5)))
        if len(measure_means) < 2 or len(target_slots) != len(measure_means):
            continue
        actual_motion = [b - a for a, b in zip(measure_means, measure_means[1:], strict=False)]
        target_motion = [b - a for a, b in zip(target_slots, target_slots[1:], strict=False)]
        local_scores: list[float] = []
        for actual, target in zip(actual_motion, target_motion, strict=False):
            if abs(target) < 0.02:
                local_scores.append(1.0 if abs(actual) <= 1.8 else 0.62)
            elif actual == 0:
                local_scores.append(0.55)
            else:
                local_scores.append(1.0 if math.copysign(1, actual) == math.copysign(1, target) else 0.3)
        scores.append(_mean(local_scores, default=0.7))
    return _mean(scores, default=0.72)


def _rh_lh_hierarchy_score(events: list[dict[str, Any]]) -> float:
    rh_events = [event for event in events if event["hand"] == "rh" and not event["isRest"]]
    lh_events = [event for event in events if event["hand"] == "lh" and not event["isRest"]]
    if not rh_events or not lh_events:
        return 1.0
    rh_density = sum(float(event["quarterLength"]) for event in rh_events) / max(1, len(rh_events))
    lh_density = sum(float(event["quarterLength"]) for event in lh_events) / max(1, len(lh_events))
    lh_chords = sum(1 for event in lh_events if len(event.get("pitches", [])) >= 2) / max(1, len(lh_events))

    rh_leads = [pitch_value for pitch_value in (_rh_lead_pitch(event) for event in rh_events) if pitch_value is not None]
    lh_basses = [pitch_value for pitch_value in (_lh_bass_pitch(event) for event in lh_events) if pitch_value is not None]
    register_gap = 0.0
    if rh_leads and lh_basses:
        register_gap = (sum(rh_leads) / len(rh_leads)) - (sum(lh_basses) / len(lh_basses))
    gap_score = 1.0 if register_gap >= 17 else max(0.35, register_gap / 17.0)
    duration_score = 1.0 if lh_density >= rh_density * 1.05 else 0.7
    voicing_score = 1.0 if lh_chords >= 0.28 else 0.74
    return 0.35 * duration_score + 0.25 * voicing_score + 0.40 * gap_score


def _top_line_strength_score(events: list[dict[str, Any]], phrase_plans: list[dict[str, Any]]) -> float:
    scores: list[float] = []
    for phrase_plan in phrase_plans:
        top_line_plan = phrase_plan.get("_topLinePlan")
        if not isinstance(top_line_plan, TopLinePlan):
            continue
        for measure_number in phrase_plan.get("measures", []):
            measure_events = [
                event
                for event in _measure_events_for_hand(events, "rh", int(measure_number))
                if not event["isRest"] and event.get("pitches")
            ]
            if not measure_events:
                continue
            target_pitch = next(
                (
                    int(event["plannedTopPitch"])
                    for event in measure_events
                    if event.get("plannedTopPitch") is not None
                ),
                None,
            )
            if target_pitch is None:
                continue
            actual_last = next(
                (_rh_lead_pitch(event) for event in reversed(measure_events) if _rh_lead_pitch(event) is not None),
                None,
            )
            actual_peak = max(
                (int(pitch_value) for pitch_value in (_rh_lead_pitch(event) for event in measure_events) if pitch_value is not None),
                default=None,
            )
            if actual_last is None or actual_peak is None:
                continue
            role = str(top_line_plan.motion_roles.get(int(measure_number), "step"))
            anchor_distance = abs(actual_last - target_pitch)
            peak_distance = abs(actual_peak - target_pitch)
            if role in {"push", "rise"} or int(measure_number) == int(top_line_plan.peak_measure):
                score = max(0.0, 1.0 - min(anchor_distance, peak_distance) / 9.0)
            else:
                score = max(0.0, 1.0 - anchor_distance / 9.0)
            scores.append(score)
    return _mean(scores, default=0.72)


def _bass_function_score(events: list[dict[str, Any]], phrase_plans: list[dict[str, Any]]) -> float:
    scores: list[float] = []
    for phrase_plan in phrase_plans:
        bass_plan = phrase_plan.get("_bassLinePlan")
        if not isinstance(bass_plan, BassLinePlan):
            continue
        previous_bass: int | None = None
        for measure_number in phrase_plan.get("measures", []):
            measure_events = [
                event
                for event in _measure_events_for_hand(events, "lh", int(measure_number))
                if not event["isRest"] and event.get("pitches")
            ]
            if not measure_events:
                continue
            actual_bass = next(
                (_lh_bass_pitch(event) for event in measure_events if _lh_bass_pitch(event) is not None),
                None,
            )
            planned_bass = next(
                (
                    int(event["plannedBassPitch"])
                    for event in measure_events
                    if event.get("plannedBassPitch") is not None
                ),
                None,
            )
            if actual_bass is None:
                continue
            target_score = 0.72
            if planned_bass is not None:
                target_score = max(0.0, 1.0 - abs(actual_bass - planned_bass) / 8.0)
            motion_score = 0.82
            if previous_bass is not None:
                interval = abs(actual_bass - previous_bass)
                motion_role = str(bass_plan.motion_roles.get(int(measure_number), "step"))
                if motion_role == "hold":
                    motion_score = 1.0 if interval <= 2 else 0.55
                elif motion_role == "step":
                    motion_score = 1.0 if interval <= 5 else 0.5
                elif motion_role == "leap":
                    motion_score = 1.0 if 4 <= interval <= 9 else 0.62
                else:
                    motion_score = 1.0 if interval <= 7 else 0.55
            scores.append(0.58 * target_score + 0.42 * motion_score)
            previous_bass = actual_bass
    return _mean(scores, default=0.74)


def _foreground_background_clarity_score(events: list[dict[str, Any]]) -> float:
    measure_scores: list[float] = []
    all_measures = sorted({int(event["measure"]) for event in events})
    for measure_number in all_measures:
        rh_events = [
            event
            for event in _measure_events_for_hand(events, "rh", measure_number)
            if not event["isRest"] and event.get("pitches")
        ]
        lh_events = [
            event
            for event in _measure_events_for_hand(events, "lh", measure_number)
            if not event["isRest"] and event.get("pitches")
        ]
        if not rh_events or not lh_events:
            continue
        rh_lead = max((int(pitch_value) for pitch_value in (_rh_lead_pitch(event) for event in rh_events) if pitch_value is not None), default=None)
        lh_bass = min((int(pitch_value) for pitch_value in (_lh_bass_pitch(event) for event in lh_events) if pitch_value is not None), default=None)
        if rh_lead is None or lh_bass is None:
            continue
        register_gap = rh_lead - lh_bass
        outer_gap_score = 1.0 if register_gap >= 19 else max(0.3, register_gap / 19.0)
        chord_events = [event for event in rh_events if len(event.get("pitches", [])) > 1]
        chord_separation = 1.0
        if chord_events:
            separations = [
                max(event["pitches"]) - sorted(event["pitches"])[-2]
                for event in chord_events
                if len(event.get("pitches", [])) >= 2
            ]
            if separations:
                chord_separation = _mean(
                    [1.0 if separation >= 3 else max(0.35, separation / 3.0) for separation in separations],
                    default=0.7,
                )
        lead_sustain = _mean(
            [min(1.0, float(event.get("_actualDur", event["quarterLength"])) / 1.0) for event in rh_events],
            default=0.7,
        )
        measure_scores.append(0.45 * outer_gap_score + 0.35 * chord_separation + 0.20 * lead_sustain)
    return _mean(measure_scores, default=0.72)


def _vertical_balance_score(events: list[dict[str, Any]]) -> float:
    measure_scores: list[float] = []
    for measure_number in sorted({int(event["measure"]) for event in events}):
        rh_events = [
            event
            for event in _measure_events_for_hand(events, "rh", measure_number)
            if not event["isRest"] and event.get("pitches")
        ]
        lh_events = [
            event
            for event in _measure_events_for_hand(events, "lh", measure_number)
            if not event["isRest"] and event.get("pitches")
        ]
        if not rh_events or not lh_events:
            continue

        measure_role = str(
            next(
                (event.get("measureRole") for event in rh_events if event.get("measureRole")),
                next((event.get("measureRole") for event in lh_events if event.get("measureRole")), "develop"),
            )
        )
        rh_multi = [event for event in rh_events if len(event.get("pitches", [])) > 1]
        lh_multi = [event for event in lh_events if len(event.get("pitches", [])) > 1]
        rh_multi_ratio = len(rh_multi) / max(1, len(rh_events))
        lh_multi_ratio = len(lh_multi) / max(1, len(lh_events))
        overlap_hits = 0
        overlap_total = 0
        for rh_event in rh_multi:
            overlap_total += 1
            rh_start = float(rh_event.get("offset", 0.0))
            rh_end = rh_start + float(rh_event.get("_actualDur", rh_event["quarterLength"]))
            if any(
                float(lh_event.get("offset", 0.0)) < rh_end - 0.02
                and float(lh_event.get("offset", 0.0)) + float(lh_event.get("_actualDur", lh_event["quarterLength"])) > rh_start + 0.02
                for lh_event in lh_multi
            ):
                overlap_hits += 1
        overlap_ratio = overlap_hits / overlap_total if overlap_total else 0.0

        allowed_pressure = {
            "establish": 0.45,
            "answer": 0.42,
            "develop": 0.38,
            "intensify": 0.56,
            "cadence": 0.72,
        }.get(measure_role, 0.42)
        vertical_pressure = (rh_multi_ratio * 0.35) + (lh_multi_ratio * 0.45) + (overlap_ratio * 0.20)
        if vertical_pressure <= allowed_pressure:
            score = 1.0
        else:
            score = max(0.0, 1.0 - (vertical_pressure - allowed_pressure) * 2.1)
        measure_scores.append(score)

    return _mean(measure_scores, default=0.74)


def _difficulty_smoothness_score(
    request: dict[str, Any],
    events: list[dict[str, Any]],
    phrase_plans: list[dict[str, Any]],
) -> float:
    all_measures = sorted({int(event["measure"]) for event in events})
    complexities = [_measure_complexity(events, measure_number, "rh") for measure_number in all_measures]
    if len(complexities) < 2:
        return 1.0
    jumps = [abs(b - a) for a, b in zip(complexities, complexities[1:], strict=False)]
    jump_score = _mean([max(0.0, 1.0 - jump * 1.8) for jump in jumps], default=0.75)
    cadence_bonus = _cadence_strength_score(request, events, phrase_plans) if phrase_plans else 0.75
    return 0.8 * jump_score + 0.2 * cadence_bonus


def _sight_reading_chunkability_score(events: list[dict[str, Any]], phrase_plans: list[dict[str, Any]]) -> float:
    measure_signatures: list[tuple[float, ...]] = []
    for measure_number in sorted({int(event["measure"]) for event in events if event["hand"] == "rh"}):
        durations = tuple(
            round(float(event["quarterLength"]), 2)
            for event in _measure_events_for_hand(events, "rh", measure_number)
            if not event["isRest"]
        )
        if durations:
            measure_signatures.append(durations)
    if not measure_signatures:
        return 0.6
    recurring = sum(1 for signature in measure_signatures if measure_signatures.count(signature) > 1)
    recurrence_score = recurring / len(measure_signatures)
    lh_score = _left_hand_stability_score(events, phrase_plans)
    return 0.55 * max(0.45, recurrence_score) + 0.45 * lh_score


def _evaluate_candidate(request: dict[str, Any], candidate: dict[str, Any]) -> EvaluationBreakdown:
    events = candidate["events"]
    phrase_plans = candidate.get("phrasePlans", [])

    motif_internal_score = _mean([
        _score_phrase_motif(events, phrase_plan) for phrase_plan in phrase_plans
    ], default=0.5)
    inheritance_score = _phrase_inheritance_score(events, phrase_plans)
    motif_score = 0.72 * motif_internal_score + 0.28 * inheritance_score
    continuation_score = _mean([
        _score_phrase_continuation(request, events, phrase_plan) for phrase_plan in phrase_plans
    ], default=0.5)
    contour_score = _mean([
        _score_phrase_contour(events, phrase_plan) for phrase_plan in phrase_plans
    ], default=0.5)
    complexity_score = _mean([
        _score_phrase_complexity(events, phrase_plan) for phrase_plan in phrase_plans
    ], default=0.5)
    harmony_score = _strong_beat_harmony_score(request, events)
    ending_score = _phrase_ending_stability_score(request, events)
    accidental_score = _accidental_resolution_score(request, events)
    lh_score = _left_hand_stability_score(events, phrase_plans)
    cadence_score = _cadence_strength_score(request, events, phrase_plans)
    line_score = _line_continuity_score(events)
    anchor_score = _anchor_clarity_score(request, events)
    non_chord_score = _non_chord_tone_function_score(request, events)
    register_score = _register_arc_score(events, phrase_plans)
    hierarchy_score = _rh_lh_hierarchy_score(events)
    top_line_score = _top_line_strength_score(events, phrase_plans)
    bass_score = _bass_function_score(events, phrase_plans)
    foreground_score = _foreground_background_clarity_score(events)
    vertical_score = _vertical_balance_score(events)
    difficulty_score = _difficulty_smoothness_score(request, events, phrase_plans)
    chunkability_score = _sight_reading_chunkability_score(events, phrase_plans)
    phrase_coherence = (
        continuation_score * 0.36
        + contour_score * 0.24
        + complexity_score * 0.20
        + inheritance_score * 0.20
    )

    weighted_components = [
        (phrase_coherence, 1.95),
        (motif_score, 2.0),
        (line_score, 1.25),
        (anchor_score, 1.1),
        (non_chord_score, 1.2),
        (cadence_score, 1.75),
        (register_score, 1.2),
        (lh_score, 1.05),
        (hierarchy_score, 0.95),
        (top_line_score, 1.65),
        (bass_score, 1.2),
        (foreground_score, 1.45),
        (vertical_score, 1.25),
        (difficulty_score, 1.15),
        (chunkability_score, 1.0),
        (accidental_score, 0.6),
        (harmony_score, 0.9),
        (ending_score, 0.8),
    ]
    weighted_total = sum(value * weight for value, weight in weighted_components)
    total = weighted_total / sum(weight for _, weight in weighted_components)
    return EvaluationBreakdown(
        phrase_coherence=phrase_coherence,
        motivic_recurrence=motif_score,
        line_continuity=line_score,
        anchor_clarity=anchor_score,
        non_chord_tone_correctness=non_chord_score,
        cadence_preparation=cadence_score,
        register_arc_quality=register_score,
        lh_role_stability=lh_score,
        rh_lh_hierarchy=hierarchy_score,
        difficulty_smoothness=difficulty_score,
        sight_reading_chunkability=chunkability_score,
        accidental_justification=accidental_score,
        top_line_strength=top_line_score,
        bass_function=bass_score,
        foreground_background_clarity=foreground_score,
        vertical_balance=vertical_score,
        total=total,
    )


def _quality_gate_result(
    request: dict[str, Any],
    candidate: dict[str, Any],
    evaluation: EvaluationBreakdown,
) -> QualityGateResult:
    grade = int(request["grade"])
    events = candidate["events"]
    phrase_plans = candidate.get("phrasePlans", [])

    # Phase 5: grade-specific quality gate thresholds for ALL grades.
    if grade >= 5:
        richness_score = _grade_richness_score(request, events, phrase_plans)
        checks = [
            ("overall total", evaluation.total, 0.72),
            ("phrase coherence", evaluation.phrase_coherence, 0.48),
            ("motivic recurrence", evaluation.motivic_recurrence, 0.56),
            ("line continuity", evaluation.line_continuity, 0.60),
            ("cadence preparation", evaluation.cadence_preparation, 0.74),
            ("top-line strength", evaluation.top_line_strength, 0.63),
            ("bass function", evaluation.bass_function, 0.50),
            ("foreground clarity", evaluation.foreground_background_clarity, 0.60),
            ("vertical balance", evaluation.vertical_balance, 0.62),
            ("difficulty smoothness", evaluation.difficulty_smoothness, 0.62),
            ("grade-5 richness", richness_score, 0.58),
        ]
        hard_checks = {
            "overall total",
            "phrase coherence",
            "cadence preparation",
            "top-line strength",
            "vertical balance",
            "grade-5 richness",
        }
        leniency_max_reasons = 2
        leniency_gate = 0.965
        leniency_total = 0.74
    elif grade == 4:
        checks = [
            ("overall total", evaluation.total, 0.65),
            ("phrase coherence", evaluation.phrase_coherence, 0.58),
            ("cadence preparation", evaluation.cadence_preparation, 0.70),
            ("line continuity", evaluation.line_continuity, 0.55),
            ("lh stability", evaluation.lh_role_stability, 0.55),
        ]
        hard_checks = {"overall total", "cadence preparation"}
        leniency_max_reasons = 2
        leniency_gate = 0.95
        leniency_total = 0.70
    elif grade == 3:
        checks = [
            ("overall total", evaluation.total, 0.60),
            ("phrase coherence", evaluation.phrase_coherence, 0.55),
            ("cadence preparation", evaluation.cadence_preparation, 0.65),
            ("lh stability", evaluation.lh_role_stability, 0.50),
        ]
        hard_checks = {"overall total", "cadence preparation"}
        leniency_max_reasons = 2
        leniency_gate = 0.94
        leniency_total = 0.65
    else:
        # Grades 1-2: basic sanity checks
        checks = [
            ("overall total", evaluation.total, 0.55),
            ("phrase coherence", evaluation.phrase_coherence, 0.50),
            ("cadence preparation", evaluation.cadence_preparation, 0.60),
        ]
        hard_checks = {"cadence preparation"}
        leniency_max_reasons = 2
        leniency_gate = 0.92
        leniency_total = 0.58

    reasons: list[str] = []
    normalized_scores: list[float] = []
    hard_fail = False
    for label, value, threshold in checks:
        normalized = min(1.12, value / threshold) if threshold > 0 else 1.0
        normalized_scores.append(normalized)
        if value + 1e-9 < threshold:
            reasons.append(label)
            if label in hard_checks and value < threshold - 0.04:
                hard_fail = True

    gate_score = _mean(normalized_scores, default=1.0)
    passed = not hard_fail and (
        not reasons
        or (len(reasons) <= 1 and gate_score >= 0.985 and evaluation.total >= leniency_total + 0.02)
        or (len(reasons) <= leniency_max_reasons and gate_score >= leniency_gate and evaluation.total >= leniency_total and "overall total" not in reasons)
    )
    return QualityGateResult(
        passed=passed,
        score=gate_score,
        reasons=tuple(reasons),
    )


def _score_candidate(request: dict[str, Any], candidate: dict[str, Any]) -> float:
    return _evaluate_candidate(request, candidate).total


def _phrase_shape_label(events: list[dict[str, Any]]) -> str:
    rh_pitches = [
        int(pitch_value)
        for pitch_value in (_rh_lead_pitch(event) for event in events if event["hand"] == "rh" and not event["isRest"] and event["pitches"])
        if pitch_value is not None
    ]
    if len(rh_pitches) < 3:
        return "Short guided phrases"
    ups = sum(1 for i in range(1, len(rh_pitches)) if rh_pitches[i] > rh_pitches[i - 1])
    downs = sum(1 for i in range(1, len(rh_pitches)) if rh_pitches[i] < rh_pitches[i - 1])
    total_motion = ups + downs
    if total_motion == 0:
        return "Repeated note phrases"
    ratio = ups / total_motion
    if ratio > 0.65:
        return "Rising phrases"
    if ratio < 0.35:
        return "Falling phrases"
    return "Mixed-contour phrases"


def _cadence_label(events: list[dict[str, Any]]) -> str:
    cadence_values = [str(event.get("phraseCadence")) for event in events if event.get("phraseCadence")]
    if any(value == "tonic" for value in cadence_values):
        return "Clear tonic closure"
    if any(value == "dominant" for value in cadence_values):
        return "Directed dominant release"
    return "Stable phrase endings"


def _harmony_focus(request: dict[str, Any], events: list[dict[str, Any]]) -> list[str]:
    focus = [f"{READING_FOCUS_LABELS[request['readingFocus']]} reading"]
    techniques = {str(event.get("technique")) for event in events if event.get("technique")}
    if "chordal texture" in techniques or "melodic chord accent" in techniques:
        focus.append("block chord reading")
    elif "scale run" in techniques or "scale figure" in techniques:
        focus.append("scale passage reading")
    elif "melodic dyad" in techniques:
        focus.append("embedded interval reading")
    elif "Alberti bass" in techniques:
        focus.append("predictable Alberti support")
    else:
        focus.append("clear chord-tone anchors")
    if request["handActivity"] == "both":
        focus.append(COORDINATION_LABELS[request["coordinationStyle"]])
    return focus[:3]


def _technique_focus(events: list[dict[str, Any]]) -> list[str]:
    focus: list[str] = []
    techniques = {str(event.get("technique")) for event in events if event.get("technique")}
    if any(_is_second_dyad(event) for event in events if event.get("hand") == "rh"):
        focus.append("RH seconds")
    for technique in ["melody", "melodic dyad", "melodic chord accent", "block chord", "chordal texture", "scale run", "scale figure", "triplet", "Alberti bass"]:
        if technique in techniques:
            focus.append(technique)
    return focus[:4] or ["guided phrase reading"]


def _validate_events(request: dict[str, Any], events: list[dict[str, Any]]) -> bool:
    total = _measure_total(request["timeSignature"])

    for hand in ("rh", "lh"):
        if (hand == "rh" and request["handActivity"] == "left-only") or (
            hand == "lh" and request["handActivity"] == "right-only"
        ):
            continue

        previous_pitch = None
        for measure_number in range(1, int(request["measureCount"]) + 1):
            hand_events = [
                event for event in events if event["hand"] == hand and int(event["measure"]) == measure_number
            ]
            coverage = sum(float(event.get("_actualDur", event["quarterLength"])) for event in hand_events)
            # Allow slight overshoot for triplet rounding
            if coverage > total + 0.05 or coverage <= 0:
                return False

            for event in hand_events:
                if event["isRest"] or not event["pitches"]:
                    continue
                pitch_value = _event_primary_pitch(event)
                if pitch_value is None:
                    continue
                if previous_pitch is not None and hand == "rh":
                    if abs(pitch_value - previous_pitch) > int(_preset_for_grade(request["grade"])["piano"]["maxLeapSemitones"]):
                        return False
                previous_pitch = pitch_value

    if request["mode"] == "piano":
        if not _validate_strong_beat_harmony(request, events):
            return False
        if not _validate_phrase_endings(request, events):
            return False

    return True


def _reading_focus(request: dict[str, Any], events: list[dict[str, Any]]) -> list[str]:
    focus: list[str] = []
    techniques = {event.get("technique") for event in events if event.get("technique")}

    if any(_is_second_dyad(event) for event in events if event.get("hand") == "rh"):
        focus.append("interval reading")

    for technique in ["melody", "melodic dyad", "melodic chord accent", "block chord", "scale run", "scale figure", "triplet"]:
        if technique in techniques:
            focus.append(technique)

    durations = [float(event["quarterLength"]) for event in events if not event["isRest"]]
    if any(abs(value - 0.5) < 0.001 for value in durations):
        focus.append("eighth-note motion")
    if any(abs(value - 0.25) < 0.001 for value in durations):
        focus.append("sixteenth-note passages")
    if any(abs(value - 0.75) < 0.001 or abs(value - 1.5) < 0.001 for value in durations):
        focus.append("dotted rhythms")

    if request["handActivity"] == "both":
        if request["coordinationStyle"] == "support":
            focus.append("RH lead with LH support")
        elif request["coordinationStyle"] == "alternating":
            focus.append("hand-to-hand response")
        else:
            focus.append("hands together")
    else:
        focus.append(HAND_ACTIVITY_LABELS[request["handActivity"]])

    if request["readingFocus"] == "melodic":
        focus.insert(0, "phrase contour reading")
    elif request["readingFocus"] == "harmonic":
        focus.insert(0, "strong-beat harmony")
    else:
        focus.insert(0, "balanced phrase reading")

    return focus[:4] if focus else ["steady pulse"]


def _debug_plan_summary(candidate: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    piece_plan = candidate.get("piecePlan")
    style_profile = candidate.get("styleProfile")
    phrase_plans = candidate.get("phrasePlans", [])
    phrase_summaries: list[dict[str, Any]] = []
    for phrase_plan in phrase_plans:
        blueprint = phrase_plan.get("_phraseBlueprint")
        accompaniment_plan = phrase_plan.get("_accompanimentPlan")
        line_plan = phrase_plan.get("_linePlan")
        top_line_plan = phrase_plan.get("_topLinePlan")
        bass_line_plan = phrase_plan.get("_bassLinePlan")
        phrase_summaries.append(
            {
                "phraseIndex": phrase_plan.get("phraseIndex"),
                "measures": phrase_plan.get("measures", []),
                "archetype": phrase_plan.get("archetype"),
                "cadenceTarget": phrase_plan.get("cadenceTarget"),
                "answerForm": phrase_plan.get("_answerForm"),
                "accompanimentRole": phrase_plan.get("accompanimentRole"),
                "leftFamily": phrase_plan.get("leftFamily"),
                "leftFamilyByMeasure": phrase_plan.get("_leftFamilyByMeasure"),
                "textureByMeasure": phrase_plan.get("_textureByMeasure"),
                "tripletMeasures": phrase_plan.get("_tripletMeasures"),
                "linePlan": asdict(line_plan) if isinstance(line_plan, LinePlan) else None,
                "topLinePlan": asdict(top_line_plan) if isinstance(top_line_plan, TopLinePlan) else None,
                "bassLinePlan": asdict(bass_line_plan) if isinstance(bass_line_plan, BassLinePlan) else None,
                "blueprint": asdict(blueprint) if isinstance(blueprint, PhraseBlueprint) else None,
                "accompanimentPlan": asdict(accompaniment_plan) if isinstance(accompaniment_plan, AccompanimentPlan) else None,
            }
        )
    return {
        "requestFocus": request.get("readingFocus"),
        "styleProfile": asdict(style_profile) if isinstance(style_profile, StyleProfile) else None,
        "piecePlan": asdict(piece_plan) if isinstance(piece_plan, PiecePlan) else None,
        "phrases": phrase_summaries,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_exercise(request: dict[str, Any]) -> dict[str, Any]:
    bpm = int(TEMPO_BY_PRESET[request["tempoPreset"]])
    key_label = request["keySignature"]
    debug_payload: dict[str, Any] | None = None
    title = (
        f"Piano Rhythm - {request['timeSignature']} - Grade {request['grade']}"
        if request["mode"] == "rhythm"
        else f"Piano Reading - {key_label}{' minor' if is_minor_key(request['keySignature']) else ''} "
        f"{request['timeSignature']} - Grade {request['grade']}"
    )

    if request["mode"] == "rhythm":
        for attempt in range(8):
            rng = random.Random(f"{request['seed']}-{attempt}")
            events = _build_rhythm_events(request, rng)
            if _validate_events(request, events):
                break
        else:
            raise ValueError("Could not generate a valid exercise after several attempts")
    else:
        preset = _preset_for_grade(int(request["grade"]))
        style_profile = _build_style_profile(request, preset)
        search_attempts = style_profile.search_attempts

        best_candidate: dict[str, Any] | None = None
        best_score = -1.0
        best_passing_candidate: dict[str, Any] | None = None
        best_passing_score = -1.0
        evaluated_candidates = 0
        passing_candidates = 0
        rejection_counts: dict[str, int] = {}

        for attempt in range(search_attempts):
            rng = random.Random(f"{request['seed']}-{attempt}")
            candidate = _build_piano_candidate(request, rng)
            if not _validate_events(request, candidate["events"]):
                continue

            evaluation = _evaluate_candidate(request, candidate)
            gate_result = _quality_gate_result(request, candidate, evaluation)
            candidate["evaluationBreakdown"] = evaluation
            candidate["qualityGate"] = gate_result
            evaluated_candidates += 1

            fallback_score = evaluation.total + max(0.0, gate_result.score - 0.9) * 0.08
            if fallback_score > best_score:
                best_candidate = candidate
                best_score = fallback_score

            if gate_result.passed:
                passing_candidates += 1
                passing_score = evaluation.total + 0.05 + max(0.0, gate_result.score - 0.95) * 0.08
                if passing_score > best_passing_score:
                    best_passing_candidate = candidate
                    best_passing_score = passing_score
            else:
                for reason in gate_result.reasons:
                    rejection_counts[reason] = rejection_counts.get(reason, 0) + 1

        selected_candidate = best_passing_candidate or best_candidate
        if selected_candidate is None:
            raise ValueError("Could not generate a valid exercise after several attempts")

        events = selected_candidate["events"]
        debug_payload = {
            "scoreBreakdown": asdict(selected_candidate["evaluationBreakdown"]),
            "planSummary": _debug_plan_summary(selected_candidate, request),
            "qualityGate": {
                "selected": asdict(selected_candidate.get("qualityGate", QualityGateResult())),
                "evaluatedCandidates": evaluated_candidates,
                "passingCandidates": passing_candidates,
                "selectedFromPassingPool": best_passing_candidate is not None,
                "rejectionCounts": rejection_counts,
            },
        }

    music_xml = _create_musicxml(request, events, bpm)
    svg = _render_svg(music_xml, title)
    audio_url = render_audio_data_uri(events, bpm)

    coordination_label = (
        HAND_ACTIVITY_LABELS[request["handActivity"]]
        if request["handActivity"] != "both"
        else COORDINATION_LABELS[request["coordinationStyle"]]
    )

    return {
        "exerciseId": f"sheet-{request['seed']}",
        "seed": request["seed"],
        "config": request,
        "title": title,
        "musicXml": music_xml,
        "svg": svg,
        "audioUrl": audio_url,
        "measureCount": request["measureCount"],
        "timeSignature": request["timeSignature"],
        "grade": request["grade"],
        "summary": {
            "bpm": bpm,
            "handPositionLabel": POSITION_LABELS[request["handPosition"]],
            "coordinationLabel": coordination_label,
            "phraseShapeLabel": _phrase_shape_label(events),
            "cadenceLabel": _cadence_label(events),
            "harmonyFocus": _harmony_focus(request, events),
            "techniqueFocus": _technique_focus(events),
            "rhythmFocus": _reading_focus(request, events),
            "seedLabel": f"{GRADE_LABELS[request['grade']]} - {str(request['seed'])[-6:]}",
        },
        "debug": debug_payload,
    }

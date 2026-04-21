"""Accidental injection and left-hand fixed patterns."""
from __future__ import annotations

import random
from typing import Any

from ._types import AccompanimentPlan
from ._chord import (
    _simultaneous_span_cap,
    _bounded_upper_tones,
    _normalize_pitch_stack,
    _sequence_from_cycle,
    _preferred_left_families,
)
from ._texture import _nearest_pool_index


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

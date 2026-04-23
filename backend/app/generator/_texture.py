"""Texture builders for the sheet music generator.

Contains functions that construct measure-level musical content:
melodic lines, chordal textures, running figures, and rhythm replay
(Phase 3 A/A' replay).  These are called by the piano candidate
builder in _monolith.py.
"""
from __future__ import annotations

import random
from typing import Any

from ..config import KEY_TONIC_PITCH_CLASS, HARMONY_INTERVALS
from ._types import LinePlan
from ._helpers import _fit_measure, _fit_measure_variants
from ._pitch import _key_pitch_classes
from ._rhythm import _RHYTHM_CELLS_SIMPLE, _CADENCE_LIBRARY, _contour_direction_bias
from ._chord import (
    _chord_pitch_classes,
    _chord_tones_in_pool,
    _build_block_triad,
    _simultaneous_span_cap,
    _build_voiced_block_chord,
    _stable_tone,
    _weighted_pitch_select,
)


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


def _align_target_pitch(
    pool: list[int],
    target_pitch: int,
    reference_pitch: int,
    max_leap: int,
) -> int:
    reachable = [
        candidate
        for candidate in pool
        if abs(int(candidate) - int(reference_pitch)) <= max_leap
    ]
    search_pool = reachable or pool
    return min(search_pool, key=lambda candidate: abs(int(candidate) - int(target_pitch)))


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
    allowed_durations: list[float] | None = None,
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

    # Clamp durations to allowed set (prevents eighth notes in lower grades)
    if allowed_durations:
        min_allowed = min(allowed_durations)
        clamped: list[float] = []
        for d in durations:
            if d < min_allowed:
                # Merge into previous duration or skip
                if clamped:
                    clamped[-1] = round(clamped[-1] + d, 3)
                else:
                    clamped.append(round(d, 3))
            else:
                clamped.append(round(d, 3))
        durations = clamped
        # Re-trim steps to match new duration count
        steps = steps[: max(1, len(durations) - 1)]

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
        aligned_pitch = _align_target_pitch(
            pool,
            int(target_pitch),
            prev_pitch,
            max_leap,
        )
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
        "opening": _chord_pitch_classes(key_signature, harmony),
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
        aligned_pitch = _align_target_pitch(pool, target_pitch, prev_pitch, max_leap)
        last_event["pitches"] = [aligned_pitch]
        prev_pitch = aligned_pitch
        recent = (recent[:-1] + [aligned_pitch])[-6:] if recent else [aligned_pitch]

    events = _apply_ornament_to_events(events, ornament.name, allow_accidentals)
    return events, prev_pitch, recent, direction, cursor, last_event


# Final-bar RH cadence templates: (name, [(duration, scale_degree), ...], min_grade, weight).
# Scale degrees: 1=tonic, 2=supertonic, 3=mediant, 5=dominant.
# Every template MUST end on scale degree 1.  The penultimate bar currently
# resolves to 2̂ (supertonic), so templates starting on 1, 2, or 3 read
# smoothly.
_RH_FINAL_CADENCE_TEMPLATES: dict[str, list[tuple[str, list[tuple[float, int]], int, float]]] = {
    "4/4": [
        ("whole",        [(4.0, 1)],                                  1, 0.55),
        ("half_half",    [(2.0, 1), (2.0, 1)],                        1, 1.10),
        ("q_dotted",     [(1.0, 1), (3.0, 1)],                        1, 0.95),
        ("dotted_q",     [(3.0, 1), (1.0, 1)],                        2, 0.75),
        ("qqh_121",      [(1.0, 1), (1.0, 2), (2.0, 1)],              2, 0.95),
        ("qqh_321",      [(1.0, 3), (1.0, 2), (2.0, 1)],              2, 1.00),
        ("hh_31",        [(2.0, 3), (2.0, 1)],                        2, 0.70),
        ("qqqq_1321",    [(1.0, 1), (1.0, 3), (1.0, 2), (1.0, 1)],    3, 0.85),
    ],
    "3/4": [
        ("dotted_half",  [(3.0, 1)],                                  1, 0.60),
        ("hq_11",        [(2.0, 1), (1.0, 1)],                        1, 1.00),
        ("qh_11",        [(1.0, 1), (2.0, 1)],                        1, 1.00),
        ("qqq_321",      [(1.0, 3), (1.0, 2), (1.0, 1)],              2, 1.05),
        ("qqq_121",      [(1.0, 1), (1.0, 2), (1.0, 1)],              2, 0.90),
    ],
    "2/4": [
        ("half",         [(2.0, 1)],                                  1, 0.55),
        ("qq_31",        [(1.0, 3), (1.0, 1)],                        1, 1.00),
        ("qq_21",        [(1.0, 2), (1.0, 1)],                        1, 1.00),
        ("qq_11",        [(1.0, 1), (1.0, 1)],                        1, 0.80),
    ],
    "6/8": [
        ("dotted_half",  [(3.0, 1)],                                  1, 0.70),
        ("dq_dq_11",     [(1.5, 1), (1.5, 1)],                        1, 1.00),
        ("dq_dq_31",     [(1.5, 3), (1.5, 1)],                        2, 0.90),
    ],
}


# Final-bar LH cadence templates: (name, [(duration, degrees_as_tuple)], min_grade, weight).
# degrees_as_tuple is scale degrees stacked as a chord in LH (e.g. (1,) for
# tonic alone, (1, 5) for tonic + fifth, (1,) fifth-less).
# These are chosen independently of the RH template so patterns don't lock
# together; they always sound tonic because every sonority is on scale-degree 1.
_LH_FINAL_CADENCE_TEMPLATES: dict[str, list[tuple[str, list[tuple[float, tuple[int, ...]]], int, float]]] = {
    "4/4": [
        ("whole_root",        [(4.0, (1,))],                                   1, 0.80),
        ("whole_chord",       [(4.0, (1, 5))],                                 3, 0.70),
        ("half_half_root",    [(2.0, (1,)), (2.0, (1,))],                      1, 0.95),
        ("half_half_chord",   [(2.0, (1, 5)), (2.0, (1, 5))],                  2, 0.90),
        ("q_dotted_root",     [(1.0, (1,)), (3.0, (1,))],                      1, 0.85),
        ("dotted_q_root",     [(3.0, (1,)), (1.0, (1,))],                      2, 0.65),
        ("h_h_root_chord",    [(2.0, (1,)), (2.0, (1, 5))],                    2, 0.70),
    ],
    "3/4": [
        ("dotted_half_root",  [(3.0, (1,))],                                   1, 0.90),
        ("dotted_half_chord", [(3.0, (1, 5))],                                 3, 0.70),
        ("hq_root",           [(2.0, (1,)), (1.0, (1,))],                      1, 0.95),
        ("qh_root",           [(1.0, (1,)), (2.0, (1,))],                      1, 0.95),
    ],
    "2/4": [
        ("half_root",         [(2.0, (1,))],                                   1, 0.85),
        ("half_chord",        [(2.0, (1, 5))],                                 3, 0.65),
        ("qq_root",           [(1.0, (1,)), (1.0, (1,))],                      1, 0.90),
    ],
    "6/8": [
        ("dotted_half_root",  [(3.0, (1,))],                                   1, 0.95),
        ("dq_dq_root",        [(1.5, (1,)), (1.5, (1,))],                      1, 0.85),
    ],
}


def _pick_cadence_template(
    templates: list[tuple[str, list, int, float]],
    grade: int,
    rng: random.Random,
) -> tuple[str, list]:
    eligible = [(n, pattern, weight) for (n, pattern, mg, weight) in templates if grade >= mg]
    if not eligible:
        name, pattern, _, _ = templates[0]
        return name, pattern
    names = [n for (n, _p, _w) in eligible]
    patterns = [p for (_n, p, _w) in eligible]
    weights = [w for (_n, _p, w) in eligible]
    choice_idx = rng.choices(range(len(eligible)), weights=weights, k=1)[0]
    return names[choice_idx], patterns[choice_idx]


def _scale_degree_to_pitch(
    pool: list[int],
    key_signature: str,
    degree: int,
    near_pitch: int,
) -> int | None:
    """Resolve a diatonic scale degree (1-based) to a MIDI pitch from the pool.

    Picks the pool pitch in the requested scale-degree closest to near_pitch.
    Returns None if no pool pitch matches.
    """
    scale = sorted(_key_pitch_classes(key_signature))
    if not scale:
        return None
    tonic_pc = KEY_TONIC_PITCH_CLASS.get(key_signature, scale[0])
    try:
        tonic_idx = scale.index(tonic_pc)
    except ValueError:
        tonic_idx = 0
    target_pc = scale[(tonic_idx + (degree - 1)) % len(scale)]
    candidates = [p for p in pool if p % 12 == target_pc]
    if not candidates:
        return None
    return min(candidates, key=lambda c: abs(c - near_pitch))


def _apply_piece_ending(
    events: list[dict[str, Any]],
    pool: list[int],
    key_signature: str,
    prev_pitch: int,
    total: float,
    time_signature: str = "4/4",
    grade: int = 1,
    rng: random.Random | None = None,
) -> None:
    """Rewrite the final measure using a cadence template bank.

    Picks one RH cadence template per call so pieces don't all collapse to a
    tonic whole note.  The last note always resolves to scale-degree 1 so the
    ending still reads as definitive.
    """
    if not events:
        return

    tonic_pc = KEY_TONIC_PITCH_CLASS.get(key_signature, 0)
    tonic_candidates = [p for p in pool if p % 12 == tonic_pc]
    fallback_tonic = (
        min(tonic_candidates, key=lambda c: abs(c - prev_pitch))
        if tonic_candidates
        else prev_pitch
    )

    templates = _RH_FINAL_CADENCE_TEMPLATES.get(time_signature)
    hand = events[0].get("hand", "rh")
    effective_rng = rng if rng is not None else random.Random(0)

    # If we have no template bank for this meter, fall back to the legacy
    # whole-note ending so rare meters still produce a valid output.
    if not templates:
        events.clear()
        events.append({
            "hand": hand,
            "offset": 0.0,
            "quarterLength": total,
            "isRest": False,
            "pitches": [fallback_tonic],
            "technique": "final tonic",
            "fermata": True,
        })
        return

    template_name, pattern = _pick_cadence_template(templates, grade, effective_rng)

    # Verify the pattern sums to `total` (defensive — avoid malformed bar).
    pattern_total = round(sum(dur for dur, _deg in pattern), 3)
    if abs(pattern_total - round(total, 3)) > 0.01:
        # Degrade to a whole-note tonic if template doesn't fit.
        events.clear()
        events.append({
            "hand": hand,
            "offset": 0.0,
            "quarterLength": total,
            "isRest": False,
            "pitches": [fallback_tonic],
            "technique": "final tonic",
            "fermata": True,
        })
        return

    events.clear()
    offset = 0.0
    near_pitch = prev_pitch
    for idx, (duration, degree) in enumerate(pattern):
        pitch = _scale_degree_to_pitch(pool, key_signature, degree, near_pitch)
        if pitch is None:
            pitch = fallback_tonic
        is_last = (idx == len(pattern) - 1)
        event: dict[str, Any] = {
            "hand": hand,
            "offset": round(offset, 3),
            "quarterLength": float(duration),
            "isRest": False,
            "pitches": [pitch],
            "technique": "final cadence" if not is_last else "final tonic",
        }
        if is_last:
            event["fermata"] = True
        events.append(event)
        offset += float(duration)
        near_pitch = pitch


def _apply_lh_variation_pass(
    events: list[dict[str, Any]],
    total: float,
    measure_count: int,
    rng: random.Random,
) -> list[dict[str, Any]]:
    """Break up runs of identical LH rhythmic shapes.

    When the LH uses the same per-measure rhythmic shape for ≥3 consecutive
    bars, rewrites the 3rd (and every 2nd thereafter) bar into a simpler
    block-half shape using the same pitches.  Sight-reading material breaks
    LH textures every 2-3 bars — perpetual Alberti or perpetual repeated-note
    patterns are a strong "engine-generated" tell.
    """
    from collections import defaultdict

    # Group LH events by measure (never touch the final bar — it owns its
    # own cadence template).
    lh_by_measure: dict[int, list[dict[str, Any]]] = defaultdict(list)
    other_events: list[dict[str, Any]] = []
    final_measure = int(measure_count)
    for ev in events:
        if ev.get("hand") == "lh" and int(ev.get("measure", 0)) != final_measure:
            lh_by_measure[int(ev["measure"])].append(ev)
        else:
            other_events.append(ev)

    if not lh_by_measure:
        return events

    # Build per-measure rhythm signatures: tuple of (quarterLength, pitch_count, is_rest).
    def _sig(measure_events: list[dict[str, Any]]) -> tuple:
        return tuple(
            (
                round(float(e.get("quarterLength", 1.0)), 3),
                len(e.get("pitches", [])),
                bool(e.get("isRest", False)),
            )
            for e in measure_events
        )

    sorted_measures = sorted(lh_by_measure)
    signatures = [_sig(lh_by_measure[m]) for m in sorted_measures]

    # Find runs of identical signatures of length >= 3.
    to_vary: set[int] = set()
    run_start = 0
    while run_start < len(signatures):
        run_end = run_start
        while run_end + 1 < len(signatures) and signatures[run_end + 1] == signatures[run_start]:
            run_end += 1
        run_len = run_end - run_start + 1
        if run_len >= 3:
            # Mark every other bar starting from the 3rd of the run for variation.
            for offset_in_run in range(2, run_len, 2):
                to_vary.add(sorted_measures[run_start + offset_in_run])
        run_start = run_end + 1

    if not to_vary:
        return events

    for measure_number in to_vary:
        measure_events = lh_by_measure[measure_number]
        if not measure_events:
            continue
        # Collect pool of pitches used this bar — we'll preserve harmony by
        # using the lowest as bass + (optionally) the next above within an
        # octave as the chord tone.
        pitches: set[int] = set()
        for e in measure_events:
            if not e.get("isRest"):
                for p in e.get("pitches", []):
                    pitches.add(int(p))
        if not pitches:
            continue
        sorted_pitches = sorted(pitches)
        bass = sorted_pitches[0]
        chord: list[int] = [bass]
        for candidate in sorted_pitches[1:]:
            if candidate - bass <= 12 and candidate != bass:
                chord.append(candidate)
                break

        # Pick a simpler shape — prefer block-half, sometimes held whole.
        # Draw from a fixed palette so variation reads as deliberate, not random.
        base_offset = float(measure_events[0].get("offset", 0.0))
        # Preserve the upstream metadata so downstream passes (ties,
        # articulation, dynamics) still find the right bar context.
        template_event = measure_events[0]
        metadata = {
            k: template_event.get(k)
            for k in (
                "measure",
                "harmony",
                "phraseIndex",
                "phraseCadence",
                "leftFamily",
                "measureRole",
                "targetDensity",
                "phraseContour",
                "rhTexture",
            )
            if k in template_event
        }

        palette = [
            ("block_half", [(total / 2.0, sorted(chord)), (total / 2.0, sorted(chord))], 1.0),
            ("held_chord", [(total, sorted(chord))], 0.85),
            ("bass_then_chord", [(total / 2.0, [bass]), (total / 2.0, sorted(chord))], 0.8),
        ]
        names = [p[0] for p in palette]
        weights = [p[2] for p in palette]
        choice_idx = rng.choices(range(len(palette)), weights=weights, k=1)[0]
        _name, shape, _w = palette[choice_idx]

        rebuilt: list[dict[str, Any]] = []
        cursor = 0.0
        for dur, chord_pitches in shape:
            ev: dict[str, Any] = {
                "hand": "lh",
                "offset": round(base_offset + cursor, 3),
                "quarterLength": float(dur),
                "isRest": False,
                "pitches": list(chord_pitches),
                "technique": "lh variation",
                **metadata,
            }
            rebuilt.append(ev)
            cursor += float(dur)
        lh_by_measure[measure_number] = rebuilt

    # Reassemble the event list, preserving insertion order by measure/offset.
    rebuilt_lh: list[dict[str, Any]] = []
    for m in sorted_measures:
        rebuilt_lh.extend(lh_by_measure[m])

    # Merge with RH + final-bar LH events and re-sort by (measure, offset, hand).
    merged = other_events + rebuilt_lh
    merged.sort(key=lambda e: (int(e.get("measure", 0)), float(e.get("offset", 0.0)), 0 if e.get("hand") == "rh" else 1))
    return merged


def _apply_lh_piece_ending(
    pool: list[int],
    key_signature: str,
    prev_bass_pitch: int,
    total: float,
    time_signature: str,
    grade: int,
    rng: random.Random,
) -> list[dict[str, Any]]:
    """Build the LH final measure using the LH cadence template bank.

    Returns a freshly-built list of LH events for the final bar.  All sonorities
    are tonic-rooted so the piece still resolves cleanly.
    """
    tonic_pc = KEY_TONIC_PITCH_CLASS.get(key_signature, 0)
    tonic_candidates = [p for p in pool if p % 12 == tonic_pc]
    if tonic_candidates:
        bass_note = min(tonic_candidates, key=lambda c: abs(c - prev_bass_pitch))
    else:
        bass_note = prev_bass_pitch

    fifth_pc = (tonic_pc + 7) % 12
    fifth_above = next(
        (p for p in sorted(pool) if p % 12 == fifth_pc and p > bass_note and p - bass_note <= 12),
        None,
    )

    templates = _LH_FINAL_CADENCE_TEMPLATES.get(time_signature)
    if not templates:
        return [{
            "hand": "lh",
            "offset": 0.0,
            "quarterLength": total,
            "isRest": False,
            "pitches": [bass_note],
            "technique": "final chord",
            "fermata": True,
        }]

    _name, pattern = _pick_cadence_template(templates, grade, rng)
    pattern_total = round(sum(dur for dur, _degs in pattern), 3)
    if abs(pattern_total - round(total, 3)) > 0.01:
        return [{
            "hand": "lh",
            "offset": 0.0,
            "quarterLength": total,
            "isRest": False,
            "pitches": [bass_note],
            "technique": "final chord",
            "fermata": True,
        }]

    result: list[dict[str, Any]] = []
    offset = 0.0
    for idx, (duration, degrees) in enumerate(pattern):
        pitches: list[int] = [bass_note]
        if 5 in degrees and fifth_above is not None:
            pitches.append(fifth_above)
        is_last = (idx == len(pattern) - 1)
        event: dict[str, Any] = {
            "hand": "lh",
            "offset": round(offset, 3),
            "quarterLength": float(duration),
            "isRest": False,
            "pitches": sorted(pitches),
            "technique": "final chord" if not is_last else "final tonic",
        }
        if is_last:
            event["fermata"] = True
        result.append(event)
        offset += float(duration)
    return result


def _apply_penultimate_ending(
    events: list[dict[str, Any]],
    pool: list[int],
    key_signature: str,
    prev_pitch: int,
    total: float,
) -> None:
    """Shape the penultimate measure to approach tonic by step.

    Forces the last note to scale-degree 2 (supertonic), creating a
    classic 2->1 resolution into the final measure.  Also simplifies
    the last beat to a longer note for a natural deceleration.
    """
    last_pitched = None
    for e in reversed(events):
        if not e.get("isRest") and e.get("pitches") and len(e["pitches"]) == 1:
            last_pitched = e
            break
    if not last_pitched:
        return

    tonic_pc = KEY_TONIC_PITCH_CLASS.get(key_signature, 0)
    # Supertonic is one diatonic step above tonic — find it from the scale
    scale_pcs = _key_pitch_classes(key_signature)
    sorted_scale = sorted(scale_pcs)
    tonic_idx = sorted_scale.index(tonic_pc) if tonic_pc in sorted_scale else 0
    supertonic_pc = sorted_scale[(tonic_idx + 1) % len(sorted_scale)]

    supertonic_candidates = [p for p in pool if p % 12 == supertonic_pc]
    if not supertonic_candidates:
        return

    best_super = min(supertonic_candidates, key=lambda c: abs(c - prev_pitch))
    last_pitched["pitches"] = [best_super]

    # Extend the last note to fill remaining time (simplify the tail).
    # Snap to nearest expressible duration to avoid floating-point artifacts
    # from triplets (e.g. 0.501 -> 0.5).
    _SNAP_DURS = [0.25, 1/3, 0.5, 2/3, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0]
    last_dur = float(last_pitched["quarterLength"])
    last_offset = float(last_pitched["offset"])
    remaining = round(total - last_offset, 3)
    if remaining > last_dur:
        # Snap to nearest standard duration
        snapped = min(_SNAP_DURS, key=lambda d: abs(d - remaining))
        if abs(snapped - remaining) < 0.01:
            remaining = snapped
        idx = events.index(last_pitched)
        del events[idx + 1:]
        last_pitched["quarterLength"] = remaining


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

    # Phase 7: tension -> release arc — active intensity response
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
    if is_piece_final:
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
            # Ending logic is applied in _build_piano_candidate after all builders
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
            allowed_durations=allowed_durations,
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

    # Note: ending logic (tonic + fermata) is applied in _build_piano_candidate

    # Apply accidentals (with piece-level budget tracking)
    pitched_groups = [e["pitches"] for e in events if not e["isRest"] and e["pitches"]]
    piece_acc_count = int(phrase_plan.get("_pieceAccidentalCount", 0))
    # Store current measure role for accidental role gating
    phrase_plan["_currentMeasureRole"] = measure_role
    if pitched_groups:
        from ._left_hand import _apply_accidental  # lazy to avoid circular import
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


def _inject_chromatic_approaches_post(
    events: list[dict[str, Any]],
    request: dict[str, Any],
    rng: random.Random,
) -> list[dict[str, Any]]:
    """Inject 1-3 chromatic approach notes into the RH of the winning candidate.

    Works on the final event list so it survives multi-candidate scoring.
    Targets develop/intensify/answer measures only (keeps openings and
    cadences clean).
    """
    key_signature = request["keySignature"]
    pitch_classes = _key_pitch_classes(key_signature)
    measure_count = int(request.get("measureCount", 8))

    # Collect RH pitched-note indices in eligible measures
    eligible_pairs: list[tuple[int, int]] = []  # (index_of_note, index_of_next_note)
    rh_indices = [
        i for i, e in enumerate(events)
        if e.get("hand") == "rh"
        and not e.get("isRest")
        and e.get("pitches")
        and len(e["pitches"]) == 1
    ]
    for a, b in zip(rh_indices, rh_indices[1:]):
        ea, eb = events[a], events[b]
        # Same measure and eligible role
        if int(ea.get("measure", 0)) != int(eb.get("measure", 0)):
            continue
        role = str(ea.get("measureRole", ""))
        m_num = int(ea.get("measure", 0))
        if role not in ("develop", "intensify", "answer"):
            continue
        # Don't touch the final measure
        if m_num >= measure_count:
            continue
        eligible_pairs.append((a, b))

    if not eligible_pairs:
        return events

    # Pick 1-3 pairs to chromaticize
    target_count = min(len(eligible_pairs), rng.randint(1, 3))
    chosen = rng.sample(eligible_pairs, target_count)
    applied = 0
    for idx_a, idx_b in chosen:
        target_pitch = int(events[idx_b]["pitches"][0])
        cur_pitch = int(events[idx_a]["pitches"][0])
        # Approach from below or above depending on direction
        if cur_pitch <= target_pitch:
            approach = target_pitch - 1
        else:
            approach = target_pitch + 1
        # Ensure approach is actually chromatic
        if approach % 12 in pitch_classes:
            approach = target_pitch + 1 if cur_pitch <= target_pitch else target_pitch - 1
        if approach % 12 in pitch_classes:
            continue  # both directions diatonic — skip
        events[idx_a]["pitches"] = [approach]
        events[idx_a]["technique"] = "chromatic approach"
        applied += 1

    return events


def _inject_chromatic_approach(
    events: list[dict[str, Any]],
    pool: list[int],
    key_signature: str,
    rng: random.Random,
) -> list[dict[str, Any]]:
    """Replace one diatonic note with a chromatic approach to its successor.

    Picks a random non-rest note that is followed by another non-rest note,
    and alters its pitch to a semitone above or below the successor — whichever
    is NOT already in the diatonic scale.  This guarantees a visible accidental.
    """
    pitch_classes = _key_pitch_classes(key_signature)
    # Collect candidate indices: pitched notes followed by another pitched note
    candidates: list[int] = []
    for i in range(len(events) - 1):
        e = events[i]
        nxt = events[i + 1]
        if (
            not e.get("isRest")
            and not nxt.get("isRest")
            and e.get("pitches")
            and nxt.get("pitches")
            and len(e["pitches"]) == 1  # single-note only
            and len(nxt["pitches"]) == 1
        ):
            candidates.append(i)
    if not candidates:
        return events

    idx = rng.choice(candidates)
    target_pitch = int(events[idx + 1]["pitches"][0])
    cur_pitch = int(events[idx]["pitches"][0])
    # Approach from below or above depending on melodic direction
    if cur_pitch <= target_pitch:
        approach = target_pitch - 1  # semitone below target
    else:
        approach = target_pitch + 1  # semitone above target
    # Only apply if the approach note is truly chromatic (not in key)
    if approach % 12 in pitch_classes:
        # Try the other direction
        if cur_pitch <= target_pitch:
            approach = target_pitch + 1
        else:
            approach = target_pitch - 1
    if approach % 12 in pitch_classes:
        # Both directions are diatonic — skip
        return events
    events[idx]["pitches"] = [approach]
    events[idx]["technique"] = "chromatic approach"
    return events


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
    # --- Grade-aware duration filtering (applied before all content builders) ---
    grade = int(request.get("grade", 3))
    current_measure = phrase_plan.get("_currentMeasure", 1)
    measure_role = phrase_plan.get("_measureRoles", {}).get(current_measure, "develop")
    if hand == "rh":
        if grade <= 2:
            allowed_durations = [d for d in allowed_durations if d >= 1.0] or allowed_durations
        elif grade == 3:
            if measure_role in ("establish", "cadence", "answer"):
                allowed_durations = [d for d in allowed_durations if d >= 1.0] or allowed_durations
            elif measure_role == "develop":
                if rng.random() < 0.65:
                    allowed_durations = [d for d in allowed_durations if d >= 1.0] or allowed_durations
            # intensify keeps full set

    if texture == "chordal":
        events, pp, rec, d = _build_chordal_content(
            hand, pool, harmony_tones, total, pulse, allowed_durations,
            key_signature, harmony, weights, max_leap, rng,
            prev_pitch, recent, direction, is_cadence, cadence_target,
            request=request, preset=preset, phrase_plan=phrase_plan,
        )
    elif texture == "running":
        events, pp, rec, d = _build_running_content(
            hand, pool, harmony_tones, total, pulse, allowed_durations,
            key_signature, harmony, weights, max_leap, rng,
            prev_pitch, recent, direction, is_cadence, cadence_target,
            request=request, preset=preset, phrase_plan=phrase_plan,
        )
    else:
        events, pp, rec, d = _build_melody_content(
            hand, pool, harmony_tones, total, pulse, allowed_durations,
            key_signature, harmony, weights, max_leap, rng,
            prev_pitch, recent, direction, is_cadence, cadence_target,
            request, preset, phrase_plan,
        )

    return events, pp, rec, d

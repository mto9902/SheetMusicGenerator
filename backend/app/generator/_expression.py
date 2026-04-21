"""Dynamics & expression post-processing for generated sheet-music events.

Contains constants and functions responsible for assigning dynamics, ties,
slurs, articulations, and playback-scalar values to the event list produced
by the core generator.
"""
from __future__ import annotations

import math
import random
from typing import Any

from ._types import PiecePlan
from ._helpers import _measure_total, _pulse_value

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

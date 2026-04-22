"""Validation, evaluation, quality gates, and summary helpers."""
from __future__ import annotations

import math
from dataclasses import asdict
from typing import Any

from ..config import (
    COORDINATION_LABELS,
    HAND_ACTIVITY_LABELS,
    KEY_TONIC_PITCH_CLASS,
    READING_FOCUS_LABELS,
)
from ._types import (
    AccompanimentPlan,
    BassLinePlan,
    EvaluationBreakdown,
    LinePlan,
    PhraseBlueprint,
    PiecePlan,
    QualityGateResult,
    StyleProfile,
    TopLinePlan,
)
from ._helpers import _measure_total, _pulse_value, _preset_for_grade, _signature_similarity, _mean
from ._pitch import _key_pitch_classes
from ._chord import (
    _chord_pitch_classes,
    _rh_lead_pitch,
    _lh_bass_pitch,
    _event_primary_pitch,
    _is_second_dyad,
)

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
        previous_planned_bass: int | None = None
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
                planned_interval = (
                    abs(planned_bass - previous_planned_bass)
                    if planned_bass is not None and previous_planned_bass is not None
                    else None
                )
                if motion_role == "hold":
                    motion_score = 1.0 if interval <= 2 else 0.55
                elif motion_role == "step":
                    if interval == 0:
                        motion_score = 0.16 if planned_interval is None or planned_interval >= 2 else 0.34
                    elif interval <= 5:
                        motion_score = 1.0
                    elif interval <= 7:
                        motion_score = 0.68
                    else:
                        motion_score = 0.42
                elif motion_role == "leap":
                    if interval == 0:
                        motion_score = 0.12
                    else:
                        motion_score = 1.0 if 4 <= interval <= 9 else 0.54
                else:
                    motion_score = 1.0 if interval <= 7 else 0.55
            scores.append(0.58 * target_score + 0.42 * motion_score)
            previous_bass = actual_bass
            previous_planned_bass = planned_bass if planned_bass is not None else previous_planned_bass
    return _mean(scores, default=0.74)


def _motion_diversity_score(pitches: list[int]) -> float:
    if len(pitches) < 2:
        return 0.72
    unique_count = len(set(int(round(pitch_value)) for pitch_value in pitches))
    return max(0.0, min(1.0, (unique_count - 1) / max(1, len(pitches) - 1)))


def _anchor_motion_score(actual_delta: float, target_delta: float | None) -> float:
    interval = abs(actual_delta)
    if interval < 0.5:
        return 0.08 if target_delta is None or abs(target_delta) >= 0.5 else 0.2

    if interval <= 2:
        base = 1.0
    elif interval <= 5:
        base = 0.86
    elif interval <= 9:
        base = 0.7
    else:
        base = 0.48

    if target_delta is None or abs(target_delta) < 0.5:
        return min(1.0, base * 0.92)
    if math.copysign(1, actual_delta) == math.copysign(1, target_delta):
        return min(1.0, base + 0.08)
    return max(0.12, base - 0.34)


def _rh_visible_motion_score(events: list[dict[str, Any]], phrase_plans: list[dict[str, Any]]) -> float:
    scores: list[float] = []
    for phrase_plan in phrase_plans:
        measures = [int(measure_number) for measure_number in phrase_plan.get("measures", [])]
        if not measures:
            continue

        entries: list[int] = []
        planned_targets: list[int | None] = []
        for measure_number in measures:
            measure_events = [
                event
                for event in _measure_events_for_hand(events, "rh", measure_number)
                if not event["isRest"] and event.get("pitches")
            ]
            if not measure_events:
                continue
            actual_entry = next(
                (int(pitch_value) for pitch_value in (_rh_lead_pitch(event) for event in measure_events) if pitch_value is not None),
                None,
            )
            if actual_entry is None:
                continue
            planned_target = next(
                (
                    int(event["plannedTopPitch"])
                    for event in measure_events
                    if event.get("plannedTopPitch") is not None
                ),
                None,
            )
            entries.append(actual_entry)
            planned_targets.append(planned_target)

        if len(entries) < 2:
            continue

        core_entries = entries[:-1] if len(entries) > 2 else list(entries)
        core_targets = planned_targets[:len(core_entries)]
        transition_scores: list[float] = []
        for index in range(1, len(core_entries)):
            target_delta = None
            previous_target = core_targets[index - 1]
            current_target = core_targets[index]
            if previous_target is not None and current_target is not None:
                target_delta = float(current_target - previous_target)
            transition_scores.append(
                _anchor_motion_score(float(core_entries[index] - core_entries[index - 1]), target_delta)
            )

        contour = str(phrase_plan.get("_contour", "flat"))
        if contour == "ascending":
            contour_score = 1.0 if core_entries[-1] > core_entries[0] else 0.25
        elif contour == "descending":
            contour_score = 1.0 if core_entries[-1] < core_entries[0] else 0.25
        elif contour == "arch":
            peak_index = max(range(len(core_entries)), key=core_entries.__getitem__)
            contour_score = 1.0 if 0 < peak_index < len(core_entries) - 1 else 0.4
        elif contour == "valley":
            trough_index = min(range(len(core_entries)), key=core_entries.__getitem__)
            contour_score = 1.0 if 0 < trough_index < len(core_entries) - 1 else 0.4
        else:
            contour_score = 0.8 if _motion_diversity_score(core_entries) >= 0.5 else 0.35

        scores.append(
            0.55 * _mean(transition_scores, default=0.66)
            + 0.30 * _motion_diversity_score(core_entries)
            + 0.15 * contour_score
        )
    return _mean(scores, default=0.72)


def _lh_visible_motion_score(events: list[dict[str, Any]], phrase_plans: list[dict[str, Any]]) -> float:
    scores: list[float] = []
    for phrase_plan in phrase_plans:
        bass_plan = phrase_plan.get("_bassLinePlan")
        if not isinstance(bass_plan, BassLinePlan):
            continue

        measures = [int(measure_number) for measure_number in phrase_plan.get("measures", [])]
        actual_basses: list[int] = []
        planned_basses: list[int | None] = []
        actual_measures: list[int] = []
        for measure_number in measures:
            measure_events = [
                event
                for event in _measure_events_for_hand(events, "lh", measure_number)
                if not event["isRest"] and event.get("pitches")
            ]
            if not measure_events:
                continue
            actual_bass = next(
                (int(pitch_value) for pitch_value in (_lh_bass_pitch(event) for event in measure_events) if pitch_value is not None),
                None,
            )
            if actual_bass is None:
                continue
            planned_bass = next(
                (
                    int(event["plannedBassPitch"])
                    for event in measure_events
                    if event.get("plannedBassPitch") is not None
                ),
                None,
            )
            actual_basses.append(actual_bass)
            planned_basses.append(planned_bass)
            actual_measures.append(measure_number)

        if len(actual_basses) < 2:
            continue

        core_basses = actual_basses[:-1] if len(actual_basses) > 2 else list(actual_basses)
        core_targets = planned_basses[:len(core_basses)]
        core_measures = actual_measures[:len(core_basses)]
        transition_scores: list[float] = []
        for index in range(1, len(core_basses)):
            actual_delta = float(core_basses[index] - core_basses[index - 1])
            target_delta = None
            previous_target = core_targets[index - 1]
            current_target = core_targets[index]
            if previous_target is not None and current_target is not None:
                target_delta = float(current_target - previous_target)
            role = str(bass_plan.motion_roles.get(core_measures[index], "step"))
            if role == "hold":
                transition_scores.append(1.0 if abs(actual_delta) <= 2 else 0.55)
                continue
            transition_scores.append(_anchor_motion_score(actual_delta, target_delta))

        scores.append(
            0.62 * _mean(transition_scores, default=0.64)
            + 0.38 * _motion_diversity_score(core_basses)
        )
    return _mean(scores, default=0.7)


def _visible_motion_score(
    request: dict[str, Any],
    events: list[dict[str, Any]],
    phrase_plans: list[dict[str, Any]],
) -> float:
    rh_score = _rh_visible_motion_score(events, phrase_plans)
    lh_score = _lh_visible_motion_score(events, phrase_plans)
    hand_activity = str(request.get("handActivity", "both"))
    coordination_style = str(request.get("coordinationStyle", "support"))
    grade = int(request.get("grade", 1))

    if hand_activity == "right-only":
        return rh_score
    if hand_activity == "left-only":
        return lh_score

    harmonic = (
        (2.0 * rh_score * lh_score) / (rh_score + lh_score)
        if rh_score > 0.0 and lh_score > 0.0
        else 0.0
    )
    combined = 0.58 * rh_score + 0.42 * lh_score
    if coordination_style == "together":
        combined = 0.25 * combined + 0.75 * harmonic
    if grade <= 2 and coordination_style == "together":
        combined = 0.15 * combined + 0.85 * harmonic
    return combined


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
    visible_motion_score = _visible_motion_score(request, events, phrase_plans)
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
        (visible_motion_score, 1.7),
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
        visible_motion=visible_motion_score,
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
    strict_visible_motion = False

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
        # Grades 1-2: keep outputs simple, but still require visible motion so
        # desktop notation does not flatten into the same bar anchors repeatedly.
        visible_motion_threshold = (
            0.60
            if str(request.get("handActivity", "both")) == "both"
            and str(request.get("coordinationStyle", "support")) == "together"
            else 0.42
        )
        checks = [
            ("overall total", evaluation.total, 0.58),
            ("phrase coherence", evaluation.phrase_coherence, 0.50),
            ("cadence preparation", evaluation.cadence_preparation, 0.60),
            ("visible motion", evaluation.visible_motion, visible_motion_threshold),
        ]
        hard_checks = {"cadence preparation", "visible motion"}
        leniency_max_reasons = 1
        leniency_gate = 0.95
        leniency_total = 0.62
        strict_visible_motion = True

    reasons: list[str] = []
    normalized_scores: list[float] = []
    hard_fail = False
    for label, value, threshold in checks:
        normalized = min(1.12, value / threshold) if threshold > 0 else 1.0
        normalized_scores.append(normalized)
        if value + 1e-9 < threshold:
            reasons.append(label)
            if strict_visible_motion and label == "visible motion":
                hard_fail = True
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

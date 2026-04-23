"""Chord helpers and weighted pitch/duration selection."""
from __future__ import annotations

import math
import random
from typing import Any

from ..config import (
    HAND_POSITION_ROOTS,
    HARMONY_INTERVALS,
    KEY_TONIC_PITCH_CLASS,
)
from ._helpers import _measure_total, _pulse_value
from ._pitch import _key_pitch_classes, _position_pitches_from_root

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
        # These user-visible knobs need to *actually* shape output, not just
        # nudge it — previously a ±0.14 step-weight delta was indistinguishable
        # from noise.  Clamp each mode into a distinct band instead.
        if motion == "stepwise":
            # Heavy stepwise: rarely leap, stay compact.
            base["stepWeight"] = 0.95
            base["rangeSigma"] = max(1.8, base["rangeSigma"] - 0.9)
            base["allowIntervals"] = ["2nd", "3rd"]
        elif motion == "small-leaps":
            # Explicitly encourage leaps: aggressively suppress steps so 3rds
            # and 4ths dominate; boost chord-tone gravity so leap choices land
            # on consonant arrivals.
            base["stepWeight"] = 0.25
            base["rangeSigma"] = min(10.0, base["rangeSigma"] + 0.7)
            base["chordToneWeight"] = base["chordToneWeight"] * 1.35
            existing = list(base.get("allowIntervals", []))
            for interval in ("3rd", "4th", "5th"):
                if interval not in existing:
                    existing.append(interval)
            base["allowIntervals"] = existing
        elif motion == "mixed":
            base["stepWeight"] = 0.70
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
    from ._planning import _LEFT_PATTERN_FAMILY_PREFERENCES
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

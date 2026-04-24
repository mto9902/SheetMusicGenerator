"""Main event builder: constructs piano and rhythm exercise candidates."""
from __future__ import annotations

import random
from typing import Any

from ..config import HAND_POSITION_ROOTS, KEY_TONIC_PITCH_CLASS, request_grade_stage, request_max_leap
from ._helpers import _preset_for_grade, _measure_total, _pulse_value, _fit_measure
from ._pitch import _position_pitches_from_root, _shift_root
from ._harmony import _harmonic_plan, _phrase_form_template
from ._chord import (
    _chord_tones_in_pool,
    _weights_for_hand,
    _lh_bass_pitch,
    _preferred_left_families,
    _apply_right_hand_seconds,
    _apply_right_hand_harmonic_punctuations,
)
from ._rhythm import _pick_rhythm_cells, _pick_texture, _pick_contour
from ._texture import (
    _build_measure_content,
    _replay_rhythm_template,
    _apply_piece_ending,
    _apply_penultimate_ending,
    _apply_lh_piece_ending,
    _apply_lh_variation_pass,
)
from ._planning import (
    _build_style_profile,
    _group_into_phrases,
    _assign_phrase_grammars,
    _build_piece_plan,
    _pick_phrase_plan,
    _resolve_top_line_target,
    _resolve_bass_line_target,
)
from ._left_hand import _build_left_pattern
from ._expression import (
    _apply_ties,
    _assign_expression_ids,
    _apply_dynamics,
    _apply_slurs,
    _apply_articulations,
    _apply_playback_expression,
)


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
# Main event builder (REWRITTEN)
# ---------------------------------------------------------------------------

def _build_piano_candidate(request: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    grade = int(request["grade"])
    preset = _preset_for_grade(grade)
    piano = preset["piano"]
    style_profile = _build_style_profile(request, preset)
    grade_stage = request_grade_stage(request)
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
    max_leap = request_max_leap(request, max_leap)
    # Harden RH motion selector: clamp max_leap so "stepwise" can't leap and
    # "small-leaps" gets more room than the base preset.  Weights alone don't
    # penetrate when top-line targets pre-determine bar boundaries, so this
    # interval cap is what actually changes the feel of the output.
    _rh_motion = str(request.get("rightHandMotion", "mixed"))
    if _rh_motion == "stepwise":
        max_leap = min(max_leap, 2)
    elif _rh_motion == "small-leaps":
        max_leap = max(max_leap, 7)

    right_root = HAND_POSITION_ROOTS["rh"][request["handPosition"]]
    left_root = HAND_POSITION_ROOTS["lh"][request["handPosition"]]

    rh_pool = _position_pitches_from_root(
        right_root,
        request["keySignature"],
        pool_size,
        hand="rh",
        grade=grade,
        grade_stage=str(request.get("gradeStage")) if request.get("gradeStage") else None,
    )
    lh_pool_size = max(8, pool_size)
    lh_pool = _position_pitches_from_root(
        left_root,
        request["keySignature"],
        lh_pool_size,
        hand="lh",
        grade=grade,
        grade_stage=str(request.get("gradeStage")) if request.get("gradeStage") else None,
    )

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
    preferred_lh = set(_preferred_left_families(request, available_lh))
    # Honor the user's leftHandPattern selection: if preferred families
    # intersect with what this grade allows, restrict available_lh to those
    # preferred families so the user-facing choice actually changes output.
    if (
        preferred_lh
        and set(available_lh) & preferred_lh
        and not (
            grade == 1
            and str(request.get("mode", "piano")) == "piano"
            and grade_stage is not None
        )
    ):
        available_lh = [family for family in available_lh if family in preferred_lh]
    coordination_style = str(request.get("coordinationStyle", "support"))
    hand_activity = str(request.get("handActivity", "both"))
    reading_focus = str(request.get("readingFocus", "balanced"))
    requested_pattern = str(request.get("leftHandPattern", "held"))

    lh_weights: list[float] = []
    for family in available_lh:
        weight = _LH_FAMILY_WEIGHT.get(family, 0.5)
        if family in preferred_lh:
            preferred_boost = 1.35 if grade == 1 and grade_stage is not None else 2.35
            weight *= preferred_boost
        if grade == 1 and grade_stage in {"g1-extend", "g1-staff"}:
            if family == "held":
                weight *= 0.48
            elif family in {"repeated", "support-bass"}:
                weight *= 1.55
        elif grade == 1 and grade_stage == "g1-pocket":
            if family == "repeated":
                weight *= 1.15
        if grade <= 2 and hand_activity == "both":
            if coordination_style == "together":
                if family in {"block-half", "bass-and-chord", "block-quarter"}:
                    weight *= 1.6
                elif family == "held":
                    weight *= 0.48
            elif coordination_style == "support" and family in {"block-half", "bass-and-chord", "support-bass"}:
                weight *= 1.2
        if reading_focus == "harmonic" and family in {"block-half", "bass-and-chord", "block-quarter"}:
            weight *= 1.15
        if reading_focus == "melodic" and family in {"support-bass", "simple-broken", "arpeggio-support"}:
            weight *= 1.15
        if requested_pattern == "held" and family in {"block-half", "bass-and-chord"}:
            weight *= 1.2
        lh_weights.append(max(weight, 0.05))
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
                rh_pool = _position_pitches_from_root(
                    right_root,
                    request["keySignature"],
                    pool_size,
                    hand="rh",
                    grade=grade,
                    grade_stage=str(request.get("gradeStage")) if request.get("gradeStage") else None,
                )
                lh_pool = _position_pitches_from_root(
                    left_root,
                    request["keySignature"],
                    lh_pool_size,
                    hand="lh",
                    grade=grade,
                    grade_stage=str(request.get("gradeStage")) if request.get("gradeStage") else None,
                )
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
                # --- RH piece ending: shape last 2 measures ---
                is_piece_final_rh = measure_number == int(request["measureCount"])
                is_penultimate_rh = measure_number == int(request["measureCount"]) - 1
                if is_penultimate_rh and rh_events:
                    _apply_penultimate_ending(
                        rh_events, rh_pool,
                        request["keySignature"], rh_pitch, total,
                    )
                    for updated_event in reversed(rh_events):
                        if not updated_event.get("isRest") and updated_event.get("pitches"):
                            rh_pitch = int(updated_event["pitches"][-1])
                            break
                if is_piece_final_rh and rh_events:
                    _apply_piece_ending(
                        rh_events, rh_pool,
                        request["keySignature"], rh_pitch, total,
                        time_signature=str(request.get("timeSignature", "4/4")),
                        grade=grade,
                        rng=rng,
                    )
                    for updated_event in reversed(rh_events):
                        if not updated_event.get("isRest") and updated_event.get("pitches"):
                            rh_pitch = int(updated_event["pitches"][-1])
                            break

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
                # Final measure: pick from LH cadence templates so the ending
                # doesn't always collapse to a held tonic.
                is_piece_final = measure_number == int(request["measureCount"])
                if is_piece_final:
                    lh_events = _apply_lh_piece_ending(
                        lh_pool,
                        request["keySignature"],
                        lh_pitch,
                        total,
                        str(request.get("timeSignature", "4/4")),
                        grade,
                        rng,
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

    # Break up runs of identical LH rhythmic shapes so the accompaniment
    # doesn't lock into the same pattern for the whole piece.
    events = _apply_lh_variation_pass(
        events,
        total,
        int(request["measureCount"]),
        rng,
    )

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

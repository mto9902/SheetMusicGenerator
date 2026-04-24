from __future__ import annotations

import random
import unittest
from collections import Counter
from typing import Any

from backend.app.config import HAND_POSITION_ROOTS
from backend.app.generator._builder import _build_piano_candidate
from backend.app.generator._chord import _lh_bass_pitch, _rh_lead_pitch
from backend.app.generator._helpers import _preset_for_grade
from backend.app.generator._pitch import _position_stage_zones
from backend.app.generator._planning import _build_style_profile
from backend.app.generator._scoring import (
    _evaluate_candidate,
    _quality_gate_result,
    _validate_events,
)
from backend.app.generator._variation import _pick_variation_profile


BASE_REQUEST: dict[str, Any] = {
    "mode": "piano",
    "grade": 1,
    "timeSignature": "4/4",
    "measureCount": 4,
    "tempoPreset": "medium",
    "handPosition": "C",
    "handActivity": "both",
    "coordinationStyle": "together",
    "readingFocus": "balanced",
    "rightHandMotion": "mixed",
    "leftHandPattern": "held",
    "allowRests": False,
    "allowAccidentals": False,
    "seed": "",
}


def _select_candidate(request: dict[str, Any]) -> dict[str, Any] | None:
    preset = _preset_for_grade(int(request["grade"]))
    style_profile = _build_style_profile(request, preset)
    best_candidate: dict[str, Any] | None = None
    best_score = -1.0
    best_passing_candidate: dict[str, Any] | None = None
    best_passing_score = -1.0

    for attempt in range(style_profile.search_attempts):
        rng = random.Random(f"{request['seed']}-{attempt}")
        candidate = _build_piano_candidate(request, rng)
        if not _validate_events(request, candidate["events"]):
            continue

        evaluation = _evaluate_candidate(request, candidate)
        gate_result = _quality_gate_result(request, candidate, evaluation)
        candidate["evaluationBreakdown"] = evaluation
        candidate["qualityGate"] = gate_result

        fallback_score = evaluation.total + max(0.0, gate_result.score - 0.9) * 0.08
        if fallback_score > best_score:
            best_candidate = candidate
            best_score = fallback_score

        if gate_result.passed:
            passing_score = evaluation.total + 0.05 + max(0.0, gate_result.score - 0.95) * 0.08
            if passing_score > best_passing_score:
                best_passing_candidate = candidate
                best_passing_score = passing_score

    return best_passing_candidate or best_candidate


def _note_pitches(events: list[dict[str, Any]], hand: str) -> list[int]:
    pitches: list[int] = []
    for event in events:
        if event["hand"] != hand or event["isRest"]:
            continue
        pitches.extend(int(pitch_value) for pitch_value in event.get("pitches", []))
    return pitches


def _primary_pitches(events: list[dict[str, Any]], hand: str) -> list[int]:
    pitches: list[int] = []
    for event in events:
        if event["hand"] != hand or event["isRest"] or not event.get("pitches"):
            continue
        pitch_value = _rh_lead_pitch(event) if hand == "rh" else _lh_bass_pitch(event)
        if pitch_value is not None:
            pitches.append(int(pitch_value))
    return pitches


def _first_primary_pitch(events: list[dict[str, Any]], hand: str) -> int | None:
    pitches = _primary_pitches(events, hand)
    return pitches[0] if pitches else None


def _max_primary_leap(events: list[dict[str, Any]], hand: str) -> int:
    pitches = _primary_pitches(events, hand)
    if len(pitches) < 2:
        return 0
    return max(abs(right - left) for left, right in zip(pitches, pitches[1:], strict=False))


def _rhythm_signature(events: list[dict[str, Any]], hand: str) -> tuple[tuple[float, ...], ...]:
    by_measure: dict[int, list[float]] = {}
    for event in events:
        if event["hand"] != hand or event["isRest"]:
            continue
        by_measure.setdefault(int(event["measure"]), []).append(round(float(event["quarterLength"]), 3))
    return tuple(tuple(values) for _, values in sorted(by_measure.items()))


def _contour_signature(candidate: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(phrase_plan.get("_contour", "flat")) for phrase_plan in candidate.get("phrasePlans", []))


def _left_family_signature(candidate: dict[str, Any]) -> tuple[str, ...]:
    families: list[str] = []
    for phrase_plan in candidate.get("phrasePlans", []):
        family_by_measure = dict(phrase_plan.get("_leftFamilyByMeasure") or {})
        for measure_number in sorted(family_by_measure):
            families.append(str(family_by_measure[measure_number]))
    return tuple(families)


def _has_extension_by_measure(
    events: list[dict[str, Any]],
    hand: str,
    extension_pitches: list[int],
    max_measure: int,
) -> bool:
    extension_set = set(int(pitch_value) for pitch_value in extension_pitches)
    if not extension_set:
        return False
    for event in events:
        if event["hand"] != hand or event["isRest"] or int(event["measure"]) > max_measure:
            continue
        if any(int(pitch_value) in extension_set for pitch_value in event.get("pitches", [])):
            return True
    return False


def _analyze_stage_batch(
    key_signature: str,
    grade_stage: str,
    seed_prefix: str,
    sample_count: int = 40,
) -> dict[str, Any]:
    request_template = {
        **BASE_REQUEST,
        "keySignature": key_signature,
        "gradeStage": grade_stage,
    }
    zones = {
        "rh": _position_stage_zones(
            HAND_POSITION_ROOTS["rh"][request_template["handPosition"]],
            key_signature,
            hand="rh",
            grade=1,
            grade_stage=grade_stage,
        ),
        "lh": _position_stage_zones(
            HAND_POSITION_ROOTS["lh"][request_template["handPosition"]],
            key_signature,
            hand="lh",
            grade=1,
            grade_stage=grade_stage,
        ),
    }

    rh_window = set(int(pitch_value) for pitch_value in zones["rh"]["window"])
    lh_window = set(int(pitch_value) for pitch_value in zones["lh"]["window"])
    rh_pocket = set(int(pitch_value) for pitch_value in zones["rh"]["pocket"])
    lh_pocket = set(int(pitch_value) for pitch_value in zones["lh"]["pocket"])
    rh_upper = set(int(pitch_value) for pitch_value in zones["rh"]["upper_extension"])
    lh_lower = set(int(pitch_value) for pitch_value in zones["lh"]["lower_extension"])

    opening_pitch_counter: Counter[int] = Counter()
    rh_union: set[int] = set()
    lh_union: set[int] = set()
    rh_upper_count = 0
    lh_lower_count = 0
    rh_above_c5_count = 0
    lh_below_c3_count = 0
    outside_window_count = 0
    outside_pocket_count = 0
    early_extension_count = 0
    opening_outside_count = 0
    max_rh_leap = 0
    failures: list[str] = []

    for idx in range(sample_count):
        request = {**request_template, "seed": f"{seed_prefix}{idx}"}
        candidate = _select_candidate(request)
        if candidate is None:
            failures.append(request["seed"])
            continue

        events = candidate["events"]
        rh_note_pitches = _note_pitches(events, "rh")
        lh_note_pitches = _note_pitches(events, "lh")
        rh_union.update(rh_note_pitches)
        lh_union.update(lh_note_pitches)

        if any(pitch_value not in rh_window for pitch_value in rh_note_pitches) or any(
            pitch_value not in lh_window for pitch_value in lh_note_pitches
        ):
            outside_window_count += 1

        if any(pitch_value not in rh_pocket for pitch_value in rh_note_pitches) or any(
            pitch_value not in lh_pocket for pitch_value in lh_note_pitches
        ):
            outside_pocket_count += 1

        if any(pitch_value in rh_upper for pitch_value in rh_note_pitches):
            rh_upper_count += 1
        if any(pitch_value in lh_lower for pitch_value in lh_note_pitches):
            lh_lower_count += 1
        if any(pitch_value > 72 for pitch_value in rh_note_pitches):
            rh_above_c5_count += 1
        if any(pitch_value < 48 for pitch_value in lh_note_pitches):
            lh_below_c3_count += 1

        if _has_extension_by_measure(events, "rh", list(rh_upper), 2) or _has_extension_by_measure(
            events,
            "lh",
            list(lh_lower),
            2,
        ):
            early_extension_count += 1

        opening_pitch = _first_primary_pitch(events, "rh")
        if opening_pitch is None:
            failures.append(request["seed"])
            continue
        opening_pitch_counter[opening_pitch] += 1

        first_rh_pitch = opening_pitch
        first_lh_pitch = _first_primary_pitch(events, "lh")
        if (
            (first_rh_pitch is not None and first_rh_pitch not in rh_pocket)
            or (first_lh_pitch is not None and first_lh_pitch not in lh_pocket)
        ):
            opening_outside_count += 1

        max_rh_leap = max(max_rh_leap, _max_primary_leap(events, "rh"))

    return {
        "sample_count": sample_count,
        "failures": failures,
        "opening_pitch_counter": opening_pitch_counter,
        "unique_openings": len(opening_pitch_counter),
        "rh_union_count": len(rh_union),
        "lh_union_count": len(lh_union),
        "rh_upper_count": rh_upper_count,
        "lh_lower_count": lh_lower_count,
        "rh_above_c5_count": rh_above_c5_count,
        "lh_below_c3_count": lh_below_c3_count,
        "outside_window_count": outside_window_count,
        "outside_pocket_count": outside_pocket_count,
        "early_extension_count": early_extension_count,
        "opening_outside_count": opening_outside_count,
        "max_rh_leap": max_rh_leap,
    }


class GeneratorRegressionTests(unittest.TestCase):
    def test_grade1_stage_pockets_cover_named_five_finger_positions(self) -> None:
        for hand_position in ("C", "G", "D", "F", "Bb"):
            with self.subTest(hand_position=hand_position):
                rh_zones = _position_stage_zones(
                    HAND_POSITION_ROOTS["rh"][hand_position],
                    "C",
                    hand="rh",
                    grade=1,
                    grade_stage="g1-pocket",
                )
                lh_zones = _position_stage_zones(
                    HAND_POSITION_ROOTS["lh"][hand_position],
                    "C",
                    hand="lh",
                    grade=1,
                    grade_stage="g1-pocket",
                )
                self.assertGreaterEqual(
                    len(rh_zones["pocket"]),
                    5,
                    msg=f"RH pocket was truncated in {hand_position} position: {rh_zones}",
                )
                self.assertGreaterEqual(
                    len(lh_zones["pocket"]),
                    5,
                    msg=f"LH pocket was truncated in {hand_position} position: {lh_zones}",
                )
        self.assertIn(74, _position_stage_zones(
            HAND_POSITION_ROOTS["rh"]["G"],
            "C",
            hand="rh",
            grade=1,
            grade_stage="g1-pocket",
        )["pocket"])
        self.assertIn(57, _position_stage_zones(
            HAND_POSITION_ROOTS["lh"]["D"],
            "C",
            hand="lh",
            grade=1,
            grade_stage="g1-pocket",
        )["pocket"])

    def test_grade1_stage_pocket_batch_rules(self) -> None:
        for key_signature in ("C", "F", "G"):
            with self.subTest(key_signature=key_signature):
                summary = _analyze_stage_batch(key_signature, "g1-pocket", f"{key_signature.lower()}pocket")
                self.assertEqual([], summary["failures"], msg=f"Unexpected failures: {summary}")
                self.assertEqual(0, summary["outside_window_count"], msg=f"Pocket stage left the allowed window: {summary}")
                self.assertEqual(0, summary["outside_pocket_count"], msg=f"Pocket stage escaped the exact five-note pocket: {summary}")
                self.assertGreaterEqual(
                    summary["unique_openings"],
                    4,
                    msg=f"Pocket stage opening variety was too low: {summary}",
                )
                self.assertLessEqual(
                    summary["max_rh_leap"],
                    2,
                    msg=f"Pocket stage RH leaps were too wide: {summary}",
                )

    def test_grade1_stage_extend_batch_rules(self) -> None:
        for key_signature in ("C", "F", "G"):
            with self.subTest(key_signature=key_signature):
                summary = _analyze_stage_batch(key_signature, "g1-extend", f"{key_signature.lower()}extend")
                self.assertEqual([], summary["failures"], msg=f"Unexpected failures: {summary}")
                self.assertEqual(0, summary["outside_window_count"], msg=f"Extend stage exceeded the stage window: {summary}")
                self.assertGreaterEqual(
                    summary["rh_upper_count"],
                    16,
                    msg=f"Extend stage did not reach above the RH pocket often enough: {summary}",
                )
                self.assertGreaterEqual(
                    summary["lh_lower_count"],
                    16,
                    msg=f"Extend stage did not reach below the LH pocket often enough: {summary}",
                )
                self.assertGreaterEqual(
                    summary["rh_union_count"],
                    7,
                    msg=f"Extend stage RH coverage was too narrow: {summary}",
                )
                self.assertGreaterEqual(
                    summary["lh_union_count"],
                    7,
                    msg=f"Extend stage LH coverage was too narrow: {summary}",
                )
                self.assertGreaterEqual(
                    summary["early_extension_count"],
                    16,
                    msg=f"Extend stage was not touching extension notes early often enough: {summary}",
                )
                self.assertLessEqual(
                    summary["max_rh_leap"],
                    4,
                    msg=f"Extend stage RH leaps were too wide: {summary}",
                )

    def test_grade1_stage_staff_batch_rules(self) -> None:
        for key_signature in ("C", "F", "G"):
            with self.subTest(key_signature=key_signature):
                summary = _analyze_stage_batch(key_signature, "g1-staff", f"{key_signature.lower()}staff")
                self.assertEqual([], summary["failures"], msg=f"Unexpected failures: {summary}")
                self.assertEqual(0, summary["outside_window_count"], msg=f"Staff stage exceeded the stage window: {summary}")
                self.assertGreaterEqual(
                    summary["rh_upper_count"],
                    28,
                    msg=f"Staff stage did not reach above the RH pocket often enough: {summary}",
                )
                self.assertGreaterEqual(
                    summary["lh_lower_count"],
                    28,
                    msg=f"Staff stage did not reach below the LH pocket often enough: {summary}",
                )
                self.assertGreaterEqual(
                    summary["rh_union_count"],
                    9,
                    msg=f"Staff stage RH coverage was too narrow: {summary}",
                )
                self.assertGreaterEqual(
                    summary["lh_union_count"],
                    9,
                    msg=f"Staff stage LH coverage was too narrow: {summary}",
                )
                self.assertGreaterEqual(
                    summary["opening_outside_count"],
                    12,
                    msg=f"Staff stage did not open outside the pocket often enough: {summary}",
                )
                self.assertGreaterEqual(
                    summary["rh_above_c5_count"],
                    12,
                    msg=f"Staff stage did not practice RH notes above treble C often enough: {summary}",
                )
                self.assertGreaterEqual(
                    summary["lh_below_c3_count"],
                    28,
                    msg=f"Staff stage did not practice LH notes below middle-bass C often enough: {summary}",
                )
                self.assertLessEqual(
                    summary["max_rh_leap"],
                    4,
                    msg=f"Staff stage RH leaps were too wide: {summary}",
                )

    def test_final_bar_rhythm_varies_across_seeds(self) -> None:
        rhythm_signatures: Counter[tuple] = Counter()
        sample_count = 30
        for idx in range(sample_count):
            request = {**BASE_REQUEST, "gradeStage": "g1-extend", "keySignature": "C", "seed": f"finalvar{idx}"}
            candidate = _select_candidate(request)
            self.assertIsNotNone(candidate, msg=f"Generation failed for seed {request['seed']}")
            events = candidate["events"]  # type: ignore[index]
            last_measure = int(request["measureCount"])
            final_events = [
                event
                for event in events
                if event["hand"] == "rh"
                and int(event["measure"]) == last_measure
                and not event["isRest"]
                and event.get("pitches")
            ]
            if not final_events:
                continue
            signature = tuple(round(float(event["quarterLength"]), 3) for event in final_events)
            rhythm_signatures[signature] += 1

        self.assertGreaterEqual(
            len(rhythm_signatures),
            3,
            msg=f"Final-bar rhythm was not varied enough: {rhythm_signatures}",
        )
        dominant_share = max(rhythm_signatures.values()) / sample_count
        self.assertLess(
            dominant_share,
            0.75,
            msg=f"One final-bar rhythm dominated: {rhythm_signatures}",
        )

    def test_lh_pattern_does_not_repeat_too_many_bars(self) -> None:
        request = {
            **BASE_REQUEST,
            "gradeStage": "g1-extend",
            "keySignature": "C",
            "measureCount": 8,
            "leftHandPattern": "support-bass",
            "seed": "lhvary",
        }
        candidate = _select_candidate(request)
        self.assertIsNotNone(candidate)
        events = candidate["events"]  # type: ignore[index]
        lh_by_measure: dict[int, list[dict[str, Any]]] = {}
        for event in events:
            if event["hand"] != "lh":
                continue
            lh_by_measure.setdefault(int(event["measure"]), []).append(event)

        def signature(measure_events: list[dict[str, Any]]) -> tuple:
            return tuple(
                (round(float(event["quarterLength"]), 3), len(event.get("pitches", [])))
                for event in measure_events
            )

        signatures = [signature(lh_by_measure[measure_number]) for measure_number in sorted(lh_by_measure)]
        non_final = signatures[:-1]
        longest_run = 1
        current_run = 1
        for prev, curr in zip(non_final, non_final[1:], strict=False):
            if prev == curr:
                current_run += 1
                longest_run = max(longest_run, current_run)
            else:
                current_run = 1
        self.assertLess(
            longest_run,
            5,
            msg=f"LH rhythm signature repeated {longest_run} bars without variation: {signatures}",
        )

    def test_variation_profile_picker_covers_each_grade_band(self) -> None:
        expected_minimums = {1: 4, 2: 5, 3: 6, 4: 7, 5: 7}
        for grade, expected_minimum in expected_minimums.items():
            with self.subTest(grade=grade):
                names: Counter[str] = Counter()
                for idx in range(90):
                    request = {
                        **BASE_REQUEST,
                        "grade": grade,
                        "keySignature": "C",
                        "gradeStage": "g1-staff" if grade == 1 else None,
                        "seed": f"profile{grade}-{idx}",
                    }
                    profile = _pick_variation_profile(request, random.Random(request["seed"]))
                    names[profile.name] += 1

                self.assertGreaterEqual(
                    len(names),
                    expected_minimum,
                    msg=f"Grade {grade} variation profile coverage collapsed: {names}",
                )

    def test_selected_candidates_keep_distinct_vibe_signatures(self) -> None:
        for grade in (1, 3, 5):
            with self.subTest(grade=grade):
                profile_names: Counter[str] = Counter()
                rhythm_signatures: Counter[tuple] = Counter()
                vibe_signatures: Counter[tuple] = Counter()
                sample_count = 18
                for idx in range(sample_count):
                    request = {
                        **BASE_REQUEST,
                        "grade": grade,
                        "gradeStage": "g1-staff" if grade == 1 else None,
                        "keySignature": "C",
                        "measureCount": 8,
                        "seed": f"vibe{grade}-{idx}",
                    }
                    candidate = _select_candidate(request)
                    self.assertIsNotNone(candidate, msg=f"Generation failed for seed {request['seed']}")
                    candidate = candidate or {}
                    events = candidate["events"]
                    profile_name = str(candidate.get("variationProfile", {}).get("name", "unknown"))
                    profile_names[profile_name] += 1
                    rh_rhythm = _rhythm_signature(events, "rh")
                    rhythm_signatures[rh_rhythm] += 1
                    vibe_signatures[(
                        profile_name,
                        rh_rhythm,
                        _contour_signature(candidate),
                        _left_family_signature(candidate),
                    )] += 1

                self.assertGreaterEqual(
                    len(profile_names),
                    3,
                    msg=f"Selected Grade {grade} candidates over-used one profile: {profile_names}",
                )
                self.assertGreaterEqual(
                    len(rhythm_signatures),
                    5,
                    msg=f"Selected Grade {grade} RH rhythm shapes were too similar: {rhythm_signatures}",
                )
                self.assertGreaterEqual(
                    len(vibe_signatures),
                    9,
                    msg=f"Selected Grade {grade} vibe signatures were too similar: {vibe_signatures}",
                )

from __future__ import annotations

import random
import unittest
from collections import Counter
from typing import Any

from backend.app.generator._builder import _build_piano_candidate
from backend.app.generator._helpers import _preset_for_grade
from backend.app.generator._planning import _build_style_profile
from backend.app.generator._scoring import (
    _evaluate_candidate,
    _quality_gate_result,
    _validate_events,
)


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


def _analyze_batch(key_signature: str, seed_prefix: str, sample_count: int) -> dict[str, Any]:
    request_template = {**BASE_REQUEST, "keySignature": key_signature}
    opening_pitch_counter: Counter[int] = Counter()
    high_treble_exercises = 0
    high_opening_exercises = 0
    low_bass_exercises = 0
    failures: list[str] = []

    for idx in range(sample_count):
        request = {**request_template, "seed": f"{seed_prefix}{idx}"}
        candidate = _select_candidate(request)
        if candidate is None:
            failures.append(request["seed"])
            continue

        events = candidate["events"]
        rh_events = [
            event
            for event in events
            if event["hand"] == "rh" and not event["isRest"] and event.get("pitches")
        ]
        lh_events = [
            event
            for event in events
            if event["hand"] == "lh" and not event["isRest"] and event.get("pitches")
        ]

        rh_pitches = [max(int(pitch_value) for pitch_value in event["pitches"]) for event in rh_events]
        lh_pitches = [min(int(pitch_value) for pitch_value in event["pitches"]) for event in lh_events]

        if any(pitch_value > 67 for pitch_value in rh_pitches):
            high_treble_exercises += 1
        if any(pitch_value < 48 for pitch_value in lh_pitches):
            low_bass_exercises += 1

        first_measure_events = [
            event
            for event in rh_events
            if int(event["measure"]) == 1
        ]
        if not first_measure_events:
            failures.append(request["seed"])
            continue

        opening_pitch = max(int(pitch_value) for pitch_value in first_measure_events[0]["pitches"])
        opening_pitch_counter[opening_pitch] += 1
        if opening_pitch > 67:
            high_opening_exercises += 1

    max_opening_share = (
        max(opening_pitch_counter.values(), default=0) / sample_count if sample_count else 0.0
    )
    return {
        "sample_count": sample_count,
        "opening_pitch_counter": opening_pitch_counter,
        "unique_openings": len(opening_pitch_counter),
        "max_opening_share": max_opening_share,
        "high_treble_exercises": high_treble_exercises,
        "high_opening_exercises": high_opening_exercises,
        "low_bass_exercises": low_bass_exercises,
        "failures": failures,
    }


class GeneratorRegressionTests(unittest.TestCase):
    def test_grade1_c_major_openings_do_not_collapse_to_one_note(self) -> None:
        summary = _analyze_batch("C", "cgate", 40)

        self.assertEqual([], summary["failures"], msg=f"Unexpected failures: {summary['failures']}")
        self.assertGreaterEqual(
            summary["unique_openings"],
            5,
            msg=f"Opening notes were not varied enough: {summary['opening_pitch_counter']}",
        )
        self.assertLessEqual(
            summary["max_opening_share"],
            0.35,
            msg=f"One opening pitch dominated too much: {summary['opening_pitch_counter']}",
        )
        self.assertGreaterEqual(
            summary["high_treble_exercises"],
            10,
            msg=f"Treble range stayed too central: {summary}",
        )
        self.assertGreaterEqual(
            summary["high_opening_exercises"],
            6,
            msg=f"Openings never reached above G often enough: {summary}",
        )
        self.assertEqual(
            summary["sample_count"],
            summary["low_bass_exercises"],
            msg=f"Bass did not dip below C often enough: {summary}",
        )

    def test_final_bar_rhythm_varies_across_seeds(self) -> None:
        """Final-bar rhythm signatures should be varied — not always a whole
        note.  Regression guard against collapsing back to the hard-override
        ending that made every piece feel identical."""
        rhythm_signatures: Counter[tuple] = Counter()
        sample_count = 30
        for idx in range(sample_count):
            request = {**BASE_REQUEST, "keySignature": "C", "seed": f"finalvar{idx}"}
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
        # No single rhythm should dominate more than ~75% of outputs.
        dominant_share = max(rhythm_signatures.values()) / sample_count
        self.assertLess(
            dominant_share,
            0.75,
            msg=f"One final-bar rhythm dominated: {rhythm_signatures}",
        )

    def test_lh_pattern_does_not_repeat_too_many_bars(self) -> None:
        """LH rhythmic shape should break up at least every ~4 bars instead
        of sitting on the same pattern for the whole piece."""
        request = {**BASE_REQUEST, "keySignature": "C", "measureCount": 8, "seed": "lhvary"}
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

        signatures = [signature(lh_by_measure[m]) for m in sorted(lh_by_measure)]
        # Excluding the final bar, the longest run of identical signatures
        # should be < 5 (so the LH doesn't lock into one texture).
        non_final = signatures[:-1]
        longest_run = 1
        current_run = 1
        for prev, curr in zip(non_final, non_final[1:]):
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

    def test_grade1_f_major_openings_keep_variety_and_range(self) -> None:
        summary = _analyze_batch("F", "fgate", 20)

        self.assertEqual([], summary["failures"], msg=f"Unexpected failures: {summary['failures']}")
        self.assertGreaterEqual(
            summary["unique_openings"],
            4,
            msg=f"F-major openings were too repetitive: {summary['opening_pitch_counter']}",
        )
        self.assertLessEqual(
            summary["max_opening_share"],
            0.45,
            msg=f"One F-major opening pitch dominated too much: {summary['opening_pitch_counter']}",
        )
        self.assertGreaterEqual(
            summary["high_treble_exercises"],
            8,
            msg=f"F-major treble range stayed too central: {summary}",
        )
        self.assertGreaterEqual(
            summary["high_opening_exercises"],
            4,
            msg=f"F-major openings never reached above G often enough: {summary}",
        )
        self.assertEqual(
            summary["sample_count"],
            summary["low_bass_exercises"],
            msg=f"F-major bass did not dip below C often enough: {summary}",
        )


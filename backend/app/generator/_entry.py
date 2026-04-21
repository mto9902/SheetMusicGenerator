"""Public entry point for the sheet-music exercise generator."""
from __future__ import annotations

import random
from dataclasses import asdict
from typing import Any

from ..config import (
    COORDINATION_LABELS,
    GRADE_LABELS,
    HAND_ACTIVITY_LABELS,
    POSITION_LABELS,
    TEMPO_BY_PRESET,
    is_minor_key,
)
from ..audio import render_audio_data_uri
from ._types import QualityGateResult
from ._helpers import _preset_for_grade
from ._planning import _build_style_profile
from ._texture import _inject_chromatic_approaches_post
from ._builder import _build_piano_candidate, _build_rhythm_events
from ._engraving import _create_musicxml, _render_svg
from ._scoring import (
    _validate_events,
    _evaluate_candidate,
    _quality_gate_result,
    _phrase_shape_label,
    _cadence_label,
    _harmony_focus,
    _technique_focus,
    _reading_focus,
    _debug_plan_summary,
)


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

        # --- Post-candidate: inject chromatic approach notes ---
        if request.get("allowAccidentals") and int(request["grade"]) >= 4:
            events = _inject_chromatic_approaches_post(
                events, request, random.Random(f"{request['seed']}-acc")
            )

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

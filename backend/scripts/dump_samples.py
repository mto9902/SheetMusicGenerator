"""Dump readable samples of generator output across grades/seeds for audit."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from backend.app.generator._entry import build_exercise  # noqa: E402


PITCH_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def midi_to_name(m: int) -> str:
    return f"{PITCH_NAMES[m % 12]}{m // 12 - 1}"


def format_candidate(resp: dict) -> str:
    lines: list[str] = []
    lines.append(f"=== seed={resp['seed']} grade={resp['grade']} key={resp['config']['keySignature']} ts={resp['timeSignature']} bars={resp['measureCount']} ===")
    summary = resp.get("summary", {})
    lines.append(
        f"phrase={summary.get('phraseShapeLabel')} cadence={summary.get('cadenceLabel')} "
        f"harmony={summary.get('harmonyFocus')} technique={summary.get('techniqueFocus')}"
    )
    debug = resp.get("debug") or {}
    plan = debug.get("planSummary") or {}
    if plan:
        lines.append(f"plan: {json.dumps(plan, default=str)[:400]}")

    # Render a measure-by-measure ascii of events
    events = []
    # pull from musicxml? easier: reconstruct via entry call... skip. Use a second path:
    return "\n".join(lines)


def analyze_batch(grade: int, key: str, seeds: list[str], measures: int = 4) -> None:
    rh_opens: Counter[int] = Counter()
    rh_top_range: list[int] = []
    rh_low_range: list[int] = []
    lh_bottom: list[int] = []
    all_rh_pitches: list[list[int]] = []
    all_lh_pitches: list[list[int]] = []
    rhythms: Counter[str] = Counter()
    contour_signatures: Counter[str] = Counter()
    cadences: Counter[str] = Counter()
    phrase_shapes: Counter[str] = Counter()

    samples = []
    for seed in seeds:
        req = {
            "mode": "piano",
            "grade": grade,
            "timeSignature": "4/4",
            "measureCount": measures,
            "tempoPreset": "medium",
            "keySignature": key,
            "handPosition": "C",
            "handActivity": "both",
            "coordinationStyle": "together",
            "readingFocus": "balanced",
            "rightHandMotion": "mixed",
            "leftHandPattern": "held",
            "allowRests": False,
            "allowAccidentals": False,
            "seed": seed,
        }
        resp = build_exercise(req)
        # parse response events from musicxml is complex; internal builder exposes events via debug?
        # Instead, re-run the internal _build_piano_candidate path for analysis:
        samples.append(resp)
    return samples


def print_events_for_seed(grade: int, key: str, seed: str, measures: int = 4) -> None:
    """Use internal builder to get event list directly."""
    import random
    from backend.app.generator._builder import _build_piano_candidate
    from backend.app.generator._planning import _build_style_profile
    from backend.app.generator._helpers import _preset_for_grade
    from backend.app.generator._scoring import _validate_events, _evaluate_candidate, _quality_gate_result

    req = {
        "mode": "piano",
        "grade": grade,
        "timeSignature": "4/4",
        "measureCount": measures,
        "tempoPreset": "medium",
        "keySignature": key,
        "handPosition": "C",
        "handActivity": "both",
        "coordinationStyle": "together",
        "readingFocus": "balanced",
        "rightHandMotion": "mixed",
        "leftHandPattern": "held",
        "allowRests": False,
        "allowAccidentals": False,
        "seed": seed,
    }
    preset = _preset_for_grade(grade)
    profile = _build_style_profile(req, preset)

    best = None
    best_score = -1.0
    best_gate = None
    for attempt in range(profile.search_attempts):
        rng = random.Random(f"{seed}-{attempt}")
        cand = _build_piano_candidate(req, rng)
        if not _validate_events(req, cand["events"]):
            continue
        ev = _evaluate_candidate(req, cand)
        gate = _quality_gate_result(req, cand, ev)
        cand["evaluationBreakdown"] = ev
        cand["qualityGate"] = gate
        # Prefer passing, then score
        score = ev.total + (0.05 if gate.passed else 0.0)
        if score > best_score:
            best_score = score
            best = cand
            best_gate = gate

    if best is None:
        print(f"FAIL seed={seed}")
        return

    events = best["events"]
    rh = [e for e in events if e["hand"] == "rh"]
    lh = [e for e in events if e["hand"] == "lh"]

    print(f"\n--- grade={grade} key={key} seed={seed} bars={measures} ---")
    if best_gate:
        print(f"gatePassed={best_gate.passed} gateScore={best_gate.score:.3f} reasons={best_gate.reasons}")
    from dataclasses import asdict
    try:
        print(f"score={asdict(best['evaluationBreakdown'])}")
    except Exception:
        pass

    # Group by measure
    from collections import defaultdict
    by_measure_rh: dict[int, list] = defaultdict(list)
    by_measure_lh: dict[int, list] = defaultdict(list)
    for e in rh:
        by_measure_rh[int(e["measure"])].append(e)
    for e in lh:
        by_measure_lh[int(e["measure"])].append(e)

    for m in sorted(set(list(by_measure_rh.keys()) + list(by_measure_lh.keys()))):
        rh_str = " ".join(
            f"{'R' if e['isRest'] else '/'.join(midi_to_name(int(p)) for p in e['pitches'])}:{e['quarterLength']}"
            for e in by_measure_rh.get(m, [])
        )
        lh_str = " ".join(
            f"{'R' if e['isRest'] else '/'.join(midi_to_name(int(p)) for p in e['pitches'])}:{e['quarterLength']}"
            for e in by_measure_lh.get(m, [])
        )
        print(f"  m{m}  RH: {rh_str}")
        print(f"        LH: {lh_str}")


if __name__ == "__main__":
    # Six seeds per grade, C major and F major, 4 bars
    for grade in (1, 2, 3):
        for key in ("C", "F"):
            for i in range(4):
                print_events_for_seed(grade, key, f"audit{grade}{key}{i}")
    # Also try 8-bar exercises at grade 2 and 3 for phrase-grammar inspection
    print("\n\n================ 8-bar samples ================")
    for grade in (2, 3):
        for i in range(3):
            print_events_for_seed(grade, "C", f"audit8-{grade}-{i}", measures=8)

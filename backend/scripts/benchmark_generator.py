from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.generator import build_exercise  # noqa: E402


CASES = [
    {
        "label": "grade-1-balanced",
        "mode": "piano",
        "grade": 1,
        "timeSignature": "4/4",
        "measureCount": 4,
        "tempoPreset": "slow",
        "keySignature": "C",
        "handPosition": "C",
        "handActivity": "both",
        "coordinationStyle": "support",
        "readingFocus": "balanced",
        "rightHandMotion": "stepwise",
        "leftHandPattern": "held",
        "allowRests": True,
        "allowAccidentals": False,
        "seed": "bench-g1-balanced",
    },
    {
        "label": "grade-3-balanced",
        "mode": "piano",
        "grade": 3,
        "timeSignature": "4/4",
        "measureCount": 4,
        "tempoPreset": "medium",
        "keySignature": "C",
        "handPosition": "C",
        "handActivity": "both",
        "coordinationStyle": "support",
        "readingFocus": "balanced",
        "rightHandMotion": "mixed",
        "leftHandPattern": "simple-broken",
        "allowRests": True,
        "allowAccidentals": False,
        "seed": "bench-g3-balanced",
    },
    {
        "label": "grade-4-harmonic",
        "mode": "piano",
        "grade": 4,
        "timeSignature": "4/4",
        "measureCount": 4,
        "tempoPreset": "medium",
        "keySignature": "F",
        "handPosition": "C",
        "handActivity": "both",
        "coordinationStyle": "support",
        "readingFocus": "harmonic",
        "rightHandMotion": "mixed",
        "leftHandPattern": "held",
        "allowRests": True,
        "allowAccidentals": True,
        "seed": "bench-g4-harmonic",
    },
    {
        "label": "grade-5-melodic",
        "mode": "piano",
        "grade": 5,
        "timeSignature": "4/4",
        "measureCount": 4,
        "tempoPreset": "medium",
        "keySignature": "G",
        "handPosition": "C",
        "handActivity": "both",
        "coordinationStyle": "support",
        "readingFocus": "melodic",
        "rightHandMotion": "mixed",
        "leftHandPattern": "simple-broken",
        "allowRests": True,
        "allowAccidentals": True,
        "seed": "bench-g5-melodic",
    },
]


def run_case(payload: dict[str, object]) -> dict[str, object]:
    result = build_exercise(payload)
    return {
        "label": payload["label"],
        "title": result["title"],
        "summary": result["summary"],
        "debug": result.get("debug"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run fixed-seed SheetGenerator benchmark cases.")
    parser.add_argument("--out", type=Path, help="Optional JSON output path.")
    args = parser.parse_args()

    results = [run_case(dict(case)) for case in CASES]
    rendered = json.dumps(results, indent=2)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
        print(f"Wrote benchmark results to {args.out}")
        return

    print(rendered)


if __name__ == "__main__":
    main()

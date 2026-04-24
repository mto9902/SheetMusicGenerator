from __future__ import annotations

import json
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
SHARED_DIR = ROOT_DIR / "shared"
CACHE_DIR = ROOT_DIR / "backend" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _load_json(filename: str):
    with (SHARED_DIR / filename).open("r", encoding="utf-8") as handle:
        return json.load(handle)


EXERCISE_OPTIONS = _load_json("exercise-options.json")
GRADE_PRESETS = _load_json("difficulty-presets.json")

TEMPO_BY_PRESET = {
    item["value"]: item["bpm"] for item in EXERCISE_OPTIONS["tempoPresets"]
}

POSITION_LABELS = {
    item["value"]: item["label"] for item in EXERCISE_OPTIONS["handPositions"]
}

GRADE_STAGE_LABELS = {
    item["value"]: item["label"] for item in EXERCISE_OPTIONS.get("gradeStages", [])
}

HAND_ACTIVITY_LABELS = {
    item["value"]: item["label"] for item in EXERCISE_OPTIONS["handActivities"]
}

COORDINATION_LABELS = {
    item["value"]: item["label"] for item in EXERCISE_OPTIONS["coordinationStyles"]
}

READING_FOCUS_LABELS = {
    item["value"]: item["label"] for item in EXERCISE_OPTIONS["readingFocuses"]
}

LEFT_PATTERN_LABELS = {
    item["value"]: item["label"] for item in EXERCISE_OPTIONS["leftHandPatterns"]
}

GRADE_LABELS = {item["value"]: item["label"] for item in EXERCISE_OPTIONS["grades"]}

# --- Key signature mappings ---
# Pitch class of the tonic for every supported key signature.
# Minor keys use lowercase-first convention: "Am", "Dm", etc.
KEY_TONIC_PITCH_CLASS = {
    # Major keys
    "C": 0,
    "G": 7,
    "D": 2,
    "F": 5,
    "Bb": 10,
    "A": 9,
    "E": 4,
    "Eb": 3,
    "Ab": 8,
    # Minor keys (natural minor tonic)
    "Am": 9,
    "Dm": 2,
    "Em": 4,
    "Gm": 7,
    "Cm": 0,
    "Bm": 11,
    "Fm": 5,
    "F#m": 6,
    "C#m": 1,
}

MAJOR_SCALE_STEPS = [0, 2, 4, 5, 7, 9, 11]
MINOR_SCALE_STEPS = [0, 2, 3, 5, 7, 8, 10]  # natural minor


def is_minor_key(key_signature: str) -> bool:
    return key_signature.endswith("m") and key_signature != "Bb"


def scale_steps_for_key(key_signature: str) -> list[int]:
    return MINOR_SCALE_STEPS if is_minor_key(key_signature) else MAJOR_SCALE_STEPS


HAND_POSITION_ROOTS = {
    "rh": {
        "C": 60,
        "G": 67,
        "D": 62,
        "F": 65,
        "Bb": 70,
    },
    "lh": {
        "C": 48,
        "G": 43,
        "D": 50,
        "F": 41,
        "Bb": 46,
    },
}

HAND_POSITION_LIMITS = {
    "rh": (57, 72),
    "lh": (40, 55),
}

# Grade-aware range expansion: higher grades get wider range (ledger lines)
HAND_POSITION_LIMITS_BY_GRADE = {
    1: {"rh": (57, 72), "lh": (40, 55)},
    2: {"rh": (57, 72), "lh": (40, 55)},
    3: {"rh": (55, 76), "lh": (38, 55)},
    4: {"rh": (52, 81), "lh": (36, 57)},
    5: {"rh": (48, 84), "lh": (33, 60)},
}

GRADE_ONE_STAGE_SPECS = {
    "g1-pocket": {
        "rh": {"below_steps": 0, "above_steps": 4},
        "lh": {"below_steps": 0, "above_steps": 4},
        "max_leap": 2,
        "allow_intervals": ("2nd",),
        "allowed_left_families": ("held", "repeated"),
    },
    "g1-extend": {
        "rh": {"below_steps": 0, "above_steps": 6},
        "lh": {"below_steps": 2, "above_steps": 4},
        "max_leap": 4,
        "allow_intervals": ("2nd", "3rd"),
        "allowed_left_families": ("held", "repeated", "support-bass"),
    },
    "g1-staff": {
        "rh": {"below_steps": 1, "above_steps": 9},
        "lh": {"below_steps": 5, "above_steps": 4},
        "max_leap": 4,
        "allow_intervals": ("2nd", "3rd"),
        "allowed_left_families": ("held", "repeated", "support-bass"),
    },
}


def normalize_grade_stage(
    grade: int,
    mode: str,
    grade_stage: str | None,
) -> str | None:
    if mode != "piano" or grade != 1:
        return None
    if grade_stage in GRADE_ONE_STAGE_SPECS:
        return grade_stage
    return "g1-extend"


def grade_one_stage_spec(grade_stage: str | None) -> dict[str, object] | None:
    normalized = normalize_grade_stage(1, "piano", grade_stage)
    if normalized is None:
        return None
    return GRADE_ONE_STAGE_SPECS[normalized]


def request_grade_stage(request: dict[str, object]) -> str | None:
    return normalize_grade_stage(
        int(request.get("grade", 1)),
        str(request.get("mode", "piano")),
        str(request.get("gradeStage")) if request.get("gradeStage") else None,
    )


def request_max_leap(request: dict[str, object], default_max_leap: int) -> int:
    stage_spec = grade_one_stage_spec(request_grade_stage(request))
    if stage_spec is None:
        return default_max_leap
    return min(default_max_leap, int(stage_spec.get("max_leap", default_max_leap)))


def hand_position_limits_for_grade(hand: str, grade: int) -> tuple[int, int]:
    """Return (low, high) MIDI limits for the given hand and grade."""
    grade_limits = HAND_POSITION_LIMITS_BY_GRADE.get(grade)
    if grade_limits:
        return grade_limits[hand]
    return HAND_POSITION_LIMITS[hand]

MEASURE_TOTALS = {
    "2/4": 2.0,
    "3/4": 3.0,
    "4/4": 4.0,
    "6/8": 3.0,
}

PULSE_BY_SIGNATURE = {
    "2/4": 1.0,
    "3/4": 1.0,
    "4/4": 1.0,
    "6/8": 1.5,
}

# Roman-numeral → semitone offset from tonic.
# Both major-key and minor-key numerals are listed so harmonic plans
# can reference either vocabulary.
HARMONY_INTERVALS = {
    # Major-key chords
    "I": 0,
    "ii": 2,
    "iii": 4,
    "IV": 5,
    "V": 7,
    "vi": 9,
    # Minor-key chords
    "i": 0,
    "III": 3,
    "iv": 5,
    "v": 7,
    "VI": 8,
    "VII": 10,
}

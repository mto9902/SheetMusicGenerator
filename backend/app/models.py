from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .config import GRADE_PRESETS


ExerciseMode = Literal["piano", "rhythm"]
TimeSignature = Literal["2/4", "3/4", "4/4", "6/8"]
TempoPreset = Literal["slow", "medium", "fast"]
KeySignature = Literal[
    "C", "G", "F", "D", "Bb", "A", "E", "Eb", "Ab",
    "Am", "Dm", "Em", "Gm", "Cm", "Bm", "Fm", "F#m", "C#m",
]
HandPosition = Literal["C", "G", "D", "F", "Bb"]
HandActivity = Literal["right-only", "left-only", "both"]
CoordinationStyle = Literal["support", "alternating", "together"]
ReadingFocus = Literal["balanced", "melodic", "harmonic"]
RightHandMotion = Literal["stepwise", "small-leaps", "mixed"]
LeftHandPattern = Literal["held", "repeated", "simple-broken"]
Grade = Literal[1, 2, 3, 4, 5]

ALLOWED_MEASURE_COUNTS = {4, 8, 12}


def _max_bars_for_grade(grade: int) -> int:
    preset = next(item for item in GRADE_PRESETS if item["grade"] == grade)
    return int(preset["piano"]["maxBars"])


class ExerciseRequest(BaseModel):
    mode: ExerciseMode
    grade: Grade = Field(ge=1, le=5)
    timeSignature: TimeSignature
    measureCount: int = Field(ge=4, le=12)
    tempoPreset: TempoPreset
    keySignature: KeySignature
    handPosition: HandPosition
    handActivity: HandActivity
    coordinationStyle: CoordinationStyle
    readingFocus: ReadingFocus
    rightHandMotion: RightHandMotion
    leftHandPattern: LeftHandPattern
    allowRests: bool
    allowAccidentals: bool
    seed: str

    @model_validator(mode="after")
    def normalize(self):
        if self.measureCount not in ALLOWED_MEASURE_COUNTS:
            raise ValueError("measureCount must be one of: 4, 8, 12")

        if self.measureCount > _max_bars_for_grade(self.grade):
            raise ValueError(
                f"grade {self.grade} supports up to {_max_bars_for_grade(self.grade)} bars"
            )

        if self.mode == "rhythm":
            self.keySignature = "C"
            self.allowAccidentals = False

        if self.grade < 4:
            self.allowAccidentals = False

        return self


class ExerciseSummary(BaseModel):
    bpm: int
    handPositionLabel: str
    coordinationLabel: str
    phraseShapeLabel: str
    cadenceLabel: str
    harmonyFocus: list[str]
    techniqueFocus: list[str]
    rhythmFocus: list[str]
    seedLabel: str


class ExerciseDebug(BaseModel):
    scoreBreakdown: dict[str, float] | None = None
    planSummary: dict[str, Any] | None = None
    qualityGate: dict[str, Any] | None = None


class ExerciseResponse(BaseModel):
    exerciseId: str
    seed: str
    config: ExerciseRequest
    title: str
    musicXml: str
    svg: str
    audioUrl: str
    measureCount: int
    timeSignature: TimeSignature
    grade: int
    summary: ExerciseSummary
    debug: ExerciseDebug | None = None

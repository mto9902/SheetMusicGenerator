"""Dataclass definitions used throughout the generator package."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StyleProfile:
    grade: int
    focus: str
    cadence_strength: float
    left_hand_persistence: float
    register_span: tuple[float, float]
    texture_ceiling: str
    allowed_connection_functions: tuple[str, ...]
    allowed_ornament_functions: tuple[str, ...]
    accidental_policy: str
    density_floor: float
    density_ceiling: float
    search_attempts: int


@dataclass(frozen=True)
class PhraseGrammar:
    """Grammatical role and shape pre-decided for each phrase."""
    phrase_index: int
    function: str           # "antecedent", "consequent", "continuation", "closing"
    cadence_type: str       # "half", "authentic", "plagal", "deceptive"
    peak_position: float    # 0.0-1.0 within phrase (0=start, 1=end)
    opening_energy: float   # 0.0-1.0 — how assertively phrase begins
    energy_profile: tuple[float, ...]  # per-measure intensity multipliers (len = phrase length)


@dataclass(frozen=True)
class PiecePlan:
    phrase_count: int
    apex_measure: int
    cadence_map: dict[int, str]
    intensity_curve: dict[int, float]
    dynamic_arc: str
    contrast_measures: tuple[int, ...]
    phrase_grammars: tuple[PhraseGrammar, ...]
    summary: str


@dataclass(frozen=True)
class AnchorTone:
    measure: int
    beat: float
    pitch_role: str
    register_slot: float
    local_goal: str


@dataclass(frozen=True)
class ConnectionFunction:
    name: str
    role: str
    intensity: float


@dataclass(frozen=True)
class OrnamentFunction:
    name: str
    placement: str


@dataclass(frozen=True)
class LinePlan:
    phrase_index: int
    climax_measure: int
    register_trajectory: dict[int, float]
    anchors: tuple[AnchorTone, ...]
    connections: dict[int, ConnectionFunction]
    ornaments: dict[int, OrnamentFunction]


@dataclass(frozen=True)
class TopLinePlan:
    phrase_index: int
    peak_measure: int
    register_targets: dict[int, float]
    pitch_roles: dict[int, str]
    motion_roles: dict[int, str]


@dataclass(frozen=True)
class BassLinePlan:
    phrase_index: int
    cadence_measure: int
    register_targets: dict[int, float]
    pitch_roles: dict[int, str]
    motion_roles: dict[int, str]


@dataclass(frozen=True)
class AccompanimentPlan:
    role: str
    primary_family: str
    support_families: tuple[str, ...]
    cadence_family: str


@dataclass(frozen=True)
class PhraseBlueprint:
    phrase_index: int
    measures: tuple[int, ...]
    archetype: str
    phrase_role: str
    cadence_target: str
    primary_motive: dict[str, Any]
    answer_form: str
    accompaniment_role: str
    line_plan: LinePlan
    top_line_plan: TopLinePlan
    bass_line_plan: BassLinePlan


@dataclass(frozen=True)
class EvaluationBreakdown:
    phrase_coherence: float = 0.0
    motivic_recurrence: float = 0.0
    line_continuity: float = 0.0
    anchor_clarity: float = 0.0
    non_chord_tone_correctness: float = 0.0
    cadence_preparation: float = 0.0
    register_arc_quality: float = 0.0
    lh_role_stability: float = 0.0
    rh_lh_hierarchy: float = 0.0
    difficulty_smoothness: float = 0.0
    sight_reading_chunkability: float = 0.0
    accidental_justification: float = 0.0
    top_line_strength: float = 0.0
    bass_function: float = 0.0
    foreground_background_clarity: float = 0.0
    vertical_balance: float = 0.0
    total: float = 0.0


@dataclass(frozen=True)
class QualityGateResult:
    passed: bool = True
    score: float = 1.0
    reasons: tuple[str, ...] = ()

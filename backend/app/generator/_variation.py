"""Variation profiles for broadening generator output shape."""
from __future__ import annotations

from dataclasses import dataclass, field
import random
from typing import Any


@dataclass(frozen=True)
class VariationProfile:
    """Internal planning profile used to avoid one default melodic habit."""

    name: str
    label: str
    min_grade: int
    max_grade: int = 5
    weight: float = 1.0
    archetype_weights: dict[str, float] = field(default_factory=dict)
    contour_weights: dict[str, float] = field(default_factory=dict)
    lh_family_bias: dict[str, float] = field(default_factory=dict)
    texture_bias: dict[str, float] = field(default_factory=dict)
    rhythm_scope: str = "piece"  # piece, phrase, loose
    contour_strategy: str = "locked"  # locked, contrast, free
    motif_density: str = "standard"  # standard, light, cadence
    replay_a_prime: str = "strict"  # strict, loose, none


_ARCHETYPES = ("period", "sentence", "lyric", "sequence")
_CONTOURS = ("ascending", "descending", "arch", "valley", "flat")
_CONTOUR_COMPLEMENT = {
    "ascending": "descending",
    "descending": "ascending",
    "arch": "valley",
    "valley": "arch",
    "flat": "flat",
}

_PROFILES: tuple[VariationProfile, ...] = (
    VariationProfile(
        name="songlike-stepwise",
        label="Songlike stepwise line",
        min_grade=1,
        weight=1.2,
        archetype_weights={"period": 1.5, "lyric": 1.3, "sentence": 0.9, "sequence": 0.5},
        contour_weights={"arch": 1.6, "ascending": 1.2, "descending": 1.0, "valley": 0.7, "flat": 0.45},
        lh_family_bias={"held": 1.15, "block-half": 1.1, "support-bass": 1.05},
        rhythm_scope="piece",
        contour_strategy="locked",
        motif_density="standard",
        replay_a_prime="strict",
    ),
    VariationProfile(
        name="question-answer",
        label="Question and answer",
        min_grade=1,
        weight=1.1,
        archetype_weights={"period": 1.9, "sentence": 1.1, "lyric": 0.9, "sequence": 0.65},
        contour_weights={"ascending": 1.15, "descending": 1.15, "arch": 1.0, "valley": 0.9, "flat": 0.35},
        lh_family_bias={"held": 1.05, "block-half": 1.2, "support-bass": 1.15, "bass-and-chord": 1.1},
        rhythm_scope="phrase",
        contour_strategy="contrast",
        motif_density="light",
        replay_a_prime="loose",
    ),
    VariationProfile(
        name="interval-reading",
        label="Interval reading",
        min_grade=1,
        weight=0.9,
        archetype_weights={"sentence": 1.25, "sequence": 1.2, "period": 0.9, "lyric": 0.8},
        contour_weights={"arch": 1.25, "valley": 1.15, "ascending": 1.0, "descending": 1.0, "flat": 0.4},
        lh_family_bias={"support-bass": 1.25, "repeated": 1.1, "bass-and-chord": 1.05},
        rhythm_scope="phrase",
        contour_strategy="free",
        motif_density="light",
        replay_a_prime="none",
    ),
    VariationProfile(
        name="left-hand-feature",
        label="Left hand feature",
        min_grade=1,
        weight=0.95,
        archetype_weights={"period": 1.1, "sentence": 1.0, "lyric": 0.85, "sequence": 0.95},
        contour_weights={"descending": 1.25, "valley": 1.2, "arch": 0.95, "ascending": 0.85, "flat": 0.5},
        lh_family_bias={"support-bass": 1.75, "repeated": 1.45, "bass-and-chord": 1.35, "simple-broken": 1.2},
        rhythm_scope="phrase",
        contour_strategy="contrast",
        motif_density="light",
        replay_a_prime="loose",
    ),
    VariationProfile(
        name="cadence-drill",
        label="Cadence drill",
        min_grade=1,
        weight=0.75,
        archetype_weights={"period": 1.25, "sentence": 1.2, "lyric": 0.8, "sequence": 0.75},
        contour_weights={"descending": 1.35, "arch": 1.1, "ascending": 0.85, "valley": 0.8, "flat": 0.55},
        lh_family_bias={"block-half": 1.35, "bass-and-chord": 1.35, "support-bass": 1.1},
        rhythm_scope="piece",
        contour_strategy="contrast",
        motif_density="cadence",
        replay_a_prime="loose",
    ),
    VariationProfile(
        name="hands-alternating",
        label="Hands alternating",
        min_grade=2,
        weight=0.85,
        archetype_weights={"period": 1.0, "sentence": 1.25, "sequence": 1.0, "lyric": 0.8},
        contour_weights={"valley": 1.25, "arch": 1.15, "ascending": 0.95, "descending": 0.95, "flat": 0.45},
        lh_family_bias={"support-bass": 1.45, "repeated": 1.3, "simple-broken": 1.25},
        rhythm_scope="loose",
        contour_strategy="free",
        motif_density="light",
        replay_a_prime="none",
    ),
    VariationProfile(
        name="rhythmic-study",
        label="Rhythmic study",
        min_grade=2,
        weight=0.9,
        archetype_weights={"sentence": 1.25, "period": 1.0, "sequence": 1.1, "lyric": 0.65},
        contour_weights={"flat": 1.15, "arch": 1.05, "ascending": 0.95, "descending": 0.95, "valley": 0.85},
        lh_family_bias={"repeated": 1.35, "block-quarter": 1.25, "support-bass": 1.2},
        rhythm_scope="loose",
        contour_strategy="free",
        motif_density="cadence",
        replay_a_prime="none",
    ),
    VariationProfile(
        name="sequence-pattern",
        label="Sequence pattern",
        min_grade=3,
        weight=0.9,
        archetype_weights={"sequence": 2.1, "sentence": 1.1, "period": 0.7, "lyric": 0.45},
        contour_weights={"ascending": 1.3, "descending": 1.3, "arch": 0.95, "valley": 0.95, "flat": 0.35},
        lh_family_bias={"support-bass": 1.2, "simple-broken": 1.2, "bass-and-chord": 1.1},
        rhythm_scope="phrase",
        contour_strategy="contrast",
        motif_density="standard",
        replay_a_prime="loose",
    ),
    VariationProfile(
        name="texture-contrast",
        label="Texture contrast",
        min_grade=3,
        weight=0.8,
        archetype_weights={"sentence": 1.25, "period": 1.0, "sequence": 1.0, "lyric": 0.8},
        contour_weights={"arch": 1.25, "valley": 1.1, "ascending": 1.0, "descending": 1.0, "flat": 0.45},
        lh_family_bias={"bass-and-chord": 1.45, "block-half": 1.3, "simple-broken": 1.2},
        texture_bias={"chordal": 1.7, "running": 1.15, "melody": 0.9},
        rhythm_scope="phrase",
        contour_strategy="contrast",
        motif_density="light",
        replay_a_prime="loose",
    ),
    VariationProfile(
        name="broken-chord-reading",
        label="Broken chord reading",
        min_grade=4,
        weight=0.85,
        archetype_weights={"sequence": 1.45, "sentence": 1.15, "period": 0.9, "lyric": 0.7},
        contour_weights={"ascending": 1.2, "arch": 1.15, "descending": 1.0, "valley": 0.9, "flat": 0.35},
        lh_family_bias={"simple-broken": 2.0, "arpeggio-support": 1.8, "alberti": 1.55, "waltz-bass": 1.25},
        texture_bias={"running": 1.65, "chordal": 1.15, "melody": 0.85},
        rhythm_scope="phrase",
        contour_strategy="free",
        motif_density="light",
        replay_a_prime="none",
    ),
)


def _weighted_choice(
    choices: tuple[str, ...],
    weights: dict[str, float],
    rng: random.Random,
) -> str:
    raw_weights = [max(0.001, float(weights.get(choice, 1.0))) for choice in choices]
    return rng.choices(list(choices), weights=raw_weights, k=1)[0]


def _eligible_variation_profiles(request: dict[str, Any]) -> list[VariationProfile]:
    grade = int(request.get("grade", 1))
    if request.get("mode") != "piano":
        return []

    eligible = [
        profile
        for profile in _PROFILES
        if profile.min_grade <= grade <= profile.max_grade
    ]

    # Keep Grade 1 stage gates pedagogical: broad staff reading still varies,
    # but not by adding later-grade texture or broken-chord behavior.
    if grade == 1:
        eligible = [
            profile
            for profile in eligible
            if profile.name in {
                "songlike-stepwise",
                "question-answer",
                "interval-reading",
                "left-hand-feature",
                "cadence-drill",
            }
        ]
    return eligible


def _pick_variation_profile(request: dict[str, Any], rng: random.Random) -> VariationProfile:
    eligible = _eligible_variation_profiles(request)
    if not eligible:
        return _PROFILES[0]
    return rng.choices(eligible, weights=[max(0.01, profile.weight) for profile in eligible], k=1)[0]


def _pick_profile_archetype(profile: VariationProfile, rng: random.Random) -> str:
    return _weighted_choice(_ARCHETYPES, profile.archetype_weights, rng)


def _pick_profile_contour(profile: VariationProfile, rng: random.Random) -> str:
    return _weighted_choice(_CONTOURS, profile.contour_weights, rng)


def _phrase_contour_for_profile(
    profile: VariationProfile,
    phrase_index: int,
    piece_contour: str | None,
    previous_contour: str | None,
    rng: random.Random,
) -> tuple[str, bool]:
    if profile.contour_strategy == "free":
        return _pick_profile_contour(profile, rng), False

    base_contour = piece_contour or previous_contour or _pick_profile_contour(profile, rng)
    if profile.contour_strategy == "contrast":
        if phrase_index == 0:
            return base_contour, False
        if phrase_index == 1:
            return _CONTOUR_COMPLEMENT.get(base_contour, base_contour), False
        return _pick_profile_contour(profile, rng), False

    if phrase_index == 0:
        return base_contour, False
    if phrase_index == 1:
        return base_contour, True
    return _CONTOUR_COMPLEMENT.get(base_contour, base_contour), True


def _variation_profile_debug(profile: VariationProfile) -> dict[str, Any]:
    return {
        "name": profile.name,
        "label": profile.label,
        "rhythmScope": profile.rhythm_scope,
        "contourStrategy": profile.contour_strategy,
        "motifDensity": profile.motif_density,
        "replayAPrime": profile.replay_a_prime,
    }

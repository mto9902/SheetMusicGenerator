"""Phrase structure, piece/phrase planning, and blueprint construction."""
from __future__ import annotations

import math
import random
from typing import Any

from ._types import (
    AccompanimentPlan,
    AnchorTone,
    BassLinePlan,
    ConnectionFunction,
    LinePlan,
    OrnamentFunction,
    PhraseBlueprint,
    PhraseGrammar,
    PiecePlan,
    StyleProfile,
    TopLinePlan,
)
from ._helpers import _measure_total, _fit_measure_variants, _signature_similarity
from ._harmony import _phrase_form_template, _form_label
from ._rhythm import _RHYTHM_CELLS_SIMPLE, _pick_rhythm_cells, _pick_contour, _related_contour, _CADENCE_LIBRARY
from ._texture import (
    _nearest_pool_index,
    _duration_signature,
    _relative_slot_to_index,
    _pitch_role_candidates,
)
from ._chord import _preferred_left_families

# ---------------------------------------------------------------------------
# Phrase structure
# ---------------------------------------------------------------------------

_ROLE_DENSITY_TARGETS = {
    "establish": 0.28,
    "answer": 0.42,
    "develop": 0.56,
    "intensify": 0.72,
    "cadence": 0.24,
}

_MOTIVE_STEP_TEMPLATES = {
    "ascending": [
        [1, 2],
        [2, 1],
        [1, 2, 1],
        [1, 1, 2],
    ],
    "descending": [
        [-1, -2],
        [-2, -1],
        [-1, -2, -1],
        [-1, -1, -2],
    ],
    "arch": [
        [1, 2, -1],
        [2, 1, -2],
        [1, 1, -2],
        [2, -1, -1],
    ],
    "valley": [
        [-1, -2, 1],
        [-2, -1, 2],
        [-1, -1, 2],
        [-2, 1, 1],
    ],
    "flat": [
        [0, 1, -1],
        [1, 0, -1],
        [0, -1, 1],
        [1, -1, 0],
    ],
}

_MOTIVE_TRANSFORM_BY_ROLE = {
    "establish": "base",
    "answer": "sequence",
    "develop": "sequence",
    "intensify": "fragment",
    "cadence": "cadence",
}

_CONNECTION_LIBRARY = {
    "period": {
        "establish": ["lead_in", "arrival"],
        "answer": ["passing", "echo_fragment"],
        "develop": ["passing", "neighbor"],
        "intensify": ["sequence", "arpeggiation"],
        "cadence": ["cadential_turn", "liquidation"],
    },
    "sentence": {
        "establish": ["lead_in", "echo_fragment"],
        "answer": ["echo_fragment", "sequence"],
        "develop": ["sequence", "passing"],
        "intensify": ["sequence", "arpeggiation"],
        "cadence": ["cadential_turn", "liquidation"],
    },
    "lyric": {
        "establish": ["arrival", "lead_in"],
        "answer": ["neighbor", "echo_fragment"],
        "develop": ["passing", "neighbor"],
        "intensify": ["suspension_like", "passing"],
        "cadence": ["cadential_turn", "arrival"],
    },
    "sequence": {
        "establish": ["lead_in", "arrival"],
        "answer": ["sequence", "echo_fragment"],
        "develop": ["sequence", "arpeggiation"],
        "intensify": ["sequence", "liquidation"],
        "cadence": ["cadential_turn", "liquidation"],
    },
}

_ORNAMENT_LIBRARY = {
    1: ["none", "arrival"],
    2: ["none", "arrival", "passing"],
    3: ["none", "passing", "neighbor", "arrival"],
    4: ["none", "passing", "neighbor", "chromatic_approach", "arrival"],
    5: ["none", "passing", "neighbor", "chromatic_approach", "release_turn", "arrival"],
}

_ACCOMPANIMENT_ROLE_LIBRARY = {
    "anchor": ["support-bass", "repeated", "held", "block-half", "bass-and-chord"],
    "pulse_support": ["support-bass", "repeated", "simple-broken", "block-quarter", "bass-and-chord", "waltz-bass"],
    "broken_support": ["simple-broken", "arpeggio-support", "alberti", "support-bass", "waltz-bass"],
    "cadence_support": ["bass-and-chord", "block-half", "octave-support", "support-bass"],
    "arrival_emphasis": ["bass-and-chord", "support-bass", "octave-support", "block-half", "arpeggio-support"],
}

_LEFT_PATTERN_FAMILY_PREFERENCES = {
    "held": ("held", "block-half", "block-quarter", "bass-and-chord"),
    "repeated": ("repeated", "support-bass", "waltz-bass", "octave-support"),
    "simple-broken": ("simple-broken", "arpeggio-support", "alberti"),
}

_REGISTER_MAPS = {
    1: {"floor": 0.18, "center": 0.42, "peak": 0.58},
    2: {"floor": 0.16, "center": 0.45, "peak": 0.62},
    3: {"floor": 0.14, "center": 0.48, "peak": 0.68},
    4: {"floor": 0.12, "center": 0.52, "peak": 0.78},
    5: {"floor": 0.10, "center": 0.55, "peak": 0.86},
}

_PHRASE_ARCHETYPES = {
    "period": {
        "establish": ["hold-answer"],
        "answer": ["neighbor-answer", "echo-tail"],
        "develop": ["bridge"],
        "intensify": ["climb"],
        "cadence": ["cadence-step"],
    },
    "sentence": {
        "establish": ["echo-tail"],
        "answer": ["echo-tail", "sequence-tail"],
        "develop": ["sequence-tail"],
        "intensify": ["fragment-push"],
        "cadence": ["cadence-step"],
    },
    "lyric": {
        "establish": ["sustain"],
        "answer": ["neighbor-answer"],
        "develop": ["bridge"],
        "intensify": ["rise-release"],
        "cadence": ["cadence-turn"],
    },
    "sequence": {
        "establish": ["hold-answer"],
        "answer": ["sequence-tail"],
        "develop": ["sequence-tail", "bridge"],
        "intensify": ["climb", "fragment-push"],
        "cadence": ["cadence-step"],
    },
}


def _choose_phrase_archetype(
    phrase_measures: list[int],
    role_by_measure: dict[int, str],
    texture_by_measure: dict[int, str],
    request: dict[str, Any],
    rng: random.Random,
) -> str:
    grade = int(request["grade"])
    focus = str(request.get("readingFocus", "balanced"))
    textures = [texture_by_measure.get(measure_number, "melody") for measure_number in phrase_measures]
    running_count = sum(1 for texture in textures if texture == "running")
    chordal_count = sum(1 for texture in textures if texture == "chordal")

    archetypes = ["period", "sentence", "lyric", "sequence"]
    weights: list[float] = []
    for name in archetypes:
        weight = 1.0
        if name == "period":
            weight = 1.4
            if focus == "balanced":
                weight += 0.3
        elif name == "sentence":
            weight = 1.1 + (0.25 if grade >= 5 else 0.0)
            if any(role == "intensify" for role in role_by_measure.values()):
                weight += 0.25
        elif name == "lyric":
            weight = 0.95 + (0.35 if focus == "melodic" else 0.0)
            if chordal_count == 0:
                weight += 0.15
        elif name == "sequence":
            weight = 0.9 + (0.25 if running_count > 0 else 0.0)
            if focus == "harmonic":
                weight -= 0.1
        weights.append(max(0.1, weight))

    return rng.choices(archetypes, weights=weights, k=1)[0]


def _build_continuation_plan(
    archetype: str,
    phrase_measures: list[int],
    role_by_measure: dict[int, str],
    texture_by_measure: dict[int, str],
    cadence_target: str,
    motive_blueprint: dict[str, Any],
    rng: random.Random,
) -> dict[int, str]:
    gesture_map = _PHRASE_ARCHETYPES.get(archetype, _PHRASE_ARCHETYPES["period"])
    continuation_by_measure: dict[int, str] = {}
    transform_by_measure = motive_blueprint.get("transformByMeasure", {})

    for measure_number in phrase_measures:
        if texture_by_measure.get(measure_number) != "melody":
            continue
        role = role_by_measure.get(measure_number, "develop")
        transform = str(transform_by_measure.get(measure_number, "sequence"))
        if transform in {"base", "repeat"}:
            gestures = ["hold-answer", "echo-tail"]
        elif transform == "sequence":
            gestures = ["sequence-tail", "bridge"]
        elif transform == "fragment":
            gestures = ["fragment-push", "climb"]
        elif transform == "cadence":
            gestures = ["cadence-step", "cadence-turn"]
        else:
            gestures = list(gesture_map.get(role, ["bridge"]))
        if role == "cadence" and cadence_target == "dominant":
            gestures = ["cadence-turn", *gestures]
        continuation_by_measure[measure_number] = rng.choice(gestures)

    return continuation_by_measure


def _split_duration_value(duration_value: float, allowed_durations: list[float]) -> list[float] | None:
    ordered = sorted({round(float(value), 3) for value in allowed_durations}, reverse=True)
    for left in ordered:
        right = round(duration_value - left, 3)
        if right <= 0:
            continue
        if any(abs(candidate - right) < 0.02 for candidate in ordered):
            snapped_right = min(ordered, key=lambda candidate: abs(candidate - right))
            if abs((left + snapped_right) - duration_value) < 0.03:
                return [left, snapped_right]
    return None


def _expand_motive_durations(
    base: list[float],
    allowed_durations: list[float],
    *,
    target_total: float = 0.0,
) -> list[float]:
    durations = [round(float(value), 3) for value in base if value in set(allowed_durations)]
    if not durations:
        durations = [max(allowed_durations)]

    while len(durations) < 3:
        largest_index = max(range(len(durations)), key=lambda idx: durations[idx])
        split = _split_duration_value(durations[largest_index], allowed_durations)
        if not split:
            break
        durations = durations[:largest_index] + split + durations[largest_index + 1:]

    # Phase 4: if a target_total is given, repeat the cell pattern to fill the measure.
    if target_total > 0:
        current_total = round(sum(durations), 3)
        # Repeat the base cell to fill up to the measure total
        base_filtered = [round(float(v), 3) for v in base if v in set(allowed_durations)] or durations[:2]
        safety = 0
        while current_total < target_total - 0.001 and safety < 20:
            safety += 1
            remaining = round(target_total - current_total, 3)
            # Try to fit a full cell repetition
            cell_total = round(sum(base_filtered), 3)
            if cell_total <= remaining + 0.001:
                durations.extend(base_filtered)
                current_total = round(current_total + cell_total, 3)
            else:
                # Fill with the largest allowed duration that fits
                fitting = [d for d in sorted(allowed_durations, reverse=True) if d <= remaining + 0.001]
                if fitting:
                    durations.append(fitting[0])
                    current_total = round(current_total + fitting[0], 3)
                else:
                    break
        # Trim if we overshot
        while round(sum(durations), 3) > target_total + 0.001 and len(durations) > 1:
            durations.pop()
    else:
        if len(durations) > 4:
            durations = durations[:4]

    return durations


def _coherent_answer_durations(
    motif_durations: list[float],
    answer_cell: list[float],
    allowed_durations: list[float],
    rng: random.Random,
) -> list[float]:
    raw_answer = _expand_motive_durations(answer_cell or motif_durations, allowed_durations)
    base_signature = _duration_signature(motif_durations)
    answer_signature = _duration_signature(raw_answer)

    if len(raw_answer) == len(motif_durations) and _signature_similarity(base_signature, answer_signature) >= 0.55:
        return raw_answer

    answer_durations = list(motif_durations)
    if len(answer_durations) >= 3 and rng.random() < 0.3:
        tail = round(answer_durations[-2] + answer_durations[-1], 3)
        if any(abs(candidate - tail) < 0.02 for candidate in allowed_durations):
            snapped_tail = min(allowed_durations, key=lambda candidate: abs(candidate - tail))
            answer_durations = answer_durations[:-2] + [snapped_tail]
    return answer_durations


def _adapt_step_template(template: list[int], target_steps: int) -> list[int]:
    if target_steps <= 0:
        return []
    if len(template) == target_steps:
        return list(template)
    if len(template) > target_steps:
        return list(template[:target_steps])

    output = list(template)
    while len(output) < target_steps:
        if output:
            output.append(-output[-1] if len(output) % 2 == 1 else output[-1])
        else:
            output.append(1)
    return output[:target_steps]


def _build_motive_blueprint(
    anchor_cell: list[float],
    answer_cell: list[float],
    allowed_durations: list[float],
    contour: str,
    phrase_measures: list[int],
    role_by_measure: dict[int, str],
    texture_by_measure: dict[int, str],
    source_blueprint: dict[str, Any] | None,
    inherit_rhythm: bool,
    inherit_contour: bool,
    rng: random.Random,
    *,
    measure_total: float = 0.0,
) -> dict[str, Any]:
    source_blueprint = source_blueprint or {}
    source_durations = list(source_blueprint.get("answerDurations") or source_blueprint.get("durations") or [])
    source_steps = list(source_blueprint.get("steps") or [])

    # Phase 4: expand motif to fill the full measure
    if inherit_rhythm and source_durations:
        motif_durations = _expand_motive_durations(source_durations, allowed_durations, target_total=measure_total)
    else:
        motif_durations = _expand_motive_durations(
            anchor_cell or answer_cell or [max(allowed_durations)],
            allowed_durations,
            target_total=measure_total,
        )
    note_count = max(2, len(motif_durations))
    if inherit_contour and source_steps:
        motif_steps = _adapt_step_template(source_steps, note_count - 1)
        if len(motif_steps) >= 2 and rng.random() < 0.18:
            motif_steps = motif_steps[1:] + motif_steps[:1]
    else:
        template_pool = _MOTIVE_STEP_TEMPLATES.get(contour, _MOTIVE_STEP_TEMPLATES["flat"])
        step_template = rng.choice(template_pool)
        motif_steps = _adapt_step_template(step_template, note_count - 1)

    answer_seed = source_durations if inherit_rhythm and source_durations else answer_cell
    answer_durations = _coherent_answer_durations(motif_durations, answer_seed, allowed_durations, rng)

    transform_by_measure: dict[int, str] = {}
    melody_measures = [measure_number for measure_number in phrase_measures if texture_by_measure.get(measure_number) == "melody"]

    if melody_measures:
        transform_by_measure[melody_measures[0]] = "base"
        ordered_followups = melody_measures[1:]
        for index, measure_number in enumerate(ordered_followups, start=1):
            role = role_by_measure.get(measure_number, "develop")
            if role == "cadence":
                transform = "cadence"
            elif index == 1:
                transform = "repeat"
            elif role == "intensify":
                transform = "intensify"
            elif role == "develop":
                transform = "sequence"
            else:
                transform = _MOTIVE_TRANSFORM_BY_ROLE.get(role, "sequence")
            transform_by_measure[measure_number] = transform

    return {
        "durations": motif_durations,
        "steps": motif_steps,
        "transformByMeasure": transform_by_measure,
        "answerDurations": answer_durations,
    }


def _measure_role_sequence(length: int) -> list[str]:
    if length <= 1:
        return ["cadence"]
    if length == 2:
        return ["establish", "cadence"]
    if length == 3:
        return ["establish", "answer", "cadence"]

    roles = ["establish", "answer"]
    middle_count = max(0, length - 3)
    if middle_count <= 1:
        roles.append("intensify")
    else:
        roles.extend(["develop"] * (middle_count - 1))
        roles.append("intensify")
    roles.append("cadence")
    return roles[:length]


def _texture_ceiling_for_grade(grade: int) -> str:
    if grade <= 2:
        return "melody"
    if grade == 3:
        return "chordal"
    return "running"


def _build_style_profile(request: dict[str, Any], preset: dict[str, Any]) -> StyleProfile:
    piano_rules = preset["piano"]
    grade = int(request["grade"])
    focus = str(request.get("readingFocus", "balanced"))
    connection_scale = {
        1: ("arrival", "lead_in", "passing"),
        2: ("arrival", "lead_in", "passing", "neighbor"),
        3: ("arrival", "lead_in", "passing", "neighbor", "echo_fragment", "arpeggiation"),
        4: ("arrival", "lead_in", "passing", "neighbor", "echo_fragment", "sequence", "arpeggiation", "suspension_like"),
        5: ("arrival", "lead_in", "passing", "neighbor", "echo_fragment", "sequence", "arpeggiation", "suspension_like", "cadential_turn", "liquidation"),
    }
    ornaments = tuple(
        ornament
        for ornament in _ORNAMENT_LIBRARY.get(grade, _ORNAMENT_LIBRARY[max(_ORNAMENT_LIBRARY)])
        if request.get("allowAccidentals") or ornament != "chromatic_approach"
    )
    density_floor = 0.18 + max(0, grade - 1) * 0.03
    density_ceiling = 0.52 + max(0, grade - 1) * 0.09
    if focus == "harmonic":
        density_ceiling -= 0.04
    elif focus == "melodic":
        density_ceiling += 0.03
    search_attempts = 22 + max(0, grade - 2) * 6
    if focus == "melodic":
        search_attempts += 4
    if grade >= 5:
        search_attempts += 12
    return StyleProfile(
        grade=grade,
        focus=focus,
        cadence_strength=float(piano_rules.get("cadenceStrictness", 0.85)),
        left_hand_persistence=float(piano_rules.get("leftPatternPersistence", 0.85)),
        register_span=(
            float(_REGISTER_MAPS.get(grade, _REGISTER_MAPS[5])["floor"]),
            float(_REGISTER_MAPS.get(grade, _REGISTER_MAPS[5])["peak"]),
        ),
        texture_ceiling=_texture_ceiling_for_grade(grade),
        allowed_connection_functions=connection_scale.get(grade, connection_scale[max(connection_scale)]),
        allowed_ornament_functions=ornaments,
        accidental_policy="functional" if request.get("allowAccidentals") else "diatonic",
        density_floor=max(0.16, density_floor),
        density_ceiling=min(0.94, density_ceiling),
        search_attempts=search_attempts,
    )


def _assign_phrase_grammars(
    phrases: list[list[int]],
    grade: int,
    focus: str,
    rng: random.Random,
) -> list[PhraseGrammar]:
    """Pre-decide grammatical function and shape for every phrase.

    Classical phrase grammar treats phrases like sentences: an antecedent
    asks a question (open cadence), a consequent answers (closed cadence).
    Continuation phrases develop material, and the closing phrase resolves.
    """
    n = len(phrases)
    grammars: list[PhraseGrammar] = []

    for i, phrase in enumerate(phrases):
        length = len(phrase)

        # --- Phrase function ---
        if n == 1:
            func = "closing"
        elif n == 2:
            func = "antecedent" if i == 0 else "consequent"
        elif n == 3:
            func = ("antecedent", "continuation", "consequent")[i]
        else:
            if i == 0:
                func = "antecedent"
            elif i == n - 1:
                func = "consequent"
            elif i == n - 2:
                func = "continuation"
            else:
                func = "continuation"

        # --- Cadence type ---
        # Antecedent: open cadence (half or deceptive).
        # Consequent/closing: closed cadence (authentic, sometimes plagal).
        # Continuation: weak cadence (half) or none significant.
        if func == "antecedent":
            cadence_type = rng.choices(
                ["half", "deceptive"],
                weights=[0.8, 0.2] if grade >= 4 else [1.0, 0.0],
                k=1,
            )[0]
        elif func in ("consequent", "closing"):
            cadence_type = rng.choices(
                ["authentic", "plagal"],
                weights=[0.82, 0.18] if grade >= 3 else [1.0, 0.0],
                k=1,
            )[0]
        else:  # continuation
            cadence_type = "half"

        # --- Peak position (0.0-1.0 within phrase) ---
        # Antecedent: peak in second half (question builds up).
        # Consequent: peak earlier (answer front-loads energy, then resolves).
        # Continuation: peak late (drives toward next phrase).
        # Closing: peak mid-early, then long resolution.
        if func == "antecedent":
            peak_position = rng.uniform(0.55, 0.75)
        elif func == "consequent":
            peak_position = rng.uniform(0.3, 0.55)
        elif func == "continuation":
            peak_position = rng.uniform(0.6, 0.85)
        else:  # closing
            peak_position = rng.uniform(0.35, 0.5)

        # --- Opening energy ---
        # Antecedent: moderate (sets the scene).
        # Consequent: slightly higher (confident answer).
        # Continuation: matches end of previous phrase.
        # Closing: assertive start, then wind down.
        if func == "antecedent":
            opening_energy = rng.uniform(0.35, 0.50)
        elif func == "consequent":
            opening_energy = rng.uniform(0.45, 0.62)
        elif func == "continuation":
            opening_energy = rng.uniform(0.42, 0.58)
        else:
            opening_energy = rng.uniform(0.48, 0.65)

        # --- Energy profile (per-measure intensity multipliers) ---
        # Build a smooth curve that peaks at peak_position and respects
        # the phrase function's character.
        profile: list[float] = []
        if length == 0:
            profile = [0.5]
        else:
            peak_idx = max(0, min(length - 1, round(peak_position * (length - 1))))
            for j in range(length):
                # Distance from peak, normalized to 0-1
                if length <= 1:
                    t = 0.0
                else:
                    dist = abs(j - peak_idx) / (length - 1)
                    t = 1.0 - dist  # 1.0 at peak, lower further away

                # Shape the curve based on function
                if func == "antecedent":
                    # Gradual build, moderate peak, slight drop at cadence
                    base = opening_energy + t * (0.72 - opening_energy)
                    if j == length - 1:
                        base *= 0.75  # cadence release
                elif func == "consequent":
                    # Front-loaded energy, long resolution tail
                    base = opening_energy + t * (0.68 - opening_energy)
                    # Measures after peak drop more steeply
                    if j > peak_idx:
                        drop = (j - peak_idx) / max(1, length - peak_idx - 1)
                        base *= 1.0 - drop * 0.35
                    if j == length - 1:
                        base *= 0.70  # strong resolution
                elif func == "continuation":
                    # Steady build, high energy throughout
                    base = opening_energy + t * (0.76 - opening_energy)
                    if j == length - 1:
                        base *= 0.82  # softer cadence (drives forward)
                else:  # closing
                    base = opening_energy + t * (0.66 - opening_energy)
                    # Long wind-down in second half
                    if j > peak_idx:
                        drop = (j - peak_idx) / max(1, length - peak_idx - 1)
                        base *= 1.0 - drop * 0.40
                    if j == length - 1:
                        base *= 0.65  # definitive resolution

                profile.append(max(0.18, min(0.92, base)))

        grammars.append(PhraseGrammar(
            phrase_index=i,
            function=func,
            cadence_type=cadence_type,
            peak_position=peak_position,
            opening_energy=opening_energy,
            energy_profile=tuple(profile),
        ))

    return grammars


def _build_piece_plan(
    phrases: list[list[int]],
    request: dict[str, Any],
    style_profile: StyleProfile,
    rng: random.Random,
    *,
    phrase_grammars: list[PhraseGrammar] | None = None,
) -> PiecePlan:
    measure_numbers = [measure for phrase in phrases for measure in phrase]
    if not measure_numbers:
        measure_numbers = [1]
    apex_measure = measure_numbers[min(len(measure_numbers) - 1, max(1, len(measure_numbers) // 2))]
    if style_profile.focus == "melodic":
        apex_measure = measure_numbers[min(len(measure_numbers) - 1, max(1, math.ceil(len(measure_numbers) * 0.66)))]

    # --- Phrase grammar ---
    grade = int(request["grade"])
    if phrase_grammars is None:
        phrase_grammars = _assign_phrase_grammars(phrases, grade, style_profile.focus, rng)

    # --- Cadence map (now driven by grammar) ---
    cadence_map: dict[int, str] = {}
    for pg in phrase_grammars:
        phrase = phrases[pg.phrase_index] if pg.phrase_index < len(phrases) else []
        if not phrase:
            continue
        # Map grammar cadence types to the existing tonic/dominant vocabulary
        # that downstream code understands, while preserving the richer type
        # in the grammar itself.
        if pg.cadence_type in ("authentic", "plagal"):
            cadence_map[phrase[-1]] = "tonic"
        else:
            cadence_map[phrase[-1]] = "dominant"

    # --- Intensity curve (now driven by grammar energy profiles) ---
    intensity_curve: dict[int, float] = {}
    for phrase_index, phrase in enumerate(phrases):
        if not phrase:
            continue
        grammar = phrase_grammars[phrase_index] if phrase_index < len(phrase_grammars) else None
        for local_index, measure_number in enumerate(phrase):
            if grammar and local_index < len(grammar.energy_profile):
                rise = grammar.energy_profile[local_index]
            else:
                rise = 0.5
            # Piece-level apex boost
            if measure_number == apex_measure:
                rise += 0.10
            intensity_curve[measure_number] = max(
                style_profile.density_floor,
                min(style_profile.density_ceiling, rise),
            )

    contrast_measures = tuple(
        measure_number
        for phrase in phrases
        for measure_number in phrase[1:-1]
        if intensity_curve.get(measure_number, 0.0) >= style_profile.density_ceiling - 0.08
    )
    dynamic_arc = "rise-and-release" if style_profile.focus != "harmonic" else "steady-build"
    form_label = _form_label(phrases)
    return PiecePlan(
        phrase_count=len(phrases),
        apex_measure=apex_measure,
        cadence_map=cadence_map,
        intensity_curve=intensity_curve,
        dynamic_arc=dynamic_arc,
        contrast_measures=contrast_measures,
        phrase_grammars=tuple(phrase_grammars),
        summary=f"{form_label}, apex around bar {apex_measure}, {dynamic_arc} arc",
    )


def _pick_answer_form(archetype: str, rng: random.Random) -> str:
    answer_forms = {
        "period": ["echo", "sequence"],
        "sentence": ["sequence", "fragment"],
        "lyric": ["neighbor", "echo"],
        "sequence": ["sequence", "liquidation"],
    }
    return rng.choice(answer_forms.get(archetype, ["echo"]))


def _choose_accompaniment_role(
    phrase_index: int,
    phrase_measures: list[int],
    request: dict[str, Any],
    role_by_measure: dict[int, str],
    rng: random.Random,
) -> str:
    left_pattern = str(request.get("leftHandPattern", "held"))
    if left_pattern == "simple-broken":
        return "broken_support"
    if left_pattern == "repeated":
        return rng.choice(["pulse_support", "anchor"])
    if request.get("readingFocus") == "harmonic":
        return rng.choice(["pulse_support", "arrival_emphasis", "anchor"])
    if any(role_by_measure.get(measure_number) == "intensify" for measure_number in phrase_measures):
        return rng.choice(["broken_support", "pulse_support", "arrival_emphasis"])
    if phrase_index == 0:
        return rng.choice(["anchor", "pulse_support", "broken_support"])
    return rng.choice(["pulse_support", "broken_support", "arrival_emphasis"])


def _available_accompaniment_families(
    role: str,
    request: dict[str, Any],
    preset: dict[str, Any],
) -> list[str]:
    available = list(dict.fromkeys(preset["piano"].get("leftPatternFamilies", ["held"])))
    preferred = _preferred_left_families(request, available)
    preferred_set = set(preferred)
    choices = [
        family
        for family in _ACCOMPANIMENT_ROLE_LIBRARY.get(role, ["held"])
        if family in set(available)
        and (family != "alberti" or bool(preset["piano"].get("allowAlberti", False)))
        and (family != "octave-support" or (bool(preset["piano"].get("allowOctaves", False)) and int(request["grade"]) >= 5))
        and family in preferred_set
    ]
    if choices:
        return choices

    fallback_choices = [
        family
        for family in preferred
        if (family != "alberti" or bool(preset["piano"].get("allowAlberti", False)))
        and (family != "octave-support" or (bool(preset["piano"].get("allowOctaves", False)) and int(request["grade"]) >= 5))
    ]
    return fallback_choices or list(available) or ["held"]


def _build_accompaniment_plan(
    role: str,
    request: dict[str, Any],
    preset: dict[str, Any],
    rng: random.Random,
) -> AccompanimentPlan:
    families = _available_accompaniment_families(role, request, preset)
    cadence_role = "cadence_support" if role != "arrival_emphasis" else "arrival_emphasis"
    cadence_choices = _available_accompaniment_families(cadence_role, request, preset)
    focus = str(request.get("readingFocus", "balanced"))
    weighted_families: list[str] = []
    for family in families:
        weight = 1
        if focus == "melodic" and family in {"support-bass", "repeated", "simple-broken", "arpeggio-support"}:
            weight += 2
        if focus == "harmonic" and family in {"bass-and-chord", "block-half", "block-quarter"}:
            weight += 2
        if int(request.get("grade", 1)) >= 5 and family in {"simple-broken", "arpeggio-support", "waltz-bass"}:
            weight += 1
        weighted_families.extend([family] * max(1, weight))
    return AccompanimentPlan(
        role=role,
        primary_family=rng.choice(weighted_families or families),
        support_families=tuple(families),
        cadence_family=rng.choice(cadence_choices),
    )


def _left_family_cluster(family: str) -> str:
    if family in {"simple-broken", "arpeggio-support", "alberti"}:
        return "broken"
    if family in {"held", "block-half", "block-quarter"}:
        return "block"
    return "bass"


def _cluster_family_pool(
    families: list[str],
    cluster: str,
) -> list[str]:
    return [family for family in families if _left_family_cluster(family) == cluster]


def _left_family_options_for_measure(
    role: str,
    texture: str,
    primary_family: str,
    accompaniment_plan: AccompanimentPlan,
    available_families: list[str],
) -> list[str]:
    support_families = list(dict.fromkeys(accompaniment_plan.support_families or tuple(available_families)))
    cadence_family = accompaniment_plan.cadence_family if accompaniment_plan.cadence_family in available_families else primary_family
    primary_cluster = _left_family_cluster(primary_family)
    primary_pool = _cluster_family_pool(support_families, primary_cluster) or [primary_family]
    broken_pool = _cluster_family_pool(available_families, "broken") or primary_pool
    bass_pool = _cluster_family_pool(available_families, "bass") or primary_pool
    block_pool = _cluster_family_pool(available_families, "block") or primary_pool

    if role == "cadence":
        return list(dict.fromkeys([cadence_family, *block_pool, *bass_pool]))
    if role == "establish":
        return list(dict.fromkeys([primary_family, *primary_pool, *bass_pool]))
    if texture == "running":
        return list(dict.fromkeys([*broken_pool, *bass_pool, primary_family]))
    if texture == "chordal":
        return list(dict.fromkeys([*bass_pool, *broken_pool, *block_pool, primary_family]))
    if role == "answer":
        return list(dict.fromkeys([*bass_pool, *primary_pool, *broken_pool]))
    if role == "intensify":
        return list(dict.fromkeys([*broken_pool, *bass_pool, *block_pool, primary_family]))
    if role == "develop":
        return list(dict.fromkeys([*bass_pool, *broken_pool, *primary_pool, primary_family]))
    return list(dict.fromkeys([*bass_pool, *primary_pool, *broken_pool, primary_family]))


def _build_left_family_plan(
    phrase_measures: list[int],
    role_by_measure: dict[int, str],
    texture_by_measure: dict[int, str],
    request: dict[str, Any],
    preset: dict[str, Any],
    accompaniment_plan: AccompanimentPlan,
    previous_phrase_plan: dict[str, Any] | None,
    rng: random.Random,
    *,
    piece_lh_family: str | None = None,
) -> dict[int, str]:
    available = list(dict.fromkeys(preset["piano"].get("leftPatternFamilies", ["held"])))
    grade = int(request["grade"])

    # Phase 2: lock LH family across the piece (grades 1-3) or phrase (grades 4-5).
    if piece_lh_family is not None:
        locked_family = piece_lh_family
        # For cadence measures at grade 4+, allow the cadence family as a single exception.
        cadence_family = accompaniment_plan.cadence_family
        family_by_measure: dict[int, str] = {}
        for measure_number in phrase_measures:
            role = str(role_by_measure.get(measure_number, "develop"))
            if grade >= 4 and role == "cadence" and cadence_family in available:
                family_by_measure[measure_number] = cadence_family
            else:
                family_by_measure[measure_number] = locked_family
        return family_by_measure

    # --- Original weighted per-measure logic (fallback when piece_lh_family not set) ---
    persistence = float(preset["piano"].get("leftPatternPersistence", 0.85))
    previous_map = dict(previous_phrase_plan.get("_leftFamilyByMeasure") or {}) if previous_phrase_plan else {}
    previous_tail_family = None
    if previous_map:
        previous_tail_family = previous_map.get(max(previous_map))
    elif previous_phrase_plan:
        previous_tail_family = previous_phrase_plan.get("leftFamily")

    primary_family = accompaniment_plan.primary_family if accompaniment_plan.primary_family in available else available[0]
    if previous_tail_family == primary_family:
        primary_pool = _cluster_family_pool(available, _left_family_cluster(primary_family))
        alternate_pool = [family for family in primary_pool if family != previous_tail_family]
        if alternate_pool:
            primary_family = rng.choice(alternate_pool)

    family_by_measure = {}
    previous_family = previous_tail_family
    unique_families: set[str] = set()

    for idx, measure_number in enumerate(phrase_measures):
        role = str(role_by_measure.get(measure_number, "develop"))
        texture = str(texture_by_measure.get(measure_number, "melody"))
        options = _left_family_options_for_measure(
            role,
            texture,
            primary_family,
            accompaniment_plan,
            available,
        )
        if not options:
            options = [primary_family]

        weighted_options: list[str] = []
        for family in options:
            weight = 1
            if family == primary_family:
                weight += 4 if idx == 0 else 2
            if family == accompaniment_plan.cadence_family and role == "cadence":
                weight += 6
            if previous_family and family == previous_family:
                weight += 2 if persistence >= 0.85 and role in {"establish", "answer"} else 0
                weight -= 2 if role in {"answer", "develop", "intensify"} else 0
            if texture == "running" and family in {"simple-broken", "arpeggio-support", "alberti"}:
                weight += 3
            if texture == "melody" and family in {"support-bass", "repeated", "bass-and-chord", "simple-broken", "arpeggio-support"}:
                weight += 2
            if grade >= 5 and texture == "melody" and family in {"bass-and-chord", "simple-broken", "arpeggio-support", "alberti", "octave-support"}:
                weight += 2
            if role == "intensify" and family in {"arpeggio-support", "alberti", "bass-and-chord", "octave-support"}:
                weight += 2
            if role == "answer" and family in {"support-bass", "simple-broken", "repeated", "bass-and-chord"}:
                weight += 2
            if role == "develop" and family in {"simple-broken", "arpeggio-support", "waltz-bass", "support-bass", "bass-and-chord"}:
                weight += 2
            if grade >= 5 and role in {"develop", "intensify"} and family in {"repeated", "held", "block-half"}:
                weight -= 1
            if idx == len(phrase_measures) - 2 and family == accompaniment_plan.cadence_family:
                weight += 2
            if idx == 0 and previous_tail_family and family == previous_tail_family:
                weight -= 2
            weighted_options.extend([family] * max(1, weight))

        chosen = rng.choice(weighted_options or options)
        family_by_measure[measure_number] = chosen
        unique_families.add(chosen)
        previous_family = chosen

    if len(unique_families) < 2 and len(phrase_measures) >= 4:
        preferred_pivots = [
            measure_number
            for measure_number in phrase_measures[1:-1]
            if role_by_measure.get(measure_number) in {"answer", "develop", "intensify"}
        ] or phrase_measures[1:-1]
        if preferred_pivots:
            pivot_measure = preferred_pivots[0]
            role = str(role_by_measure.get(pivot_measure, "answer"))
            texture = str(texture_by_measure.get(pivot_measure, "melody"))
            options = [
                family
                for family in _left_family_options_for_measure(
                    role,
                    texture,
                    primary_family,
                    accompaniment_plan,
                    available,
                )
                if family != family_by_measure[pivot_measure]
            ]
            if options:
                family_by_measure[pivot_measure] = rng.choice(options)

    return family_by_measure


def _register_slot_for_position(
    contour: str,
    relative_position: float,
    style_profile: StyleProfile,
    target_peak_measure: bool,
) -> float:
    register_map = _REGISTER_MAPS.get(style_profile.grade, _REGISTER_MAPS[5])
    floor = float(register_map["floor"])
    center = float(register_map["center"])
    peak = float(register_map["peak"])
    if contour == "ascending":
        slot = floor + (peak - floor) * relative_position
    elif contour == "descending":
        slot = peak - (peak - floor) * relative_position
    elif contour == "arch":
        slope = relative_position * 2 if relative_position <= 0.5 else (1 - relative_position) * 2
        slot = center + (peak - center) * max(0.0, slope)
    elif contour == "valley":
        slope = relative_position * 2 if relative_position <= 0.5 else (1 - relative_position) * 2
        slot = center - (center - floor) * max(0.0, slope)
    else:
        slot = center
    if target_peak_measure:
        slot = max(slot, peak - 0.04)
    return max(style_profile.register_span[0], min(style_profile.register_span[1], slot))


def _anchor_role_for_measure(
    measure_role: str,
    cadence_target: str,
    is_phrase_end: bool,
) -> str:
    if is_phrase_end:
        return "tonic" if cadence_target == "tonic" else cadence_target
    if measure_role == "establish":
        return "root"
    if measure_role == "answer":
        return "third"
    if measure_role == "intensify":
        return "dominant"
    return "stable"


def _choose_connection_name(
    archetype: str,
    measure_role: str,
    cadence_target: str,
    style_profile: StyleProfile,
    request: dict[str, Any],
    rng: random.Random,
) -> str:
    choices = list(_CONNECTION_LIBRARY.get(archetype, _CONNECTION_LIBRARY["period"]).get(measure_role, ["passing"]))
    if measure_role == "cadence":
        cadence_entry = _CADENCE_LIBRARY.get(request["timeSignature"], _CADENCE_LIBRARY["4/4"]).get(cadence_target)
        if cadence_entry:
            choices = [str(cadence_entry["connection"]), *choices]
    filtered = [choice for choice in choices if choice in set(style_profile.allowed_connection_functions)]
    return rng.choice(filtered or list(style_profile.allowed_connection_functions))


def _top_pitch_role_for_measure(
    measure_role: str,
    cadence_target: str,
    *,
    is_phrase_end: bool,
    answer_form: str,
    focus: str,
    phrase_index: int,
    measure_index: int,
    grade: int,
) -> str:
    if is_phrase_end:
        return "tonic" if cadence_target == "tonic" else cadence_target
    if measure_role == "establish":
        if grade <= 2 and measure_index == 0:
            return "opening"
        if grade <= 2:
            return "third" if phrase_index == 0 or focus != "harmonic" else "root"
        return "third" if focus == "melodic" else "root"
    if measure_role == "answer":
        return "fifth" if answer_form == "sequence" else "third"
    if measure_role == "intensify":
        return "dominant"
    if measure_role == "cadence":
        return "tonic" if cadence_target == "tonic" else "dominant"
    return "stable"


def _top_motion_role_for_measure(measure_role: str, contour: str) -> str:
    if measure_role == "cadence":
        return "cadence"
    if measure_role == "intensify":
        return "push"
    if contour in {"ascending", "arch"}:
        return "rise"
    if contour == "descending":
        return "release"
    return "step"


def _bass_pitch_role_for_measure(
    measure_index: int,
    measure_role: str,
    cadence_target: str,
    *,
    is_phrase_end: bool,
    phrase_index: int,
) -> str:
    if is_phrase_end:
        return "tonic" if cadence_target == "tonic" else "dominant"
    if measure_role == "establish":
        if phrase_index == 0:
            return "root"
        return "third" if phrase_index % 2 else "fifth"
    if measure_role == "answer":
        return "fifth" if (measure_index + phrase_index) % 2 == 0 else "third"
    if measure_role == "develop":
        return "third" if (measure_index + phrase_index) % 3 == 1 else "fifth"
    if measure_role == "intensify":
        return "dominant" if (measure_index + phrase_index) % 2 == 0 else "fifth"
    return "root"


def _bass_motion_role_for_measure(measure_role: str, measure_index: int) -> str:
    if measure_role == "cadence":
        return "cadence"
    if measure_role == "intensify":
        return "leap"
    if measure_role in {"answer", "develop"}:
        return "step"
    if measure_index == 0:
        return "hold"
    return "step"


def _build_top_line_plan(
    phrase_index: int,
    phrase_measures: list[int],
    role_by_measure: dict[int, str],
    contour: str,
    cadence_target: str,
    answer_form: str,
    style_profile: StyleProfile,
    piece_plan: PiecePlan,
) -> TopLinePlan:
    register_targets: dict[int, float] = {}
    pitch_roles: dict[int, str] = {}
    motion_roles: dict[int, str] = {}
    peak_measure = phrase_measures[min(len(phrase_measures) - 1, len(phrase_measures) // 2)]
    if contour == "ascending":
        peak_measure = phrase_measures[-1]
    elif contour == "descending":
        peak_measure = phrase_measures[0]
    elif piece_plan.apex_measure in phrase_measures:
        peak_measure = piece_plan.apex_measure

    for index, measure_number in enumerate(phrase_measures):
        position = index / max(1, len(phrase_measures) - 1) if len(phrase_measures) > 1 else 0.5
        register_slot = _register_slot_for_position(
            contour,
            position,
            style_profile,
            measure_number == peak_measure,
        )
        register_targets[measure_number] = max(
            style_profile.register_span[0],
            min(style_profile.register_span[1], register_slot + 0.08),
        )
        measure_role = role_by_measure.get(measure_number, "develop")
        if style_profile.grade <= 2 and measure_role == "establish" and index == 0:
            register_targets[measure_number] = max(
                register_targets[measure_number],
                0.88 if phrase_index == 0 else 0.8,
            )
        elif style_profile.grade <= 2 and measure_number == peak_measure:
            register_targets[measure_number] = max(
                register_targets[measure_number],
                0.84 if phrase_index == 0 else 0.76,
            )
        pitch_roles[measure_number] = _top_pitch_role_for_measure(
            measure_role,
            cadence_target,
            is_phrase_end=measure_number == phrase_measures[-1],
            answer_form=answer_form,
            focus=style_profile.focus,
            phrase_index=phrase_index,
            measure_index=index,
            grade=style_profile.grade,
        )
        motion_roles[measure_number] = _top_motion_role_for_measure(measure_role, contour)

    return TopLinePlan(
        phrase_index=phrase_index,
        peak_measure=peak_measure,
        register_targets=register_targets,
        pitch_roles=pitch_roles,
        motion_roles=motion_roles,
    )


def _build_bass_line_plan(
    phrase_index: int,
    phrase_measures: list[int],
    role_by_measure: dict[int, str],
    cadence_target: str,
    style_profile: StyleProfile,
) -> BassLinePlan:
    register_targets: dict[int, float] = {}
    pitch_roles: dict[int, str] = {}
    motion_roles: dict[int, str] = {}
    low_span = max(0.02, style_profile.register_span[0] * 0.55)
    high_span = max(low_span + 0.06, style_profile.register_span[0] + 0.12)

    for index, measure_number in enumerate(phrase_measures):
        measure_role = role_by_measure.get(measure_number, "develop")
        position = index / max(1, len(phrase_measures) - 1) if len(phrase_measures) > 1 else 0.5
        register_targets[measure_number] = max(
            0.02,
            min(0.28, low_span + (high_span - low_span) * position),
        )
        pitch_roles[measure_number] = _bass_pitch_role_for_measure(
            index,
            measure_role,
            cadence_target,
            is_phrase_end=measure_number == phrase_measures[-1],
            phrase_index=phrase_index,
        )
        motion_roles[measure_number] = _bass_motion_role_for_measure(measure_role, index)

    return BassLinePlan(
        phrase_index=phrase_index,
        cadence_measure=phrase_measures[-1],
        register_targets=register_targets,
        pitch_roles=pitch_roles,
        motion_roles=motion_roles,
    )


def _resolve_top_line_target(
    plan: TopLinePlan | None,
    measure_number: int,
    pool: list[int],
    harmony_tones: list[int],
    key_signature: str,
    harmony: str,
    reference_pitch: int,
) -> int | None:
    if plan is None or measure_number not in plan.pitch_roles:
        return None
    candidates = _pitch_role_candidates(
        pool,
        harmony_tones,
        key_signature,
        harmony,
        plan.pitch_roles[measure_number],
    )
    desired_set = {int(pitch_value) for pitch_value in candidates}
    preferred = [
        pitch_value for pitch_value in candidates
        if _nearest_pool_index(pool, pitch_value) >= max(0, len(pool) // 2 - 1)
    ] or candidates
    preferred_set = {int(pitch_value) for pitch_value in preferred}
    target_index = _relative_slot_to_index(plan.register_targets.get(measure_number, 0.7), len(pool))
    motion_role = plan.motion_roles.get(measure_number, "step")

    def _score(pitch_value: int) -> float:
        pool_index = _nearest_pool_index(pool, pitch_value)
        interval = abs(pitch_value - reference_pitch)
        interval_penalty = interval * 0.05
        if motion_role in {"rise", "push"} and pitch_value <= reference_pitch:
            interval_penalty += 0.55
        elif motion_role == "release" and pitch_value >= reference_pitch:
            interval_penalty += 0.55
        elif motion_role == "cadence":
            interval_penalty += interval * 0.02
        elif motion_role == "step" and pitch_value == reference_pitch:
            interval_penalty += 0.25
        repeat_penalty = 0.7 if pitch_value == reference_pitch else 0.0
        role_penalty = 0.0 if pitch_value in desired_set else (0.9 if motion_role == "cadence" else 0.38)
        register_penalty = 0.0 if pitch_value in preferred_set else 0.22
        return abs(pool_index - target_index) * 0.9 + interval_penalty + repeat_penalty + role_penalty + register_penalty

    return min(pool, key=_score)


def _resolve_bass_line_target(
    plan: BassLinePlan | None,
    measure_number: int,
    pool: list[int],
    harmony_tones: list[int],
    key_signature: str,
    harmony: str,
    reference_pitch: int | None,
) -> int | None:
    if plan is None or measure_number not in plan.pitch_roles:
        return None
    candidates = _pitch_role_candidates(
        pool,
        harmony_tones,
        key_signature,
        harmony,
        plan.pitch_roles[measure_number],
    )
    desired_set = {int(pitch_value) for pitch_value in candidates}
    preferred = [
        pitch_value for pitch_value in candidates
        if _nearest_pool_index(pool, pitch_value) <= max(1, len(pool) // 2)
    ] or candidates
    preferred_set = {int(pitch_value) for pitch_value in preferred}
    target_index = _relative_slot_to_index(plan.register_targets.get(measure_number, 0.15), len(pool))
    motion_role = plan.motion_roles.get(measure_number, "step")

    def _score(pitch_value: int) -> float:
        pool_index = _nearest_pool_index(pool, pitch_value)
        interval_penalty = 0.0
        if reference_pitch is not None:
            interval = abs(pitch_value - reference_pitch)
            if motion_role == "hold":
                interval_penalty = interval * 0.10
            elif motion_role == "step":
                if interval == 0:
                    interval_penalty = 0.75
                elif interval <= 5:
                    interval_penalty = abs(interval - 2.5) * 0.08
                else:
                    interval_penalty = 0.55 + (interval - 5) * 0.1
            elif motion_role == "leap":
                if interval == 0:
                    interval_penalty = 0.85
                elif interval < 3:
                    interval_penalty = 0.45 + (3 - interval) * 0.18
                else:
                    interval_penalty = abs(interval - 5.5) * 0.05
            else:
                interval_penalty = interval * 0.04
            if pitch_value == reference_pitch and motion_role != "hold":
                interval_penalty += 0.45
        role_penalty = 0.0 if pitch_value in desired_set else (0.85 if motion_role == "cadence" else 0.32)
        register_penalty = 0.0 if pitch_value in preferred_set else 0.18
        return abs(pool_index - target_index) * 0.9 + interval_penalty + role_penalty + register_penalty

    return min(pool, key=_score)


def _choose_ornament_name(
    measure_role: str,
    style_profile: StyleProfile,
    request: dict[str, Any],
    rng: random.Random,
) -> str:
    choices = list(style_profile.allowed_ornament_functions)
    if measure_role == "cadence" and "arrival" in choices:
        return "arrival"
    if measure_role in {"establish", "answer"} and "none" in choices and rng.random() < 0.45:
        return "none"
    if request.get("allowAccidentals") and "chromatic_approach" in choices and measure_role in {"develop", "intensify"} and rng.random() < 0.25:
        return "chromatic_approach"
    return rng.choice(choices or ["none"])


def _build_line_plan(
    phrase_index: int,
    phrase_measures: list[int],
    role_by_measure: dict[int, str],
    contour: str,
    archetype: str,
    cadence_target: str,
    style_profile: StyleProfile,
    piece_plan: PiecePlan,
    request: dict[str, Any],
    rng: random.Random,
) -> LinePlan:
    anchors: list[AnchorTone] = []
    connections: dict[int, ConnectionFunction] = {}
    ornaments: dict[int, OrnamentFunction] = {}
    trajectory: dict[int, float] = {}
    climax_measure = phrase_measures[min(len(phrase_measures) - 1, len(phrase_measures) // 2)]
    if contour == "ascending":
        climax_measure = phrase_measures[-1]
    elif contour == "descending":
        climax_measure = phrase_measures[0]
    elif piece_plan.apex_measure in phrase_measures:
        climax_measure = piece_plan.apex_measure

    for index, measure_number in enumerate(phrase_measures):
        position = index / max(1, len(phrase_measures) - 1) if len(phrase_measures) > 1 else 0.5
        measure_role = role_by_measure.get(measure_number, "develop")
        register_slot = _register_slot_for_position(
            contour,
            position,
            style_profile,
            measure_number == climax_measure,
        )
        trajectory[measure_number] = register_slot
        anchors.append(
            AnchorTone(
                measure=measure_number,
                beat=0.0,
                pitch_role=_anchor_role_for_measure(
                    measure_role,
                    cadence_target,
                    measure_number == phrase_measures[-1],
                ),
                register_slot=register_slot,
                local_goal=measure_role,
            )
        )
        connection_name = _choose_connection_name(
            archetype,
            measure_role,
            cadence_target,
            style_profile,
            request,
            rng,
        )
        if phrase_index > 0 and index == 0:
            if measure_role == "answer":
                if "sequence" in set(style_profile.allowed_connection_functions):
                    connection_name = "sequence"
                elif "echo_fragment" in set(style_profile.allowed_connection_functions):
                    connection_name = "echo_fragment"
            elif measure_role == "develop":
                if "passing" in set(style_profile.allowed_connection_functions):
                    connection_name = "passing"
        elif phrase_index > 0 and measure_role == "develop" and connection_name in {"arrival", "lead_in"}:
            if "arpeggiation" in set(style_profile.allowed_connection_functions):
                connection_name = "arpeggiation"
            elif "sequence" in set(style_profile.allowed_connection_functions):
                connection_name = "sequence"
        connections[measure_number] = ConnectionFunction(
            name=connection_name,
            role=measure_role,
            intensity=piece_plan.intensity_curve.get(measure_number, style_profile.density_floor),
        )
        ornament_name = _choose_ornament_name(measure_role, style_profile, request, rng)
        if phrase_index > 0 and index == 0 and ornament_name == "none":
            if "passing" in set(style_profile.allowed_ornament_functions):
                ornament_name = "passing"
        ornaments[measure_number] = OrnamentFunction(
            name=ornament_name,
            placement="pre_anchor" if ornament_name in {"passing", "chromatic_approach", "neighbor"} else "arrival",
        )

    return LinePlan(
        phrase_index=phrase_index,
        climax_measure=climax_measure,
        register_trajectory=trajectory,
        anchors=tuple(anchors),
        connections=connections,
        ornaments=ornaments,
    )


def _simple_rhythm_cells(allowed_durations: list[float]) -> list[list[float]]:
    allowed = set(allowed_durations)
    simple = [cell for cell in _RHYTHM_CELLS_SIMPLE if all(d in allowed for d in cell)]
    if simple:
        return simple
    longer = [d for d in allowed_durations if d >= 1.0]
    if longer:
        return [[max(longer)]]
    return [[max(allowed_durations)]]


def _scaled_density_target(
    base: float,
    grade: int,
    role: str,
    request: dict[str, Any],
) -> float:
    bonus = max(0, grade - 1) * 0.06
    if request.get("readingFocus") == "harmonic" and role in {"answer", "develop", "intensify"}:
        bonus += 0.03
    if request.get("readingFocus") == "melodic" and role in {"develop", "intensify"}:
        bonus += 0.02
    if role == "cadence":
        bonus *= 0.5
    return max(0.18, min(0.95, base + bonus))


def _choose_phrase_textures(
    phrase_measures: list[int],
    role_by_measure: dict[int, str],
    request: dict[str, Any],
    preset: dict[str, Any],
    rng: random.Random,
) -> dict[int, str]:
    piano_rules = preset["piano"]
    base_weights = dict(piano_rules.get("textureWeights", {"melody": 1.0, "chordal": 0.0, "running": 0.0}))
    grade = int(request["grade"])
    focus = str(request.get("readingFocus", "balanced"))

    if grade < 4:
        return {measure_number: "melody" for measure_number in phrase_measures}

    primary_weights = {
        "melody": max(0.01, float(base_weights.get("melody", 1.0))) * (
            1.22 if focus == "harmonic" else (1.32 if focus == "melodic" else 1.16)
        ),
        "chordal": max(0.01, float(base_weights.get("chordal", 0.0))) * (
            1.35 if focus == "harmonic" else (1.0 if focus == "melodic" else 1.08)
        ),
    }
    if request.get("coordinationStyle") == "together":
        primary_weights["chordal"] *= 1.18

    primary_texture = rng.choices(
        ["melody", "chordal"],
        weights=[primary_weights["melody"], primary_weights["chordal"]],
        k=1,
    )[0]
    if focus == "harmonic" and len(phrase_measures) <= 4 and grade < 5:
        primary_texture = "melody"

    texture_by_measure = {measure_number: primary_texture for measure_number in phrase_measures}

    # Cadences should resolve simply; never end a phrase with a running bar.
    cadence_measure = phrase_measures[-1]
    if primary_texture == "chordal" and focus == "harmonic" and rng.random() < 0.25:
        texture_by_measure[cadence_measure] = "chordal"
    else:
        texture_by_measure[cadence_measure] = "melody"

    if phrase_measures:
        texture_by_measure[phrase_measures[0]] = "melody"

    contrast_candidates = [
        measure_number
        for measure_number in phrase_measures
        if measure_number not in {phrase_measures[0], cadence_measure}
        and role_by_measure.get(measure_number) in {"answer", "develop", "intensify"}
    ]
    intensify_candidates = [
        measure_number for measure_number in contrast_candidates
        if role_by_measure.get(measure_number) == "intensify"
    ]

    should_add_contrast = len(phrase_measures) >= 3 and (
        rng.random() < (0.68 if grade == 4 else 0.86)
    )

    if should_add_contrast and contrast_candidates:
        contrast_measure = rng.choice(intensify_candidates or contrast_candidates)
        if focus == "harmonic":
            contrast_texture = "chordal" if primary_texture == "melody" else "melody"
        else:
            allow_running = grade >= 5 and role_by_measure.get(contrast_measure) == "intensify"
            if allow_running and rng.random() < 0.58:
                contrast_texture = "running"
            else:
                contrast_texture = "chordal" if primary_texture == "melody" else "melody"
        texture_by_measure[contrast_measure] = contrast_texture

    # Rare second contrast for longer Grade 5 phrases, but keep it adjacent to the first idea.
    if grade >= 5 and len(phrase_measures) >= 4 and rng.random() < 0.4:
        current_contrasts = [
            measure_number for measure_number, texture in texture_by_measure.items()
            if texture != primary_texture and measure_number != cadence_measure
        ]
        if current_contrasts:
            base_measure = current_contrasts[0]
            neighbor_measures = [
                measure_number for measure_number in contrast_candidates
                if measure_number != base_measure and abs(measure_number - base_measure) == 1
            ]
            if neighbor_measures:
                neighbor_measure = rng.choice(neighbor_measures)
                texture_by_measure[neighbor_measure] = texture_by_measure[base_measure]

    if grade >= 5 and "running" not in texture_by_measure.values():
        running_candidates = [
            measure_number
            for measure_number in contrast_candidates
            if role_by_measure.get(measure_number) in {"develop", "intensify"}
            and measure_number != cadence_measure
        ]
        running_bias = max(0.18, min(0.6, float(base_weights.get("running", 0.0)) * 1.8))
        if running_candidates and rng.random() < running_bias:
            running_measure = rng.choice(intensify_candidates or running_candidates)
            texture_by_measure[running_measure] = "running"

    return texture_by_measure


def _choose_phrase_left_family(
    request: dict[str, Any],
    preset: dict[str, Any],
    rng: random.Random,
) -> str:
    piano_rules = preset["piano"]
    families = list(piano_rules.get("leftPatternFamilies", ["held"]))
    families = _preferred_left_families(request, families)
    grade = int(request["grade"])
    meter = str(request.get("timeSignature", "4/4"))
    focus = str(request.get("readingFocus", "balanced"))
    preferred_families = set(families)

    if grade < 4:
        weighted = [
            family
            for family in families
            for _ in range(4 if family in preferred_families else 1)
        ]
        return rng.choice(weighted or families)

    weighted_families: list[str] = []
    for family in families:
        weight = 1
        if family in {"block-half", "bass-and-chord", "support-bass"}:
            weight = 5
        elif family in {"block-quarter", "simple-broken", "arpeggio-support"}:
            weight = 3
        elif family == "alberti":
            weight = 3 if bool(piano_rules.get("allowAlberti", False)) else 0
        elif family == "octave-support":
            weight = 3 if bool(piano_rules.get("allowOctaves", False)) and grade >= 5 else 0
        elif family == "waltz-bass":
            weight = 3 if meter.startswith("3/") else 0

        if focus == "harmonic" and family in {"block-half", "bass-and-chord", "block-quarter"}:
            weight += 1
        if focus == "melodic" and family in {"support-bass", "simple-broken", "arpeggio-support", "alberti"}:
            weight += 2
        if grade >= 5 and family in {"arpeggio-support", "alberti", "octave-support"}:
            weight += 1
        if family in preferred_families:
            weight += 4

        weighted_families.extend([family] * max(0, weight))

    return rng.choice(weighted_families or families or ["held"])


def _group_into_phrases(
    measure_count: int,
    allowed_lengths: list[int],
    rng: random.Random,
) -> list[list[int]]:
    del allowed_lengths, rng
    return _phrase_form_template(measure_count)


def _pick_phrase_plan(
    phrase_index: int,
    phrase_measures: list[int],
    request: dict[str, Any],
    preset: dict[str, Any],
    style_profile: StyleProfile,
    piece_plan: PiecePlan,
    previous_phrase_plan: dict[str, Any] | None,
    rng: random.Random,
    *,
    piece_rhythm_cells: dict[str, list[list[float]]] | None = None,
    piece_lh_family: str | None = None,
    piece_archetype: str | None = None,
    piece_contour: str | None = None,
    phrase_grammar: PhraseGrammar | None = None,
) -> dict[str, Any]:
    piano_rules = preset["piano"]
    accidental_roles = list(piano_rules.get("accidentalRoles", []))
    cadence_target = piece_plan.cadence_map.get(phrase_measures[-1], "tonic")

    # Use piece-level rhythm cells if provided (Phase 1: piece-level rhythm identity)
    allowed_durs = sorted({float(v) for v in piano_rules["rightQuarterLengths"]}, reverse=True)
    lh_allowed = sorted(
        {float(v) for v in piano_rules.get("leftQuarterLengths", piano_rules["rightQuarterLengths"])},
        reverse=True,
    )
    if piece_rhythm_cells is not None:
        rh_cells = list(piece_rhythm_cells["rh"])
        lh_cells = list(piece_rhythm_cells["lh"])
    else:
        rh_cells = _pick_rhythm_cells(int(request["grade"]), allowed_durs, rng)
        lh_cells = _pick_rhythm_cells(int(request["grade"]), lh_allowed, rng)

    # Phase 6: derive contour deterministically from piece-level contour.
    # Phrase A and A' share the same contour; B/close get the complement.
    _CONTOUR_COMPLEMENT = {
        "ascending": "descending", "descending": "ascending",
        "arch": "valley", "valley": "arch", "flat": "flat",
    }
    if piece_contour is not None:
        if phrase_index == 0:
            contour = piece_contour
        elif phrase_index == 1:
            contour = piece_contour  # A' = same as A
        else:
            contour = _CONTOUR_COMPLEMENT.get(piece_contour, piece_contour)  # B = complement
        inherit_contour = phrase_index > 0
    else:
        source_contour = str(previous_phrase_plan.get("_contour", "flat")) if previous_phrase_plan else "flat"
        inherit_contour = bool(previous_phrase_plan and rng.random() < 0.72)
        contour = _related_contour(source_contour, rng) if inherit_contour else _pick_contour(rng)
    measure_roles = _measure_role_sequence(len(phrase_measures))
    role_by_measure = {
        measure_number: role for measure_number, role in zip(phrase_measures, measure_roles, strict=False)
    }
    if phrase_index > 0 and phrase_measures:
        role_by_measure[phrase_measures[0]] = "answer"
        if len(phrase_measures) >= 4:
            role_by_measure[phrase_measures[1]] = "develop"

    # --- Phrase grammar overrides ---
    # Grammar function shapes which measure gets the intensify role and how
    # the phrase opens.  This makes consequent phrases feel like answers and
    # continuation phrases feel like bridges.
    if phrase_grammar is not None and len(phrase_measures) >= 3:
        peak_idx = max(0, min(len(phrase_measures) - 2,
                              round(phrase_grammar.peak_position * (len(phrase_measures) - 1))))
        # Move the "intensify" role to the grammar-determined peak.
        # Only override interior measures (never first or last).
        if 0 < peak_idx < len(phrase_measures) - 1:
            # Clear any existing intensify
            for mn, rl in role_by_measure.items():
                if rl == "intensify":
                    role_by_measure[mn] = "develop"
            role_by_measure[phrase_measures[peak_idx]] = "intensify"

        # Consequent phrases start more assertively — mark first measure
        # as "establish" (not "answer") so melody restates with authority.
        if phrase_grammar.function == "consequent" and phrase_index > 0:
            role_by_measure[phrase_measures[0]] = "establish"
            if len(phrase_measures) >= 4:
                role_by_measure[phrase_measures[1]] = "answer"

    density_targets = {
        measure_number: max(
            style_profile.density_floor,
            min(
                style_profile.density_ceiling,
                (
                    _scaled_density_target(
                        _ROLE_DENSITY_TARGETS.get(role, 0.5),
                        int(request["grade"]),
                        role,
                        request,
                    )
                    * 0.6
                )
                + (piece_plan.intensity_curve.get(measure_number, 0.5) * 0.4),
            ),
        )
        for measure_number, role in role_by_measure.items()
    }
    texture_by_measure = _choose_phrase_textures(
        phrase_measures,
        role_by_measure,
        request,
        preset,
        rng,
    )
    if phrase_index == 0 and phrase_measures:
        for measure_number in phrase_measures[:2]:
            texture_by_measure[measure_number] = "melody"
        texture_by_measure[phrase_measures[-1]] = "melody"
        for measure_number in phrase_measures[2:-1]:
            if texture_by_measure.get(measure_number) == "chordal":
                texture_by_measure[measure_number] = (
                    "running"
                    if int(request["grade"]) >= 5
                    and role_by_measure.get(measure_number) == "intensify"
                    and rng.random() < 0.32
                    else "melody"
                )
    elif previous_phrase_plan and phrase_measures:
        texture_by_measure[phrase_measures[0]] = "melody"
    accompaniment_role = _choose_accompaniment_role(
        phrase_index,
        phrase_measures,
        request,
        role_by_measure,
        rng,
    )
    accompaniment_plan = _build_accompaniment_plan(
        accompaniment_role,
        request,
        preset,
        rng,
    )
    left_family = accompaniment_plan.primary_family
    # Phase 6: use piece-level archetype when available.
    if piece_archetype is not None:
        phrase_archetype = piece_archetype
    else:
        phrase_archetype = _choose_phrase_archetype(
            phrase_measures,
            role_by_measure,
            texture_by_measure,
            request,
            rng,
        )
    line_plan = _build_line_plan(
        phrase_index,
        phrase_measures,
        role_by_measure,
        contour,
        phrase_archetype,
        cadence_target,
        style_profile,
        piece_plan,
        request,
        rng,
    )
    answer_form = _pick_answer_form(phrase_archetype, rng)
    top_line_plan = _build_top_line_plan(
        phrase_index,
        phrase_measures,
        role_by_measure,
        contour,
        cadence_target,
        answer_form,
        style_profile,
        piece_plan,
    )
    bass_line_plan = _build_bass_line_plan(
        phrase_index,
        phrase_measures,
        role_by_measure,
        cadence_target,
        style_profile,
    )

    source_motive_blueprint = dict(previous_phrase_plan.get("_motiveBlueprint") or {}) if previous_phrase_plan else {}

    # Anchor and answer cells are drawn from the piece-level pool (locked across phrases).
    # When piece_rhythm_cells is active, every phrase shares the same palette so
    # inherit_rhythm is always True by construction.
    inherit_rhythm = piece_rhythm_cells is not None or bool(
        previous_phrase_plan
        and (previous_phrase_plan.get("_anchorCell") or previous_phrase_plan.get("_answerCell"))
        and rng.random() < 0.82
    )
    if piece_rhythm_cells is not None:
        # Deterministic: first cell is the anchor, second is the answer — locked for the piece.
        anchor_cell = list(rh_cells[0] if rh_cells else [1.0])
        answer_cell = list(rh_cells[1] if len(rh_cells) > 1 else anchor_cell)
    else:
        source_anchor_cell = list(previous_phrase_plan.get("_anchorCell") or []) if previous_phrase_plan else []
        source_answer_cell = list(previous_phrase_plan.get("_answerCell") or []) if previous_phrase_plan else []
        anchor_cell = list(rng.choice(rh_cells) if rh_cells else [1.0])
        answer_pool = [cell for cell in rh_cells if cell != anchor_cell]
        answer_cell = list(rng.choice(answer_pool or rh_cells or [anchor_cell]))
        if inherit_rhythm:
            anchor_cell = list(source_answer_cell or source_anchor_cell or anchor_cell)
            answer_cell = list(source_anchor_cell or source_answer_cell or answer_cell)

    cadence_cells = _simple_rhythm_cells(allowed_durs)

    triplet_measures: list[int] = []
    if (
        float(piano_rules.get("tripletChance", 0.0)) > 0
        and request["grade"] >= 4
        and len(phrase_measures) >= 3
    ):
        eligible_triplet_measures = [
            measure_number
            for measure_number, role in role_by_measure.items()
            if role in {"develop", "intensify"}
            and texture_by_measure.get(measure_number, "melody") != "chordal"
        ]
        if eligible_triplet_measures:
            running_triplet_measures = [
                measure_number
                for measure_number in eligible_triplet_measures
                if texture_by_measure.get(measure_number, "melody") == "running"
            ]
            if running_triplet_measures:
                eligible_triplet_measures = running_triplet_measures
            eligible_triplet_measures.sort(
                key=lambda measure_number: (
                    0 if texture_by_measure.get(measure_number, "melody") == "running" else 1,
                    0 if role_by_measure.get(measure_number) == "intensify" else 1,
                    measure_number,
                )
            )
            triplet_count = 1
            if (
                len(eligible_triplet_measures) > 1
                and request["grade"] >= 5
                and int(request["measureCount"]) >= 12
                and rng.random() < 0.25
            ):
                triplet_count = 2
            triplet_measures = eligible_triplet_measures[: min(triplet_count, len(eligible_triplet_measures))]

    # Determine peak measure from grammar when available, else from contour.
    if phrase_grammar is not None and phrase_measures:
        peak_idx = max(0, min(len(phrase_measures) - 1,
                              round(phrase_grammar.peak_position * (len(phrase_measures) - 1))))
        target_peak_measure = phrase_measures[peak_idx]
    else:
        target_peak_measure = phrase_measures[len(phrase_measures) // 2]
        if contour == "ascending":
            target_peak_measure = phrase_measures[-1]
        elif contour == "descending":
            target_peak_measure = phrase_measures[0]
        elif contour == "valley":
            target_peak_measure = phrase_measures[0]

    rhythm_cells_by_role = {
        "establish": [anchor_cell, anchor_cell, answer_cell],
        "answer": [anchor_cell, answer_cell, answer_cell],
        "develop": rh_cells + [answer_cell],
        "intensify": rh_cells + [answer_cell, answer_cell],
        "cadence": cadence_cells + [anchor_cell],
    }
    motive_blueprint = _build_motive_blueprint(
        anchor_cell,
        answer_cell,
        allowed_durs,
        contour,
        phrase_measures,
        role_by_measure,
        texture_by_measure,
        source_motive_blueprint,
        inherit_rhythm,
        inherit_contour,
        rng,
        measure_total=_measure_total(request["timeSignature"]),
    )
    continuation_by_measure = _build_continuation_plan(
        phrase_archetype,
        phrase_measures,
        role_by_measure,
        texture_by_measure,
        cadence_target,
        motive_blueprint,
        rng,
    )
    melody_measures = [measure_number for measure_number in phrase_measures if texture_by_measure.get(measure_number) == "melody"]
    if phrase_index == 0:
        force_motif_measures = tuple(melody_measures)
    elif previous_phrase_plan:
        force_motif_measures = tuple(dict.fromkeys([*melody_measures[:2], *melody_measures[-1:]]))
    else:
        force_motif_measures = tuple(melody_measures[:1])
    # Use grammar function as phrase_role when available.
    if phrase_grammar is not None:
        phrase_role = phrase_grammar.function
    else:
        phrase_role = "opening" if phrase_index == 0 else (
            "closing" if phrase_measures[-1] == int(request["measureCount"]) else "continuation"
        )
    phrase_blueprint = PhraseBlueprint(
        phrase_index=phrase_index,
        measures=tuple(phrase_measures),
        archetype=phrase_archetype,
        phrase_role=phrase_role,
        cadence_target=cadence_target,
        primary_motive={
            "durations": motive_blueprint["durations"],
            "steps": motive_blueprint["steps"],
        },
        answer_form=answer_form,
        accompaniment_role=accompaniment_plan.role,
        line_plan=line_plan,
        top_line_plan=top_line_plan,
        bass_line_plan=bass_line_plan,
    )
    left_family_by_measure = _build_left_family_plan(
        phrase_measures,
        role_by_measure,
        texture_by_measure,
        request,
        preset,
        accompaniment_plan,
        previous_phrase_plan,
        rng,
        piece_lh_family=piece_lh_family,
    )
    left_family = (
        left_family_by_measure.get(phrase_measures[0], accompaniment_plan.primary_family)
        if phrase_measures
        else accompaniment_plan.primary_family
    )

    return {
        "phraseIndex": phrase_index,
        "measures": phrase_measures,
        "length": len(phrase_measures),
        "cadenceTarget": cadence_target,
        "leftFamily": left_family,
        "accompanimentRole": accompaniment_plan.role,
        "archetype": phrase_archetype,
        "accidentalRoles": accidental_roles,
        "_rhythmCells": rh_cells,
        "_lhRhythmCells": lh_cells,
        "_contour": contour,
        "_measureRoles": role_by_measure,
        "_densityTargets": density_targets,
        "_textureByMeasure": texture_by_measure,
        "_tripletMeasures": triplet_measures,
        "_targetPeakMeasure": target_peak_measure,
        "_anchorCell": anchor_cell,
        "_answerCell": answer_cell,
        "_inheritContour": inherit_contour,
        "_inheritRhythm": inherit_rhythm,
        "_inheritsFromPhraseIndex": previous_phrase_plan.get("phraseIndex") if previous_phrase_plan else None,
        "_cadenceCells": cadence_cells,
        "_roleRhythmCells": rhythm_cells_by_role,
        "_motiveBlueprint": motive_blueprint,
        "_forceMotifMeasures": force_motif_measures,
        "_continuationByMeasure": continuation_by_measure,
        "_styleProfile": style_profile,
        "_piecePlan": piece_plan,
        "_linePlan": line_plan,
        "_topLinePlan": top_line_plan,
        "_bassLinePlan": bass_line_plan,
        "_accompanimentPlan": accompaniment_plan,
        "_leftFamilyByMeasure": left_family_by_measure,
        "_phraseBlueprint": phrase_blueprint,
        "_answerForm": answer_form,
        "_phraseGrammar": phrase_grammar,
    }

"""Harmonic planning for sheet music generation.

Provides progression banks (major and minor, weak and strong cadences) and the
functions that build a per-measure harmony plan from those banks, respecting
phrase structure and optional phrase-grammar annotations.
"""
from __future__ import annotations

import random

from ..config import is_minor_key
from ._types import PhraseGrammar

# ---------------------------------------------------------------------------
# Harmonic plan
# ---------------------------------------------------------------------------

_MAJOR_PROGRESSIONS: dict[int, list[list[str]]] = {
    1: [
        ["I", "V", "I", "I"],
        ["I", "I", "V", "I"],
        ["I", "IV", "I", "I"],
        ["I", "V", "V", "I"],
    ],
    2: [
        ["I", "IV", "V", "I"],
        ["I", "V", "IV", "I"],
        ["I", "IV", "I", "V"],
    ],
    3: [
        ["I", "IV", "V", "I"],
        ["I", "V", "IV", "I"],
        ["I", "IV", "I", "V"],
        ["I", "ii", "V", "I"],
    ],
    4: [
        ["I", "vi", "ii", "V", "I", "IV", "V", "I"],
        ["I", "IV", "vi", "V", "I", "ii", "V", "I"],
        ["I", "vi", "IV", "V", "I", "IV", "ii", "V"],
        ["I", "ii", "V", "I", "vi", "IV", "V", "I"],
        ["IV", "V", "I", "vi", "ii", "V", "I", "I"],
        ["vi", "IV", "V", "I", "ii", "V", "I", "I"],
    ],
    5: [
        ["I", "vi", "ii", "V", "I", "IV", "V", "I"],
        ["I", "IV", "vi", "V", "I", "ii", "V", "I"],
        ["I", "vi", "IV", "V", "I", "IV", "ii", "V"],
        ["I", "ii", "V", "I", "vi", "IV", "V", "I"],
        ["IV", "V", "vi", "I", "ii", "V", "I", "I"],
        ["vi", "ii", "V", "I", "IV", "V", "I", "I"],
        ["V", "I", "IV", "vi", "ii", "V", "I", "I"],
        ["ii", "V", "I", "vi", "IV", "I", "V", "I"],
        ["I", "iii", "vi", "IV", "ii", "V", "I", "IV", "V", "vi", "ii", "V"],
    ],
}

_MINOR_PROGRESSIONS: dict[int, list[list[str]]] = {
    1: [
        ["i", "V", "i", "i"],
        ["i", "i", "V", "i"],
        ["i", "iv", "i", "i"],
    ],
    2: [
        ["i", "iv", "V", "i"],
        ["i", "VI", "V", "i"],
        ["i", "iv", "i", "V"],
    ],
    3: [
        ["i", "iv", "V", "i"],
        ["i", "VI", "V", "i"],
        ["i", "iv", "i", "V"],
        ["i", "III", "V", "i"],
    ],
    4: [
        ["i", "VI", "iv", "V", "i", "III", "V", "i"],
        ["i", "iv", "VII", "III", "VI", "iv", "V", "i"],
        ["i", "III", "VI", "iv", "i", "iv", "V", "i"],
        ["iv", "V", "i", "VI", "III", "iv", "V", "i"],
        ["VI", "iv", "V", "i", "iv", "V", "i", "i"],
    ],
    5: [
        ["i", "VI", "iv", "V", "i", "III", "V", "i"],
        ["i", "iv", "VII", "III", "VI", "iv", "V", "i"],
        ["i", "III", "VI", "iv", "i", "iv", "V", "i"],
        ["iv", "V", "i", "VI", "III", "iv", "V", "i"],
        ["VI", "III", "iv", "V", "i", "iv", "V", "i"],
        ["V", "i", "VI", "iv", "III", "iv", "V", "i"],
        ["III", "VI", "iv", "V", "i", "iv", "V", "i"],
        ["i", "VI", "III", "VII", "i", "iv", "V", "i", "VI", "iv", "V", "i"],
    ],
}

_MAJOR_WEAK_CADENCE_BANK: dict[int, list[list[str]]] = {
    1: [["I", "I", "V", "V"], ["I", "IV", "I", "V"], ["I", "V", "I", "V"], ["vi", "IV", "I", "V"]],
    2: [["I", "IV", "I", "V"], ["I", "V", "IV", "V"], ["I", "IV", "V", "V"], ["vi", "IV", "ii", "V"]],
    3: [["I", "IV", "ii", "V"], ["I", "V", "IV", "V"], ["I", "vi", "ii", "V"]],
    4: [["I", "vi", "ii", "V"], ["I", "IV", "ii", "V"], ["I", "V", "IV", "V"]],
    5: [["I", "vi", "ii", "V"], ["I", "IV", "ii", "V"], ["I", "ii", "IV", "V"]],
}

_MAJOR_STRONG_CADENCE_BANK: dict[int, list[list[str]]] = {
    1: [["I", "V", "V", "I"], ["I", "IV", "V", "I"], ["I", "I", "V", "I"], ["vi", "IV", "V", "I"]],
    2: [["I", "IV", "V", "I"], ["I", "V", "IV", "I"], ["I", "ii", "V", "I"], ["vi", "ii", "V", "I"]],
    3: [["I", "ii", "V", "I"], ["I", "IV", "V", "I"], ["I", "vi", "V", "I"]],
    4: [["I", "vi", "ii", "V"], ["I", "IV", "V", "I"], ["I", "ii", "V", "I"]],
    5: [["I", "vi", "ii", "V"], ["I", "IV", "ii", "V"], ["I", "ii", "V", "I"]],
}

_MINOR_WEAK_CADENCE_BANK: dict[int, list[list[str]]] = {
    1: [["i", "i", "v", "v"], ["i", "iv", "i", "v"], ["i", "V", "i", "V"]],
    2: [["i", "iv", "i", "V"], ["i", "VI", "iv", "V"], ["i", "iv", "V", "V"]],
    3: [["i", "iv", "V", "V"], ["i", "VI", "iv", "V"], ["i", "III", "iv", "V"]],
    4: [["i", "VI", "iv", "V"], ["i", "III", "iv", "V"], ["i", "iv", "VII", "V"]],
    5: [["i", "VI", "iv", "V"], ["i", "III", "iv", "V"], ["i", "iv", "VII", "V"]],
}

_MINOR_STRONG_CADENCE_BANK: dict[int, list[list[str]]] = {
    1: [["i", "V", "V", "i"], ["i", "iv", "V", "i"], ["i", "i", "V", "i"]],
    2: [["i", "iv", "V", "i"], ["i", "VI", "V", "i"], ["i", "III", "V", "i"]],
    3: [["i", "iv", "V", "i"], ["i", "VI", "V", "i"], ["i", "III", "V", "i"]],
    4: [["i", "VI", "iv", "V"], ["i", "iv", "V", "i"], ["i", "III", "V", "i"]],
    5: [["i", "VI", "iv", "V"], ["i", "iv", "V", "i"], ["i", "III", "V", "i"]],
}


def _progression_bank(
    grade: int,
    key_signature: str,
    *,
    cadence_strength: str,
) -> list[list[str]]:
    effective_grade = max(1, min(5, int(grade)))
    if is_minor_key(key_signature):
        bank = _MINOR_STRONG_CADENCE_BANK if cadence_strength == "strong" else _MINOR_WEAK_CADENCE_BANK
    else:
        bank = _MAJOR_STRONG_CADENCE_BANK if cadence_strength == "strong" else _MAJOR_WEAK_CADENCE_BANK
    return bank.get(effective_grade, bank[max(bank.keys())])


def _phrase_form_template(measure_count: int) -> list[list[int]]:
    if measure_count <= 4:
        return [list(range(1, measure_count + 1))]
    if measure_count in {8, 12, 16}:
        return [list(range(start, start + 4)) for start in range(1, measure_count + 1, 4)]

    phrases: list[list[int]] = []
    start = 1
    while start <= measure_count:
        end = min(measure_count, start + 3)
        phrases.append(list(range(start, end + 1)))
        start = end + 1
    return phrases


def _form_label(phrases: list[list[int]]) -> str:
    phrase_count = len(phrases)
    if phrase_count <= 1:
        return "Single phrase"
    if phrase_count == 2:
        return "A + B"
    if phrase_count == 3:
        return "A + A' + B"
    if phrase_count == 4:
        return "A + A' + B + close"
    return f"{phrase_count} phrases"


def _harmonic_plan(
    measure_count: int,
    grade: int,
    key_signature: str,
    phrases: list[list[int]],
    rng: random.Random,
    *,
    phrase_grammars: list[PhraseGrammar] | None = None,
) -> list[str]:
    if measure_count <= 0:
        return []

    minor = is_minor_key(key_signature)
    plan = ["I"] * measure_count if not minor else ["i"] * measure_count
    for phrase_index, phrase_measures in enumerate(phrases or _phrase_form_template(measure_count)):
        if not phrase_measures:
            continue

        # Grammar-aware cadence strength: consequent/closing get strong,
        # antecedent/continuation get weak (half cadence on V).
        pg = (
            phrase_grammars[phrase_index]
            if phrase_grammars and phrase_index < len(phrase_grammars)
            else None
        )
        if pg is not None:
            cadence_strength = (
                "strong" if pg.cadence_type in ("authentic", "plagal") else "weak"
            )
        else:
            cadence_strength = "strong" if phrase_measures[-1] == measure_count else "weak"

        bank = _progression_bank(grade, key_signature, cadence_strength=cadence_strength)
        progression = list(rng.choice(bank))
        if len(progression) < len(phrase_measures):
            while len(progression) < len(phrase_measures):
                progression.extend(rng.choice(bank))
        progression = progression[: len(phrase_measures)]

        # Beginner phrases should not default to tonic-centered openings every
        # time. A small harmonic nudge toward IV / V / vi (or the minor-key
        # parallels) gives the reading line a more varied first note while
        # keeping the cadence pattern intact.
        if (
            grade <= 2
            and phrase_index == 0
            and len(progression) >= 4
            and progression[0] in {"I", "i"}
            and rng.random() < 0.8
        ):
            opening_choices = ["IV", "V", "vi"] if not minor else ["iv", "V", "VI"]
            opening_weights = [1.2, 1.0, 0.65]
            if len(progression) > 1:
                filtered_pairs = [
                    (choice, weight)
                    for choice, weight in zip(opening_choices, opening_weights, strict=False)
                    if choice != progression[1]
                ]
                filtered_choices = [choice for choice, _weight in filtered_pairs]
                if filtered_choices:
                    opening_choices = filtered_choices
                    opening_weights = [weight for _choice, weight in filtered_pairs]
            progression[0] = rng.choices(opening_choices, weights=opening_weights, k=1)[0]

        if cadence_strength == "weak":
            progression[-1] = "V"
        else:
            # Plagal cadences end IV → I instead of V → I.
            if pg is not None and pg.cadence_type == "plagal":
                progression[-1] = "I" if not minor else "i"
                if len(progression) >= 2:
                    progression[-2] = "IV" if not minor else "iv"
            else:
                # Authentic: V → I
                progression[-1] = "I" if not minor else "i"
                if len(progression) >= 2 and progression[-2] not in {"V", "v"}:
                    progression[-2] = "V"

        # Deceptive cadences: V → vi instead of V → I (surprise resolution).
        if pg is not None and pg.cadence_type == "deceptive":
            progression[-1] = "vi" if not minor else "VI"
            if len(progression) >= 2 and progression[-2] not in {"V", "v"}:
                progression[-2] = "V"

        for measure_number, harmony in zip(phrase_measures, progression, strict=False):
            plan[measure_number - 1] = harmony
        if phrase_index > 0 and len(phrase_measures) >= 4:
            plan[phrase_measures[0] - 1] = progression[0]
    return plan

"""Key-aware pitch spelling and pitch-pool helpers."""
from __future__ import annotations

import random

from music21 import key, pitch as m21pitch

from ..config import (
    KEY_TONIC_PITCH_CLASS,
    hand_position_limits_for_grade,
    is_minor_key,
    scale_steps_for_key,
)


# ---------------------------------------------------------------------------
# Key-aware pitch spelling
# ---------------------------------------------------------------------------
# When music21 assigns a pitch via MIDI number, it uses a default enharmonic
# spelling (e.g. MIDI 68 → G#4) which may clash with the key signature
# (e.g. Ab major expects Ab4, not G#4).  This causes redundant or wrong
# accidentals to appear in the rendered score.
#
# _KEY_PITCH_SPELLING maps (key_signature, pitch_class_0-11) → note name.
# Built lazily per key the first time it's needed.
# ---------------------------------------------------------------------------

_KEY_PITCH_SPELLING: dict[str, dict[int, str]] = {}


def _build_key_spelling(key_signature: str) -> dict[int, str]:
    """Return a pitch-class → note-name mapping for *key_signature*.

    Diatonic notes use their scale spelling.  Chromatic notes prefer sharps in
    sharp-key contexts and flats in flat-key contexts.
    """
    if key_signature in _KEY_PITCH_SPELLING:
        return _KEY_PITCH_SPELLING[key_signature]

    if is_minor_key(key_signature):
        m21k = key.Key(key_signature[:-1], "minor")
    else:
        m21k = key.Key(key_signature)

    # Diatonic notes from the scale
    spelling: dict[int, str] = {}
    for p in m21k.getScale().pitches[:7]:
        spelling[p.pitchClass] = p.name

    # Chromatic fill – prefer sharps in sharp keys, flats in flat keys
    num_sharps = m21k.sharps  # positive ⇒ sharps, negative ⇒ flats
    for pc in range(12):
        if pc in spelling:
            continue
        p = m21pitch.Pitch(pc)
        if num_sharps >= 0:
            # sharp-key context: prefer sharp spelling
            while "-" in p.name:
                p = p.getEnharmonic()
        else:
            # flat-key context: prefer flat spelling
            while "#" in p.name:
                p = p.getEnharmonic()
        spelling[pc] = p.name

    _KEY_PITCH_SPELLING[key_signature] = spelling
    return spelling


def _spell_midi_pitch(midi_val: int, key_signature: str) -> m21pitch.Pitch:
    """Create a correctly-spelled music21 Pitch from a MIDI number + key."""
    spelling = _build_key_spelling(key_signature)
    pc = midi_val % 12
    name = spelling.get(pc, m21pitch.Pitch(midi=midi_val).name)
    octave = midi_val // 12 - 1
    p = m21pitch.Pitch(f"{name}{octave}")
    # Edge-case octave correction (Cb, B#, etc.)
    while p.midi < midi_val:
        p.octave += 1
    while p.midi > midi_val:
        p.octave -= 1
    return p


def _key_pitch_classes(key_signature: str) -> set[int]:
    tonic = KEY_TONIC_PITCH_CLASS[key_signature]
    steps = scale_steps_for_key(key_signature)
    return {(tonic + step) % 12 for step in steps}


def _position_pitches_from_root(
    root: int,
    key_signature: str,
    pool_size: int = 5,
    *,
    hand: str | None = None,
    grade: int | None = None,
) -> list[int]:
    pitch_classes = _key_pitch_classes(key_signature)
    if hand is not None and grade is not None:
        lower_limit, upper_limit = hand_position_limits_for_grade(hand, grade)

        # Grades 1-2 stay "in position", but allow a small fringe around that
        # core so RH can reach above the five-finger top note and LH can dip
        # below the bass anchor without introducing full position shifts.
        if grade <= 2:
            if hand == "rh":
                window_low = max(lower_limit, root)
                window_high = min(upper_limit, root + 11)
            else:
                window_low = max(lower_limit, root - 3)
                window_high = min(upper_limit, root + 7)

            pitches = [
                midi for midi in range(window_low, window_high + 1)
                if midi % 12 in pitch_classes
            ]
            if pitches:
                return pitches

        scan_low = max(lower_limit, root)
        scan_high = min(upper_limit, root + pool_size + 8)
        pitches = [
            midi for midi in range(scan_low, scan_high + 1)
            if midi % 12 in pitch_classes
        ]
        if len(pitches) >= pool_size:
            return pitches[:pool_size]

    scan_range = pool_size + 8
    pitches = [midi for midi in range(root, root + scan_range)
               if midi % 12 in pitch_classes]
    if len(pitches) >= pool_size:
        return pitches[:pool_size]
    return [root, root + 2, root + 4, root + 5, root + 7]


def _shift_root(current_root: int, hand: str, grade: int, rng: random.Random) -> int:
    lower, upper = hand_position_limits_for_grade(hand, grade)
    next_root = current_root + rng.choice([-2, -1, 1, 2])
    return max(lower, min(upper, next_root))

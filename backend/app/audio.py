from __future__ import annotations

import base64
import io
import math
import random
import wave

import numpy as np


SAMPLE_RATE = 22050
_HAND_PAN = {"rh": 0.22, "lh": -0.28}
_HAND_GAIN = {"rh": 1.0, "lh": 0.78}
_DYNAMIC_TO_GAIN = {
    "pp": 0.22,
    "p": 0.34,
    "mp": 0.48,
    "mf": 0.64,
    "f": 0.82,
    "ff": 0.96,
}


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def midi_to_frequency(midi_value: int) -> float:
    return 440.0 * (2 ** ((midi_value - 69) / 12))


def _piano_note(
    frequency: float,
    duration_seconds: float,
    amplitude: float = 0.45,
    midi_value: int = 60,
    touch: float = 0.58,
    reattack: float = 1.0,
) -> np.ndarray:
    """
    Mono piano note with touch-sensitive warmth, hammer noise, and bloom.
    """
    touch = _clamp(touch, 0.0, 1.0)
    reattack = _clamp(reattack, 0.0, 1.2)
    n_samples = max(1, int(duration_seconds * SAMPLE_RATE))
    t = np.arange(n_samples, dtype=np.float32) / SAMPLE_RATE

    register_t = float(max(0.0, min(1.0, (midi_value - 28) / 72.0)))
    t60_fundamental = max(2.0, 7.2 - register_t * 2.8 - touch * 0.45)
    attack_s = max(0.002, 0.013 - register_t * 0.0015 - touch * 0.0025)
    attack_n = min(n_samples, max(1, int((attack_s / max(0.35, reattack)) * SAMPLE_RATE)))
    brightness = 0.28 + touch * 0.5

    harmonics = [
        (1, 1.000, 1.0),
        (2, 0.340, 1.55),
        (3, 0.180, 2.45),
        (4, 0.095, 3.9),
        (5, 0.050, 6.1),
        (6, 0.024, 8.8),
    ]

    samples = np.zeros(n_samples, dtype=np.float32)
    attack_ramp = np.ones(n_samples, dtype=np.float32)
    ramp = np.linspace(0.0, 1.0, attack_n, dtype=np.float32)
    attack_ramp[:attack_n] = ramp

    for partial_number, relative_amplitude, decay_multiplier in harmonics:
        harmonic_frequency = frequency * partial_number
        if harmonic_frequency >= SAMPLE_RATE * 0.47:
            break

        t60_partial = t60_fundamental / decay_multiplier
        alpha = math.log(1000.0) / max(0.05, t60_partial)
        env = np.exp(-alpha * t, dtype=np.float32) * attack_ramp
        detune = 1.0 + (0.00045 + register_t * 0.00055) * (1 if partial_number % 2 else -1)
        wave_arr = (
            0.72 * np.sin(2.0 * math.pi * harmonic_frequency * t, dtype=np.float32)
            + 0.28 * np.sin(
                2.0 * math.pi * harmonic_frequency * detune * t + (partial_number * 0.11),
                dtype=np.float32,
            )
        )
        brightness_scale = (
            1.0
            if partial_number == 1
            else (0.24 + brightness * min(0.72, partial_number / 6.0))
        )
        samples += (amplitude * relative_amplitude * brightness_scale) * env * wave_arr

    hammer_n = min(n_samples, max(1, int((0.0016 + touch * 0.0015) * SAMPLE_RATE)))
    rng = random.Random(int(frequency * 1337 + midi_value))
    hammer_noise = np.array(
        [rng.uniform(-1.0, 1.0) for _ in range(hammer_n)],
        dtype=np.float32,
    )
    hammer_env = np.linspace(1.0, 0.0, len(hammer_noise), dtype=np.float32)
    hammer_amp = amplitude * reattack * (0.012 + touch * 0.07 + register_t * 0.018)
    samples[: len(hammer_noise)] += hammer_amp * hammer_noise * hammer_env

    body_kernel = np.array([0.08, 0.14, 0.2, 0.24, 0.2, 0.14, 0.08], dtype=np.float32)
    body_kernel /= np.sum(body_kernel)
    body = np.convolve(samples, body_kernel, mode="same").astype(np.float32)
    body_mix = 0.28 + (1.0 - touch) * 0.18
    samples = samples * (1.0 - body_mix) + body * body_mix

    release_n = min(
        max(1, int((0.035 + (1.0 - touch) * 0.02) * SAMPLE_RATE)),
        max(1, n_samples // 3),
    )
    fade = np.linspace(1.0, 0.0, release_n, dtype=np.float32)
    samples[-release_n:] *= fade

    return samples


def _dynamic_gain(event: dict) -> float:
    if event.get("dynamicScalar") is not None:
        return float(event["dynamicScalar"])
    return float(_DYNAMIC_TO_GAIN.get(str(event.get("dynamic", "mf")), _DYNAMIC_TO_GAIN["mf"]))


def _duration_scale(event: dict) -> float:
    if event.get("durationScale") is not None:
        return float(event["durationScale"])
    articulation = event.get("articulation")
    if articulation == "staccato":
        return 0.58
    if articulation == "tenuto":
        return 1.07
    if articulation == "accent":
        return 0.96
    return 0.98


def _reattack_value(event: dict) -> float:
    if event.get("reattack") is not None:
        return float(event["reattack"])
    articulation = event.get("articulation")
    if articulation == "accent":
        return 1.14
    if articulation == "tenuto":
        return 0.92
    return 1.0


def _touch_value(event: dict, note_index: int, note_count: int) -> float:
    touch = float(event.get("touch", 0.16 + _dynamic_gain(event) * 0.52))
    if event.get("hand") == "rh":
        touch += 0.03
        if note_count > 1:
            touch += 0.05 if note_index == note_count - 1 else -0.03
    else:
        touch -= 0.03
        if note_count > 1:
            touch += 0.03 if note_index == 0 else -0.02

    if event.get("slurRole") in {"continue", "stop"}:
        touch -= 0.1

    return _clamp(touch, 0.08, 1.0)


def _pan_gains(pan: float) -> tuple[float, float]:
    pan = _clamp(pan, -1.0, 1.0)
    angle = (pan + 1.0) * (math.pi / 4.0)
    return math.cos(angle), math.sin(angle)


def _voice_weights(hand: str, pitches: list[int]) -> list[float]:
    if not pitches:
        return []

    weights = [1.0 for _ in pitches]
    if len(pitches) > 1:
        if hand == "rh":
            weights[-1] *= 1.35
            for index in range(len(weights) - 1):
                weights[index] *= 0.88
        else:
            weights[0] *= 1.22
            for index in range(1, len(weights)):
                weights[index] *= 0.9

    total = sum(weights) or 1.0
    return [weight / total for weight in weights]


def _consolidate_tied_events(events: list[dict]) -> list[dict]:
    sorted_events = sorted(
        [dict(event) for event in events],
        key=lambda event: (
            0 if event.get("hand") == "rh" else 1,
            float(event.get("offset", 0.0)),
            int(event.get("measure", 0)),
        ),
    )
    consolidated: list[dict] = []
    index = 0

    while index < len(sorted_events):
        event = sorted_events[index]
        tie_group = event.get("tieGroup")
        tie_type = event.get("tieType")
        if tie_group and tie_type == "start":
            merged = dict(event)
            total_duration = float(event.get("_actualDur", event["quarterLength"]))
            cursor = index + 1
            while cursor < len(sorted_events):
                candidate = sorted_events[cursor]
                if (
                    candidate.get("hand") != event.get("hand")
                    or candidate.get("tieGroup") != tie_group
                ):
                    break
                total_duration += float(candidate.get("_actualDur", candidate["quarterLength"]))
                if candidate.get("tieType") == "stop":
                    break
                cursor += 1

            merged["quarterLength"] = round(total_duration, 3)
            merged["_actualDur"] = round(total_duration, 3)
            merged.pop("tieGroup", None)
            merged.pop("tieType", None)
            consolidated.append(merged)
            index = cursor + 1
            continue

        if tie_group and tie_type in {"continue", "stop"}:
            index += 1
            continue

        event.pop("tieGroup", None)
        event.pop("tieType", None)
        consolidated.append(event)
        index += 1

    return consolidated


def _render_wave(events: list[dict], bpm: int) -> bytes:
    quarter_seconds = 60.0 / max(40, bpm)
    playback_events = _consolidate_tied_events(events)
    total_quarters = max(
        (float(event["offset"]) + float(event["quarterLength"]) for event in playback_events),
        default=0.0,
    )
    total_seconds = max(1.0, total_quarters * quarter_seconds + 2.4)
    total_samples = max(1, int(total_seconds * SAMPLE_RATE))
    mix = np.zeros((2, total_samples), dtype=np.float32)

    next_offset_by_hand: dict[str, float] = {}
    for event in reversed(playback_events):
        hand = str(event.get("hand", "rh"))
        event["_nextHandOffset"] = next_offset_by_hand.get(hand)
        next_offset_by_hand[hand] = float(event["offset"])

    for event in playback_events:
        pitches = [int(pitch) for pitch in (event.get("pitches") or [])]
        if event.get("isRest") or not pitches:
            continue

        base_duration = float(event.get("_actualDur", event["quarterLength"])) * quarter_seconds
        duration_seconds = base_duration * _duration_scale(event)
        next_offset = event.get("_nextHandOffset")
        if next_offset is not None:
            gap_seconds = max(
                0.0,
                (float(next_offset) - float(event["offset"])) * quarter_seconds,
            )
            if event.get("articulation") == "staccato":
                duration_seconds = min(duration_seconds, max(0.04, gap_seconds * 0.72))
            elif event.get("slurId") and event.get("slurRole") != "stop":
                duration_seconds = max(duration_seconds, gap_seconds + 0.025)
            elif gap_seconds > 0:
                duration_seconds = min(
                    duration_seconds,
                    max(base_duration * 0.6, gap_seconds * 1.02),
                )

        start_idx = max(0, int(float(event["offset"]) * quarter_seconds * SAMPLE_RATE))
        hand = str(event.get("hand", "rh"))
        dynamic_gain = _dynamic_gain(event)
        voice_weights = _voice_weights(hand, pitches)
        left_gain, right_gain = _pan_gains(_HAND_PAN.get(hand, 0.0))

        for pitch_index, midi_value in enumerate(pitches):
            frequency = midi_to_frequency(int(midi_value))
            amplitude = (0.2 + dynamic_gain * 0.44) * _HAND_GAIN.get(hand, 1.0)
            amplitude *= (
                voice_weights[pitch_index]
                if pitch_index < len(voice_weights)
                else 1.0 / math.sqrt(max(1, len(pitches)))
            )
            note_arr = _piano_note(
                frequency,
                duration_seconds,
                amplitude=amplitude,
                midi_value=int(midi_value),
                touch=_touch_value(event, pitch_index, len(pitches)),
                reattack=_reattack_value(event),
            )
            end_idx = min(start_idx + len(note_arr), total_samples)
            if end_idx <= start_idx:
                continue

            mix[0, start_idx:end_idx] += note_arr[: end_idx - start_idx] * left_gain
            mix[1, start_idx:end_idx] += note_arr[: end_idx - start_idx] * right_gain

    peak = float(np.max(np.abs(mix)))
    if peak > 0.9:
        mix *= 0.9 / peak

    pcm = np.clip(mix.T * 32767, -32767, 32767).astype(np.int16)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(pcm.tobytes())

    return buffer.getvalue()


def render_audio_data_uri(events: list[dict], bpm: int) -> str:
    wav_bytes = _render_wave(events, bpm)
    encoded = base64.b64encode(wav_bytes).decode("ascii")
    return f"data:audio/wav;base64,{encoded}"

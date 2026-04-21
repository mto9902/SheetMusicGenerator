"""MusicXML generation and SVG rendering via Verovio."""
from __future__ import annotations

from typing import Any

from music21 import (
    articulations,
    bar,
    chord,
    clef,
    duration as m21duration,
    dynamics,
    expressions,
    key,
    layout,
    meter,
    note,
    spanner,
    stream,
    tempo,
    tie as m21tie,
)
from music21.musicxml.m21ToXml import GeneralObjectExporter

try:
    from verovio import toolkit  # type: ignore
except Exception:  # pragma: no cover
    toolkit = None

from ..config import is_minor_key
from ._helpers import _measure_total, _mean
from ._pitch import _spell_midi_pitch


def _entry_for_event(event: dict[str, Any], key_signature: str | None = None):
    if event["isRest"] or not event["pitches"]:
        return note.Rest(quarterLength=float(event["quarterLength"]))

    if len(event["pitches"]) > 1:
        if key_signature:
            spelled = [_spell_midi_pitch(int(m), key_signature) for m in event["pitches"]]
            entry = chord.Chord(spelled, quarterLength=float(event["quarterLength"]))
        else:
            entry = chord.Chord(event["pitches"], quarterLength=float(event["quarterLength"]))
    else:
        entry = note.Note(quarterLength=float(event["quarterLength"]))
        if key_signature:
            entry.pitch = _spell_midi_pitch(int(event["pitches"][0]), key_signature)
        else:
            entry.pitch.midi = int(event["pitches"][0])

    if event.get("eventId"):
        entry.id = str(event["eventId"])

    if event.get("tieType"):
        entry.tie = m21tie.Tie(str(event["tieType"]))

    # Tuplet (triplets)
    if event.get("tuplet"):
        t = event["tuplet"]
        entry.duration.tuplets = [
            m21duration.Tuplet(
                numberNotesActual=t["actual"],
                numberNotesNormal=t["normal"],
            )
        ]

    # Articulations
    art = event.get("articulation")
    if art == "staccato":
        entry.articulations.append(articulations.Staccato())
    elif art == "accent":
        entry.articulations.append(articulations.Accent())
    elif art == "tenuto":
        entry.articulations.append(articulations.Tenuto())

    # Fermata (final note of piece)
    if event.get("fermata"):
        entry.expressions.append(expressions.Fermata())

    return entry


def _build_measure(
    hand_events: list[dict[str, Any]],
    measure_number: int,
    measure_offset: float,
    total: float,
    is_final: bool,
    *,
    start_new_system: bool = False,
    key_signature: str | None = None,
) -> stream.Measure:
    measure_obj = stream.Measure(number=measure_number)
    if start_new_system:
        measure_obj.insert(0, layout.SystemLayout(isNew=True))
    cursor = 0.0

    # Expressible rest durations (standard note values)
    _EXPRESSIBLE = {4.0, 3.0, 2.0, 1.5, 1.0, 0.75, 0.5, 0.25, 0.125}

    def _add_rest_if_expressible(dur: float):
        dur = round(dur, 3)
        if dur <= 0.001:
            return
        # Only add rest if it's a standard duration; skip tiny tuplet gaps
        if dur in _EXPRESSIBLE or dur >= 0.25:
            # For non-standard durations, snap to nearest expressible
            if dur not in _EXPRESSIBLE:
                candidates = [d for d in _EXPRESSIBLE if d <= dur + 0.001]
                if candidates:
                    dur = max(candidates)
                else:
                    return
            measure_obj.append(note.Rest(quarterLength=dur))

    for event in sorted(hand_events, key=lambda item: float(item["offset"])):
        local_start = round(float(event["offset"]) - measure_offset, 3)
        gap = round(local_start - cursor, 3)
        if gap > 0.001:
            _add_rest_if_expressible(gap)

        entry = _entry_for_event(event, key_signature=key_signature)
        measure_obj.append(entry)

        # Dynamic marking
        if event.get("dynamic"):
            dyn = dynamics.Dynamic(event["dynamic"])
            measure_obj.insert(local_start, dyn)

        # Use actual sounding duration for cursor (different for tuplets)
        actual_dur = float(event.get("_actualDur", event["quarterLength"]))
        cursor = round(local_start + actual_dur, 3)

    trailing = round(total - cursor, 3)
    if trailing > 0.001:
        _add_rest_if_expressible(trailing)

    measure_obj.rightBarline = bar.Barline("final" if is_final else "regular")
    return measure_obj


def _apply_part_spanners(part: stream.Part, hand_events: list[dict[str, Any]]) -> None:
    entry_map: dict[str, Any] = {}
    for entry in part.recurse().getElementsByClass([note.Note, chord.Chord]):
        entry_id = getattr(entry, "id", None)
        if entry_id:
            entry_map[str(entry_id)] = entry

    slur_groups: dict[str, list[str]] = {}
    hairpin_starts: dict[str, tuple[str, str]] = {}
    hairpin_stops: dict[str, str] = {}

    for event in hand_events:
        if event.get("isRest") or not event.get("pitches") or not event.get("eventId"):
            continue

        slur_id = event.get("slurId")
        if slur_id:
            slur_groups.setdefault(str(slur_id), []).append(str(event["eventId"]))

        hairpin_start = event.get("hairpinStart")
        if hairpin_start:
            hairpin_starts[str(hairpin_start["id"])] = (
                str(hairpin_start["type"]),
                str(event["eventId"]),
            )

        for hairpin_stop_id in event.get("hairpinStopIds", []):
            hairpin_stops[str(hairpin_stop_id)] = str(event["eventId"])

    for slur_event_ids in slur_groups.values():
        entries = [entry_map[event_id] for event_id in slur_event_ids if event_id in entry_map]
        if len(entries) >= 2:
            part.insert(0, spanner.Slur(entries))

    for hairpin_id, (hairpin_type, start_event_id) in hairpin_starts.items():
        end_event_id = hairpin_stops.get(hairpin_id)
        if not end_event_id:
            continue

        start_entry = entry_map.get(start_event_id)
        end_entry = entry_map.get(end_event_id)
        if not start_entry or not end_entry or start_entry is end_entry:
            continue

        wedge = dynamics.Crescendo() if hairpin_type == "crescendo" else dynamics.Diminuendo()
        wedge.addSpannedElements([start_entry, end_entry])
        part.insert(0, wedge)


def _music21_key(key_signature: str):
    if is_minor_key(key_signature):
        tonic = key_signature[:-1]
        return key.Key(tonic, "minor")
    return key.Key(key_signature)


def _engraving_system_interval(request: dict[str, Any], events: list[dict[str, Any]]) -> int:
    measure_count = int(request["measureCount"])
    if measure_count <= 4:
        return 4

    density_samples: list[float] = []
    dense_measures = 0
    for measure_number in range(1, measure_count + 1):
        measure_events = [
            event for event in events
            if int(event.get("measure", 0)) == measure_number
            and not event.get("isRest")
        ]
        if not measure_events:
            density_samples.append(0.0)
            continue

        density = 0.0
        for event in measure_events:
            duration_value = float(event.get("_actualDur", event.get("quarterLength", 0.0)))
            pitch_count = len(event.get("pitches", []))
            technique = str(event.get("technique", ""))

            density += 1.0
            density += max(0, pitch_count - 1) * 0.65
            if duration_value <= 0.5:
                density += 0.8
            if duration_value <= 0.25:
                density += 1.1
            if technique in {"triplet", "scale run", "scale figure", "scale figure landing", "chordal texture", "block chord"}:
                density += 0.9

        density_samples.append(density)
        if density >= 9.5:
            dense_measures += 1

    avg_density = _mean(density_samples, default=0.0)
    very_dense = avg_density >= 9.0 or dense_measures >= max(2, measure_count // 3)
    dense = avg_density >= 7.0 or dense_measures >= max(1, measure_count // 4)

    if measure_count == 8:
        return 2 if dense else 4
    if measure_count == 12:
        return 3 if dense else 4
    if measure_count >= 16:
        return 2 if very_dense else 4
    return 4


def _create_musicxml(request: dict[str, Any], events: list[dict[str, Any]], bpm: int) -> str:
    score = stream.Score()
    right_hand = stream.Part(id="RH")
    left_hand = stream.Part(id="LH")

    right_hand.partName = "RH"
    left_hand.partName = "LH"

    right_hand.append(tempo.MetronomeMark(number=bpm))
    left_hand.append(tempo.MetronomeMark(number=bpm))
    right_hand.insert(0, clef.TrebleClef())
    left_hand.insert(0, clef.BassClef())
    right_hand.insert(0, meter.TimeSignature(request["timeSignature"]))
    left_hand.insert(0, meter.TimeSignature(request["timeSignature"]))

    if request["mode"] == "piano":
        m21_key = _music21_key(request["keySignature"])
        right_hand.insert(0, m21_key)
        left_hand.insert(0, key.Key(m21_key.tonic, m21_key.mode))

    total = _measure_total(request["timeSignature"])
    ks = request.get("keySignature") if request.get("mode") != "rhythm" else None
    system_interval = _engraving_system_interval(request, events)
    for measure_number in range(1, int(request["measureCount"]) + 1):
        measure_offset = (measure_number - 1) * total
        right_events = [
            event for event in events if event["hand"] == "rh" and int(event["measure"]) == measure_number
        ]
        left_events = [
            event for event in events if event["hand"] == "lh" and int(event["measure"]) == measure_number
        ]
        is_final = measure_number == int(request["measureCount"])
        start_new_system = measure_number > 1 and (measure_number - 1) % system_interval == 0
        right_hand.append(
            _build_measure(
                right_events,
                measure_number,
                measure_offset,
                total,
                is_final,
                start_new_system=start_new_system,
                key_signature=ks,
            )
        )
        left_hand.append(
            _build_measure(
                left_events,
                measure_number,
                measure_offset,
                total,
                is_final,
                start_new_system=start_new_system,
                key_signature=ks,
            )
        )

    _apply_part_spanners(
        right_hand,
        [event for event in events if event.get("hand") == "rh"],
    )
    _apply_part_spanners(
        left_hand,
        [event for event in events if event.get("hand") == "lh"],
    )

    score.insert(0, right_hand)
    score.insert(0, left_hand)
    score.insert(0, layout.StaffGroup([right_hand, left_hand], name="Piano", symbol="brace", barTogether=True))

    # --- Strip redundant accidentals that the key signature already covers ---
    # music21 often attaches explicit accidental objects even for diatonic notes;
    # the MusicXML exporter then writes <accidental> tags that Verovio renders
    # as visible sharps/flats.  We suppress display for any note whose
    # accidental matches the key signature.
    if ks:
        m21k = _music21_key(ks)
        ks_names = {p.name for p in m21k.alteredPitches}
        for part_obj in (right_hand, left_hand):
            for n in part_obj.flatten().notes:
                pitches_to_check = n.pitches if hasattr(n, "pitches") else [n.pitch]
                for p in pitches_to_check:
                    if p.accidental and p.name in ks_names:
                        p.accidental.displayStatus = False

    xml_bytes = GeneralObjectExporter(score).parse()
    return xml_bytes.decode("utf-8")


def _render_svg(music_xml: str, title: str) -> str:
    if toolkit is None:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="360" viewBox="0 0 1200 360">'
            '<rect width="1200" height="360" fill="#ffffff" stroke="#d9d2c8" />'
            f'<text x="60" y="92" font-size="42" font-family="Arial" fill="#17181d">{title}</text>'
            '<text x="60" y="150" font-size="22" font-family="Arial" fill="#68707c">'
            "Install verovio to render grand-staff notation locally."
            "</text></svg>"
        )

    import re

    vrv = toolkit()
    vrv.setOptions({
        "pageWidth": 920,
        "pageMarginLeft": 26,
        "pageMarginRight": 26,
        "pageMarginTop": 30,
        "pageMarginBottom": 22,
        "scale": 39,
        "header": "none",
        "footer": "none",
        "adjustPageHeight": True,
        "breaks": "encoded",
        "spacingSystem": 16,
        "spacingStaff": 8,
    })
    vrv.loadData(music_xml)

    def _fix_svg(raw: str) -> str:
        fixed = raw.replace("currentColor", "#000000")
        fixed = re.sub(r"<path(?![^>]*\bstroke=)\s", '<path stroke="#000000" ', fixed)
        fixed = re.sub(r"<rect(?![^>]*\bstroke=)\s", '<rect stroke="#000000" ', fixed)
        fixed = re.sub(r"<polyline(?![^>]*\bstroke=)\s", '<polyline stroke="#000000" ', fixed)
        fixed = re.sub(r"<polygon(?![^>]*\bstroke=)\s", '<polygon stroke="#000000" ', fixed)
        fixed = re.sub(r"<ellipse(?![^>]*\bstroke=)\s", '<ellipse stroke="#000000" ', fixed)
        fixed = re.sub(
            r'(<g[^>]*class="slur"[^>]*>\s*<path\b)(?![^>]*\bfill=)',
            r'\1 fill="none"',
            fixed,
        )
        return fixed

    page_count = vrv.getPageCount()
    if page_count == 1:
        return _fix_svg(vrv.renderToSVG(1))

    page_svgs: list[str] = []
    page_heights: list[float] = []
    page_width = 0.0

    for page_num in range(1, page_count + 1):
        svg = vrv.renderToSVG(page_num)
        match = re.search(r'width="([\d.]+)px"\s+height="([\d.]+)px"', svg)
        if match:
            page_width = max(page_width, float(match.group(1)))
            page_heights.append(float(match.group(2)))
        else:
            page_heights.append(500.0)
        page_svgs.append(svg)

    total_height = sum(page_heights)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{page_width}px" height="{total_height}px" '
        f'viewBox="0 0 {page_width} {total_height}">'
    ]

    y_offset = 0.0
    for svg, h in zip(page_svgs, page_heights):
        inner = re.sub(r'^<svg[^>]*>', '', svg, count=1)
        inner = re.sub(r'</svg>\s*$', '', inner, count=1)
        parts.append(
            f'<svg x="0" y="{y_offset}" width="{page_width}" height="{h}">'
            f'{inner}</svg>'
        )
        y_offset += h

    parts.append("</svg>")
    return _fix_svg("".join(parts))

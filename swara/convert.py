"""One entry point that turns a Piece into everything a front end needs to draw."""
from .notes import (SHARP_NAMES, detect_key, format_swara, midi_name, parse_key, pitch_class,
                    plan_shift, sa_reference, swara_of, LONG, SHORT)
from .readers import mono_ratio, pick_part, to_melody
from .render import build_cells, pick_subdiv, quantise


def list_parts(piece):
    auto = pick_part(piece)
    out = []
    for i, part in enumerate(piece.parts):
        ps = [n.pitch for n in part.notes]
        out.append({"index": i, "name": part.name, "notes": len(ps), "low": midi_name(min(ps)),
                    "high": midi_name(max(ps)), "mono": round(mono_ratio(part.notes), 2), "auto": i == auto})
    return out


def convert(piece, sa="D#", key=None, absolute=False, part=None, subdiv=None, beats_per_bar=None,
            long=False):
    """Raises ValueError with a user-readable message on bad input."""
    if not piece.parts:
        raise ValueError("No notes found in that file.")
    sa_pc = pitch_class(sa)
    idx = pick_part(piece) if part is None else part
    if not 0 <= idx < len(piece.parts):
        raise ValueError(f"Part must be 0-{len(piece.parts) - 1}.")
    melody = to_melody(piece.parts[idx].notes)
    if not melody:
        raise ValueError("That part has no notes.")
    tonic, mode = parse_key(key) if key else detect_key(melody)
    shift = plan_shift(melody, tonic, sa_pc, absolute)
    sa_ref = sa_reference(sa_pc)
    subdiv = subdiv or pick_subdiv(melody)
    bar_beats = beats_per_bar or piece.beats_per_bar
    units_per_bar = max(1, round(bar_beats * subdiv))
    raw_bars = build_cells(quantise(melody, subdiv), units_per_bar)
    first = next((i for i, b in enumerate(raw_bars) if any(c is not None for c in b)), 0)

    def cell(c):
        if c is None:
            return {"t": "rest"}
        if c == "hold":
            return {"t": "hold"}
        semi, octave = swara_of(c + shift, sa_ref)
        return {"t": "note", "name": (LONG if long else SHORT)[semi], "octave": octave,
                "text": format_swara(semi, octave, long), "western": midi_name(c),
                "played": midi_name(c + shift), "midi": c + shift}

    low, high = min(n.pitch for n in melody) + shift, max(n.pitch for n in melody) + shift
    return {
        "title": piece.title, "part": idx, "partName": piece.parts[idx].name,
        "parts": list_parts(piece),
        "sa": SHARP_NAMES[sa_pc], "key": f"{SHARP_NAMES[tonic]} {mode}", "keyDetected": not key,
        "shift": shift, "absolute": absolute,
        "low": format_swara(*swara_of(low, sa_ref), long), "high": format_swara(*swara_of(high, sa_ref), long),
        "lowPitch": midi_name(low), "highPitch": midi_name(high),
        "subdiv": subdiv, "beatsPerBar": bar_beats, "unitsPerBar": units_per_bar,
        "firstBar": first + 1,
        "bars": [[cell(c) for c in b] for b in raw_bars[first:]],
    }

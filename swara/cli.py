import argparse
import sys

from .notes import (SHARP_NAMES, detect_key, format_swara, midi_name, parse_key, pitch_class,
                    plan_shift, sa_reference, swara_of)
from .readers import mono_ratio, pick_part, read_file, read_text, to_melody
from .render import build_cells, layout, pick_subdiv, quantise


def build_parser():
    p = argparse.ArgumentParser(prog="swara", description="Turn Western tunes into Carnatic sargam notation.")
    p.add_argument("file", nargs="?", help=".mid / .musicxml / .mxl file")
    p.add_argument("--notes", help='type a tune instead, e.g. "E4 E4 F4 G4:2 r" (":n" = beats, r = rest)')
    p.add_argument("--sa", default="D#", help="your violin's Sa (default D#)")
    p.add_argument("--key", help='override detected key, e.g. "G major" or "A minor"')
    p.add_argument("--absolute", action="store_true",
                   help="keep the song's original pitches (play along with the recording) "
                        "instead of moving its tonic onto Sa")
    p.add_argument("--list", action="store_true", help="list the parts in the file and exit")
    p.add_argument("--part", type=int, help="part number to use (see --list); default: auto-pick the melody")
    p.add_argument("--subdiv", type=int, help="notes per beat on the grid (default: auto)")
    p.add_argument("--beats-per-bar", type=float, help="override the bar length in quarter-note beats")
    p.add_argument("--bars-per-line", type=int, default=4)
    p.add_argument("--western", action="store_true", help="print the Western note names under each swara")
    p.add_argument("--long", action="store_true", help="use R1/R2/G2/G3... names instead of r/R/g/G...")
    p.add_argument("-o", "--output", help="write to a file instead of the terminal")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.notes:
            piece = read_text(args.notes, args.beats_per_bar or 4.0)
        elif args.file:
            piece = read_file(args.file)
        else:
            build_parser().error("give a file or --notes")
        sa_pc = pitch_class(args.sa)
    except (ValueError, OSError, KeyError) as e:
        print(f"swara: {e}", file=sys.stderr)
        return 1
    if not piece.parts:
        print("swara: no notes found", file=sys.stderr)
        return 1

    auto = pick_part(piece)
    if args.list:
        for i, part in enumerate(piece.parts):
            ps = [n.pitch for n in part.notes]
            print(f"{i:>2}{'*' if i == auto else ' '} {part.name:<32} {len(ps):>5} notes  "
                  f"{midi_name(min(ps))}-{midi_name(max(ps))}  one-at-a-time {mono_ratio(part.notes):.0%}")
        print("* = auto-picked melody")
        return 0
    idx = auto if args.part is None else args.part
    if not 0 <= idx < len(piece.parts):
        print(f"swara: part must be 0-{len(piece.parts) - 1}", file=sys.stderr)
        return 1
    part = piece.parts[idx]
    melody = to_melody(part.notes)
    if not melody:
        print("swara: that part has no notes", file=sys.stderr)
        return 1

    try:
        tonic, mode = parse_key(args.key) if args.key else detect_key(melody)
    except ValueError as e:
        print(f"swara: {e}", file=sys.stderr)
        return 1
    shift = plan_shift(melody, tonic, sa_pc, args.absolute)
    sa_ref = sa_reference(sa_pc)
    subdiv = args.subdiv or pick_subdiv(melody)
    bar_beats = args.beats_per_bar or piece.beats_per_bar
    units_per_bar = max(1, round(bar_beats * subdiv))
    bars = build_cells(quantise(melody, subdiv), units_per_bar)

    low, high = min(n.pitch for n in melody) + shift, max(n.pitch for n in melody) + shift
    lo_s, hi_s = swara_of(low, sa_ref), swara_of(high, sa_ref)
    sa_name = SHARP_NAMES[sa_pc]
    out = []
    if piece.title:
        out.append(piece.title)
    out.append(f"Part: {part.name}")
    out.append(f"Song key: {SHARP_NAMES[tonic]} {mode}" + ("" if args.key else "  (detected; use --key to correct)"))
    if args.absolute:
        out.append(f"Original pitches kept, Sa = {sa_name}: play along with the recording")
    else:
        out.append(f"Song's {SHARP_NAMES[tonic]} -> Sa ({sa_name}); tune moved {shift:+d} semitones, so it sounds in {sa_name} {mode}")
    out.append(f"Range: {format_swara(*lo_s)} to {format_swara(*hi_s)}  ({midi_name(low)} to {midi_name(high)})")
    out.append(f"Grid: {subdiv} per beat, {bar_beats:g} beats per bar.   , = hold   - = rest   dot above = tara, dot below = mandra")
    out.append("")
    out.extend(layout(bars, shift, sa_ref, subdiv, args.bars_per_line, args.western, args.long))
    text = "\n".join(out).rstrip() + "\n"
    if args.output:
        with open(args.output, "w") as f:
            f.write(text)
        print(f"wrote {args.output}")
    else:
        print(text, end="")
    return 0

"""Quantise a monophonic melody onto a grid and lay it out as bars of sargam."""
import math
import unicodedata

from .notes import format_swara, midi_name, swara_of

REST, HOLD = "-", ","


def vlen(s):
    return sum(1 for c in s if not unicodedata.combining(c))


def pad(s, width):
    return s + " " * (width - vlen(s))


def pick_subdiv(notes, tolerance=0.03):
    """Smallest units-per-beat that puts nearly every onset on the grid."""
    for s in (1, 2, 3, 4, 6, 8):
        off = sum(1 for n in notes if abs(n.start - round(n.start * s) / s) > tolerance)
        if off <= 0.05 * len(notes):
            return s
    return 8


def quantise(notes, subdiv):
    """-> list of (start_unit, end_unit, pitch), non-overlapping."""
    out = []
    for i, n in enumerate(notes):
        start = round(n.start * subdiv)
        end = n.start + n.dur
        if i + 1 < len(notes):
            nxt = notes[i + 1].start
            if nxt - end < 0.25 * (nxt - n.start):  # tiny gap = articulation, not a rest
                end = nxt
        end = max(round(end * subdiv), start + 1)
        if out and start < out[-1][1]:
            out[-1] = (out[-1][0], max(start, out[-1][0] + 1), out[-1][2])
            start = max(start, out[-1][1])
        out.append((start, max(end, start + 1), n.pitch))
    return out


def build_cells(q, units_per_bar):
    """-> list of bars; each bar is a list of None (rest), 'hold', or a pitch."""
    total = max(e for _, e, _ in q)
    bars = math.ceil(total / units_per_bar)
    units = [None] * (bars * units_per_bar)
    for start, end, pitch in q:
        units[start] = pitch
        for u in range(start + 1, min(end, len(units))):
            units[u] = "hold"
    return [units[b * units_per_bar:(b + 1) * units_per_bar] for b in range(bars)]


def layout(bars, shift, sa_ref, subdiv, bars_per_line=4, western=False, long=False):
    lines = []
    first = next((i for i, b in enumerate(bars) if any(c is not None for c in b)), 0)
    for lo in range(first, len(bars), bars_per_line):
        rows = [[], []]
        for bar in bars[lo:lo + bars_per_line]:
            cells = []
            for c in bar:
                if c is None:
                    cells.append((REST, REST))
                elif c == "hold":
                    cells.append((HOLD, HOLD))
                else:
                    semi, octave = swara_of(c + shift, sa_ref)
                    cells.append((format_swara(semi, octave, long), midi_name(c)))
            widths = [max(vlen(a), vlen(b)) if western else vlen(a) for a, b in cells]
            for r in (0, 1):
                text = ""
                for k, (cell, w) in enumerate(zip(cells, widths)):
                    if k:
                        text += "   " if k % subdiv == 0 else " "
                    text += pad(cell[r], w)
                rows[r].append(text)
        prefix = f"{lo + 1:>4}  "
        lines.append(prefix + " | ".join(rows[0]) + " |")
        if western:
            lines.append(" " * len(prefix) + " | ".join(rows[1]) + " |")
        lines.append("")
    return lines

"""Pitch helpers, the Western -> Carnatic swara mapping, and key detection."""
import math
import re
from dataclasses import dataclass

SHARP_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_STEP = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_PITCH_RE = re.compile(r"^([A-Ga-g])([#b♯♭]*)(-?\d+)?$")

# Index = semitones above Sa. Where Carnatic has two names for one pitch
# (R2/G1, R3/G2, D2/N1, D3/N2) we use the name a major/minor-style tune implies.
SHORT = ["S", "r", "R", "g", "G", "m", "M", "P", "d", "D", "n", "N"]
LONG = ["S", "R1", "R2", "G2", "G3", "M1", "M2", "P", "D1", "D2", "N2", "N3"]

_OCTAVE_MARK = {0: "", 1: "̇", 2: "̈", -1: "̣", -2: "̤"}


@dataclass
class Note:
    start: float  # in quarter-note beats
    dur: float
    pitch: int  # MIDI number


def parse_pitch(text, default_octave=4):
    m = _PITCH_RE.match(text.strip())
    if not m:
        raise ValueError(f"can't read note name: {text!r}")
    letter, acc, octave = m.groups()
    semis = _STEP[letter.upper()]
    for ch in acc:
        semis += 1 if ch in "#♯" else -1
    octave = default_octave if octave is None else int(octave)
    return 12 * (octave + 1) + semis


def pitch_class(text):
    return parse_pitch(text) % 12


def midi_name(pitch):
    return f"{SHARP_NAMES[pitch % 12]}{pitch // 12 - 1}"


def sa_reference(sa_pc):
    """MIDI number of Sa in madhya sthayi: the Sa within C4..B4."""
    return 60 + sa_pc


def swara_of(pitch, sa_ref):
    octave, semi = divmod(pitch - sa_ref, 12)
    return semi, octave


def format_swara(semi, octave, long=False):
    name = (LONG if long else SHORT)[semi]
    mark = _OCTAVE_MARK.get(octave)
    if mark is None:
        return f"{name}{octave:+d}"
    return name[0] + mark + name[1:]


# --- key detection (Krumhansl-Schmuckler) ---------------------------------

_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
_MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]


def _pearson(a, b):
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return num / den if den else 0.0


def detect_key(notes):
    """Return (tonic_pc, 'major'|'minor') best matching the duration-weighted pitch classes."""
    hist = [0.0] * 12
    for n in notes:
        hist[n.pitch % 12] += n.dur
    best = None
    for tonic in range(12):
        rotated = hist[tonic:] + hist[:tonic]
        for mode, profile in (("major", _MAJOR), ("minor", _MINOR)):
            r = _pearson(rotated, profile)
            if best is None or r > best[0]:
                best = (r, tonic, mode)
    return best[1], best[2]


def parse_key(text):
    m = re.match(r"^\s*([A-Ga-g])([#b♯♭]?)\s*(major|maj|minor|min|m|M)?\s*$", text)
    if not m:
        raise ValueError(f"can't read key: {text!r} (try 'C major' or 'F# minor')")
    letter, acc, mode = m.groups()
    pc = _STEP[letter.upper()] + {"#": 1, "♯": 1, "b": -1, "♭": -1, "": 0}[acc]
    minor = mode is not None and mode != "M" and mode.lower() in ("minor", "min", "m")
    return pc % 12, "minor" if minor else "major"


# --- transposition ---------------------------------------------------------

def plan_shift(notes, tonic_pc, sa_pc, absolute=False):
    """Semitone shift to apply to the tune. Relative mode moves the song's tonic onto Sa,
    choosing the octave that centres the melody in madhya sthayi."""
    if absolute:
        return 0
    pitches = sorted(n.pitch for n in notes)
    median = pitches[len(pitches) // 2]
    centre = sa_reference(sa_pc) + 6
    base = (sa_pc - tonic_pc) % 12
    return min((base + 12 * k for k in range(-4, 5)), key=lambda s: abs(median + s - centre))

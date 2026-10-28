"""Read tunes from MIDI, MusicXML/MXL, or a typed note list into parts of Notes."""
import struct
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field, replace
from fractions import Fraction

from .notes import _STEP, Note, parse_pitch


@dataclass
class Part:
    name: str
    notes: list = field(default_factory=list)


@dataclass
class Piece:
    parts: list
    beats_per_bar: float = 4.0  # in quarter-note beats
    title: str = ""


# --- MIDI ------------------------------------------------------------------

def _varint(body, i):
    value = 0
    while True:
        b = body[i]
        i += 1
        value = (value << 7) | (b & 0x7F)
        if not b & 0x80:
            return value, i


def _parse_track(body, division, index, parts, state):
    i = tick = 0
    status = None
    track_name = None
    active = {}  # (channel, note) -> [start ticks]
    found = {}  # channel -> [Note]

    def close(ch, note, start, end):
        found.setdefault(ch, []).append(Note(start / division, (end - start) / division, note))

    try:
        while i < len(body):
            delta, i = _varint(body, i)
            tick += delta
            b = body[i]
            if b == 0xFF:
                kind = body[i + 1]
                length, i = _varint(body, i + 2)
                payload = body[i:i + length]
                i += length
                if kind == 0x03 and track_name is None:
                    track_name = payload.decode("latin-1").strip()
                elif kind == 0x58 and length >= 2 and state["timesig"] is None:
                    state["timesig"] = (payload[0], 2 ** payload[1])
                elif kind == 0x2F:
                    break
                continue
            if b in (0xF0, 0xF7):
                length, i = _varint(body, i + 1)
                i += length
                status = None
                continue
            if b & 0x80:
                status = b
                i += 1
            elif status is None:
                raise ValueError("MIDI data starts without a status byte")
            kind, ch = status & 0xF0, status & 0x0F
            if kind in (0xC0, 0xD0):
                i += 1
                continue
            d1, d2 = body[i], body[i + 1]
            i += 2
            if kind == 0x90 and d2 > 0:
                active.setdefault((ch, d1), []).append(tick)
            elif kind == 0x80 or kind == 0x90:
                starts = active.get((ch, d1))
                if starts:
                    close(ch, d1, starts.pop(0), tick)
    except IndexError:
        pass  # truncated track: keep what we have
    for (ch, note), starts in active.items():
        for s in starts:
            close(ch, note, s, max(tick, s + 1))
    for ch, notes in found.items():
        if ch == 9:  # General MIDI drums
            continue
        label = track_name or f"track {index}"
        parts.append(Part(f"{label} (ch {ch + 1})", sorted(notes, key=lambda n: n.start)))


def read_midi(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"MThd":
        raise ValueError("not a MIDI file")
    hlen = struct.unpack(">I", data[4:8])[0]
    _fmt, _ntrk, division = struct.unpack(">HHH", data[8:14])
    if division & 0x8000:
        raise ValueError("SMPTE-timed MIDI isn't supported")
    pos = 8 + hlen
    parts, state, index = [], {"timesig": None}, 0
    while pos + 8 <= len(data):
        chunk, length = data[pos:pos + 4], struct.unpack(">I", data[pos + 4:pos + 8])[0]
        if chunk == b"MTrk":
            _parse_track(data[pos + 8:pos + 8 + length], division, index, parts, state)
            index += 1
        pos += 8 + length
    parts = [p for p in parts if p.notes]
    nn, dd = state["timesig"] or (4, 4)
    return Piece(parts, nn * 4 / dd)


# --- MusicXML --------------------------------------------------------------

def _xml_root(path):
    if path.lower().endswith(".mxl"):
        with zipfile.ZipFile(path) as z:
            container = ET.fromstring(z.read("META-INF/container.xml"))
            return ET.fromstring(z.read(container.find(".//rootfile").get("full-path")))
    return ET.parse(path).getroot()


def read_musicxml(path):
    root = _xml_root(path)
    if root.tag != "score-partwise":
        raise ValueError("only partwise MusicXML is supported")
    names = {sp.get("id"): (sp.findtext("part-name") or "").strip()
             for sp in root.findall("part-list/score-part")}
    title = (root.findtext("work/work-title") or root.findtext("movement-title") or "").strip()
    beats_per_bar = None
    parts = []
    for p in root.findall("part"):
        divisions, measure_start = 1, 0
        notes, tied = [], {}
        for measure in p.findall("measure"):
            pos = last_start = furthest = measure_start
            for el in measure:
                if el.tag == "attributes":
                    if el.findtext("divisions"):
                        divisions = int(float(el.findtext("divisions")))
                    t = el.find("time")
                    if t is not None and beats_per_bar is None:
                        beats = sum(int(x) for x in t.findtext("beats").split("+"))
                        beats_per_bar = beats * 4 / int(t.findtext("beat-type"))
                elif el.tag == "note":
                    if el.find("grace") is not None:
                        continue
                    dur = int(float(el.findtext("duration") or 0))
                    if el.find("chord") is None:
                        last_start, pos = pos, pos + dur
                    pitch = el.find("pitch")
                    if pitch is None:
                        furthest = max(furthest, pos)
                        continue
                    midi = 12 * (int(pitch.findtext("octave")) + 1) + _STEP[pitch.findtext("step")]
                    midi += int(round(float(pitch.findtext("alter") or 0)))
                    ties = {t.get("type") for t in el.findall("tie")}
                    start = last_start / divisions
                    prev = tied.get(midi)
                    if "stop" in ties and prev and abs(prev.start + prev.dur - start) < 1e-6:
                        prev.dur += dur / divisions
                        note = prev
                    else:
                        note = Note(start, dur / divisions, midi)
                        notes.append(note)
                    if "start" in ties:
                        tied[midi] = note
                    else:
                        tied.pop(midi, None)
                    furthest = max(furthest, pos)
                elif el.tag in ("backup", "forward"):
                    d = int(float(el.findtext("duration") or 0))
                    pos += d if el.tag == "forward" else -d
                    furthest = max(furthest, pos)
            measure_start = furthest
        if notes:
            parts.append(Part(names.get(p.get("id")) or p.get("id") or "part", notes))
    return Piece(parts, beats_per_bar or 4.0, title)


# --- typed notes -------------------------------------------------------------

def read_text(text, beats_per_bar=4.0):
    """'C4 D4 E4:2 r G4' -> notes. ':n' is length in beats (fractions ok); r or - is a rest."""
    notes, t = [], 0.0
    for token in text.split():
        name, _, length = token.partition(":")
        dur = float(Fraction(length)) if length else 1.0
        if name.lower() in ("r", "-"):
            t += dur
            continue
        notes.append(Note(t, dur, parse_pitch(name)))
        t += dur
    return Piece([Part("typed notes", notes)], beats_per_bar)


def read_file(path):
    low = path.lower()
    if low.endswith((".mid", ".midi")):
        return read_midi(path)
    if low.endswith((".xml", ".musicxml", ".mxl")):
        return read_musicxml(path)
    raise ValueError("Unsupported file type. Use a .mid, .musicxml or .mxl file.")


# --- picking and cleaning the melody ----------------------------------------

_MELODY_WORDS = ("melody", "vocal", "voice", "vox", "lead", "sing", "violin", "tune", "solo",
                 "flute", "sax", "trumpet", "oboe")


def mono_ratio(notes):
    if len(notes) < 2:
        return 1.0
    ns = sorted(notes, key=lambda n: n.start)
    ok = sum(1 for a, b in zip(ns, ns[1:]) if b.start > a.start + 0.02 and b.start >= a.start + a.dur - 0.1)
    return ok / (len(ns) - 1)


def melody_score(part):
    n = part.notes
    mean = sum(x.pitch for x in n) / len(n)
    score = 3.0 * any(w in part.name.lower() for w in _MELODY_WORDS)
    score += 2.0 * mono_ratio(n) + min(len(n) / 200, 1.0)
    score += 1.0 if 55 <= mean <= 88 else (-2.0 if mean < 48 else 0.0)
    return score if len(n) >= 8 else score - 5


def pick_part(piece):
    return max(range(len(piece.parts)), key=lambda i: melody_score(piece.parts[i]))


def to_melody(notes):
    """Skyline: one note at a time, highest wins on chords, earlier notes cut at the next onset."""
    out = []
    for n in sorted(notes, key=lambda n: (n.start, -n.pitch)):
        if out and n.start - out[-1].start < 0.03:
            continue
        if out and out[-1].start + out[-1].dur > n.start:
            out[-1].dur = n.start - out[-1].start
        out.append(replace(n))
    return out

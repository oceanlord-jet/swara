import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from swara.notes import detect_key, format_swara, parse_key, parse_pitch, swara_of
from swara.readers import pick_part, read_midi, read_musicxml, read_text, to_melody


def var(n):
    out = [n & 0x7F]
    while n >> 7:
        n >>= 7
        out.append((n & 0x7F) | 0x80)
    return bytes(reversed(out))


def midi_bytes(tracks, ppq=480):
    """tracks: list of (name, channel, [(start_beat, dur_beat, pitch)])"""
    chunks = []
    for name, ch, notes in tracks:
        ev = []
        for s, d, p in notes:
            ev.append((round(s * ppq), 1, bytes([0x90 | ch, p, 90])))
            ev.append((round((s + d) * ppq), 0, bytes([0x80 | ch, p, 0])))
        ev.sort(key=lambda e: (e[0], e[1]))
        body = b"\x00\xff\x03" + bytes([len(name)]) + name.encode()
        body += b"\x00\xff\x58\x04\x03\x02\x18\x08"  # 3/4
        t = 0
        for tick, _, msg in ev:
            body += var(tick - t) + msg
            t = tick
        body += b"\x00\xff\x2f\x00"
        chunks.append(b"MTrk" + struct.pack(">I", len(body)) + body)
    return b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), ppq) + b"".join(chunks)


class Names(unittest.TestCase):
    def test_pitch(self):
        self.assertEqual(parse_pitch("C4"), 60)
        self.assertEqual(parse_pitch("D#4"), 63)
        self.assertEqual(parse_pitch("Eb4"), 63)
        self.assertEqual(parse_pitch("bb3"), 58)

    def test_swara(self):
        sa = 63  # D#4
        # semitones above Sa 0..11 in the first octave
        expect = ["S", "r", "R", "g", "G", "m", "M", "P", "d", "D", "n", "N"]
        got = [format_swara(*swara_of(sa + i, sa)) for i in range(12)]
        self.assertEqual(got, expect)
        self.assertEqual(format_swara(*swara_of(sa + 12, sa)), "S\u0307")  # tara Sa
        self.assertEqual(format_swara(*swara_of(sa - 5, sa)), "P\u0323")  # mandra Pa
        self.assertEqual(format_swara(*swara_of(sa + 4, sa), long=True), "G3")

    def test_key(self):
        notes = read_text("C4 E4 G4 C5 D4 F4 E4 D4 C4 G4 E4 C4 B3 C4").parts[0].notes
        self.assertEqual(detect_key(notes), (0, "major"))
        self.assertEqual(parse_key("F# minor"), (6, "minor"))
        self.assertEqual(parse_key("Bb"), (10, "major"))
        self.assertEqual(parse_key("Am"), (9, "minor"))


class Readers(unittest.TestCase):
    def test_midi_picks_melody_and_skips_drums(self):
        mel = [(i, 1, p) for i, p in enumerate([64, 62, 60, 62, 64, 64, 64, 62, 62, 62, 64, 67, 67])]
        chords = [(i * 3, 3, p) for i in range(4) for p in (36, 43, 48)]
        drums = [(i, 0.5, 38) for i in range(10)]
        with tempfile.NamedTemporaryFile(suffix=".mid") as f:
            f.write(midi_bytes([("Piano", 0, chords), ("Melody", 1, mel), ("Drums", 9, drums)]))
            f.flush()
            piece = read_midi(f.name)
        self.assertEqual(len(piece.parts), 2)
        self.assertEqual(piece.beats_per_bar, 3)
        best = piece.parts[pick_part(piece)]
        self.assertIn("Melody", best.name)
        self.assertEqual([n.pitch for n in best.notes], [p for _, _, p in mel])
        self.assertAlmostEqual(best.notes[2].start, 2.0)

    def test_musicxml_ties_chords_rests(self):
        xml = """<?xml version="1.0"?><score-partwise><part-list><score-part id="P1"><part-name>Violin</part-name></score-part></part-list>
        <part id="P1"><measure number="1"><attributes><divisions>2</divisions><time><beats>2</beats><beat-type>4</beat-type></time></attributes>
        <note><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration><tie type="start"/></note>
        <note><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration><tie type="stop"/></note></measure>
        <measure number="2"><note><pitch><step>F</step><alter>1</alter><octave>4</octave></pitch><duration>2</duration></note>
        <note><rest/><duration>2</duration></note></measure>
        <measure number="3"><note><pitch><step>E</step><octave>4</octave></pitch><duration>4</duration></note>
        <note><chord/><pitch><step>G</step><octave>4</octave></pitch><duration>4</duration></note></measure></part></score-partwise>"""
        with tempfile.NamedTemporaryFile("w", suffix=".musicxml") as f:
            f.write(xml)
            f.flush()
            piece = read_musicxml(f.name)
        notes = piece.parts[0].notes
        self.assertEqual(piece.beats_per_bar, 2)
        self.assertEqual([(n.start, n.dur, n.pitch) for n in notes],
                         [(0, 2.0, 60), (2.0, 1.0, 66), (4.0, 2.0, 64), (4.0, 2.0, 67)])
        self.assertEqual([n.pitch for n in to_melody(notes)], [60, 66, 67])  # skyline keeps chord top


if __name__ == "__main__":
    unittest.main()

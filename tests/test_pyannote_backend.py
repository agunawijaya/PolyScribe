"""Uji konversi Annotation pyannote -> SpeakerTurn (brief 36).

Bagian yang bisa diuji TANPA PyTorch: _turns_from_annotation (fungsi murni). Model
& pipeline pyannote adalah dependency plan B (torch ~GB, model ter-gate) — diuji
end-to-end oleh TESTER saat model dibundel, bukan di unit test ringan ini.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from polyscribe.diarization.pyannote_backend import _turns_from_annotation


class _Seg:
    def __init__(self, start, end):
        self.start, self.end = start, end


class _FakeAnnotation:
    """Meniru pyannote Annotation.itertracks(yield_label=True)."""
    def __init__(self, triples):        # (start, end, label)
        self._triples = triples

    def itertracks(self, yield_label=True):
        for s, e, lab in self._triples:
            yield _Seg(s, e), "_", lab


def test_sorts_by_start_and_relabels_contiguous():
    # pyannote bisa memberi label meloncat (SPEAKER_02, SPEAKER_00) & tak terurut.
    ann = _FakeAnnotation([
        (5.0, 6.0, "SPEAKER_02"),
        (0.0, 1.0, "SPEAKER_00"),
        (1.0, 2.0, "SPEAKER_02"),
    ])
    turns = _turns_from_annotation(ann)
    assert [t.start for t in turns] == [0.0, 1.0, 5.0]          # terurut waktu
    # kemunculan pertama = SPEAKER_00, berikutnya SPEAKER_01 (kontigu)
    assert turns[0].speaker == "SPEAKER_00"
    assert turns[1].speaker == "SPEAKER_01"                     # dulu "SPEAKER_02"
    assert turns[2].speaker == "SPEAKER_01"                     # label sama dipetakan sama


def test_drops_zero_and_negative_length():
    ann = _FakeAnnotation([(1.0, 1.0, "A"), (2.0, 1.5, "B"), (3.0, 4.0, "C")])
    turns = _turns_from_annotation(ann)
    assert len(turns) == 1 and turns[0].speaker == "SPEAKER_00"


def test_empty():
    assert _turns_from_annotation(_FakeAnnotation([])) == []


def test_overlap_preserved_as_two_turns():
    # Overlap-aware: dua orang bicara di waktu tumpang-tindih -> DUA turn (tak dilebur).
    ann = _FakeAnnotation([(10.0, 12.0, "SPEAKER_00"), (11.5, 13.0, "SPEAKER_01")])
    turns = _turns_from_annotation(ann)
    assert len(turns) == 2
    assert {t.speaker for t in turns} == {"SPEAKER_00", "SPEAKER_01"}


if __name__ == "__main__":
    import traceback
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
                passed += 1
            except Exception:
                print(f"FAIL {name}")
                traceback.print_exc()
                failed += 1
    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)

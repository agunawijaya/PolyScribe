"""Uji pembersih pasca-diarization (cleanup_turns) + relabel kontigu (merge).

Fokus: over-split ditekan (speaker minor & turn ultra-pendek dilebur), turn
berdampingan ber-speaker sama digabung, dan label akhir benar-benar kontigu.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from polyscribe.diarization.base import SpeakerTurn
from polyscribe.diarization.cleanup import cleanup_turns
from polyscribe.merge import relabel_contiguous, MergedLine


def test_minor_speaker_absorbed():
    # Dua speaker mayor (banyak bicara) + satu blip palsu 0.3s di tengah.
    turns = [
        SpeakerTurn(0.0, 10.0, "SPEAKER_00"),
        SpeakerTurn(10.0, 10.3, "SPEAKER_09"),   # spurious, total 0.3s
        SpeakerTurn(10.3, 20.0, "SPEAKER_01"),
    ]
    out = cleanup_turns(turns, min_turn=1.0, min_speaker_frac=0.05)
    speakers = {t.speaker for t in out}
    assert "SPEAKER_09" not in speakers   # blip terserap
    assert speakers == {"SPEAKER_00", "SPEAKER_01"}


def test_adjacent_same_speaker_merged():
    turns = [
        SpeakerTurn(0.0, 5.0, "SPEAKER_00"),
        SpeakerTurn(5.2, 9.0, "SPEAKER_00"),   # jeda 0.2s, speaker sama
    ]
    out = cleanup_turns(turns, bridge_gap=0.5)
    assert len(out) == 1
    assert out[0].start == 0.0 and out[0].end == 9.0


def test_two_real_speakers_survive():
    # Jangan over-collapse: dua orang yang sama-sama banyak bicara tetap dua.
    turns = [
        SpeakerTurn(0.0, 12.0, "SPEAKER_00"),
        SpeakerTurn(12.0, 25.0, "SPEAKER_01"),
        SpeakerTurn(25.0, 40.0, "SPEAKER_00"),
    ]
    out = cleanup_turns(turns, min_turn=1.0, min_speaker_frac=0.05)
    assert {t.speaker for t in out} == {"SPEAKER_00", "SPEAKER_01"}


def test_relabel_contiguous_fills_gaps():
    # Label meloncat (00, 02, 05) -> harus jadi 00, 01, 02 sesuai kemunculan.
    lines = [
        MergedLine(0.0, 1.0, "SPEAKER_00", "a"),
        MergedLine(1.0, 2.0, "SPEAKER_02", "b"),
        MergedLine(2.0, 3.0, "SPEAKER_05", "c"),
        MergedLine(3.0, 4.0, "SPEAKER_02", "d"),
    ]
    out = relabel_contiguous(lines)
    assert [l.speaker for l in out] == [
        "SPEAKER_00", "SPEAKER_01", "SPEAKER_02", "SPEAKER_01",
    ]


def test_empty_turns():
    assert cleanup_turns([]) == []


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

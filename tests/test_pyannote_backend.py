"""Uji konversi Annotation pyannote -> SpeakerTurn (brief 36).

Bagian yang bisa diuji TANPA PyTorch: _turns_from_annotation (fungsi murni). Model
& pipeline pyannote adalah dependency plan B (torch ~GB, model ter-gate) — diuji
end-to-end oleh TESTER saat model dibundel, bukan di unit test ringan ini.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from polyscribe.diarization.pyannote_backend import (
    _pick_pyannote_device,
    _turns_from_annotation,
)


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


# --- Pemilihan device pyannote (bug user 2026-08 CUDA OOM di RTX 4060 8 GB) ------
# Diuji dengan torch palsu supaya tak butuh CUDA nyata & torch tak perlu ada.

class _FakeCuda:
    def __init__(self, available=True, free_gb=8.0):
        self._available = available
        self._free_bytes = int(free_gb * (1024 ** 3))

    def is_available(self):
        return self._available

    def mem_get_info(self):
        return (self._free_bytes, 8 * (1024 ** 3))


class _FakeTorch:
    def __init__(self, available=True, free_gb=8.0):
        self.cuda = _FakeCuda(available=available, free_gb=free_gb)

    def device(self, kind):
        return f"device:{kind}"      # sentinel yang bisa dibandingkan tanpa torch


class _Cfg:
    def __init__(self, choice="auto", min_free_gb=4.0):
        self.pyannote_device = choice
        self.pyannote_min_free_vram_gb = min_free_gb


def test_pick_device_cpu_when_forced():
    dev = _pick_pyannote_device(_Cfg(choice="cpu"), _FakeTorch(available=True, free_gb=20))
    assert dev == "device:cpu"


def test_pick_device_cpu_when_no_cuda():
    dev = _pick_pyannote_device(_Cfg(choice="auto"), _FakeTorch(available=False))
    assert dev == "device:cpu"


def test_pick_device_cuda_when_forced_and_available():
    dev = _pick_pyannote_device(_Cfg(choice="cuda"), _FakeTorch(available=True, free_gb=1.0))
    # "cuda" dipaksa -> lewati ambang free VRAM (retry-CPU di diarize jadi jaring pengaman).
    assert dev == "device:cuda"


def test_pick_device_auto_picks_cuda_when_vram_ample():
    # 6 GB free >= 4 GB ambang -> CUDA.
    dev = _pick_pyannote_device(_Cfg(choice="auto", min_free_gb=4.0),
                                _FakeTorch(available=True, free_gb=6.0))
    assert dev == "device:cuda"


def test_pick_device_auto_picks_cpu_when_vram_tight():
    # Kasus bug user: RTX 4060 8 GB, sesudah ASR ambil ~3,2 GB, free ~3,5 GB < 4 GB ambang.
    dev = _pick_pyannote_device(_Cfg(choice="auto", min_free_gb=4.0),
                                _FakeTorch(available=True, free_gb=3.5))
    assert dev == "device:cpu"


def test_pick_device_auto_falls_to_cpu_when_mem_get_info_fails():
    # Beberapa driver melempar saat mem_get_info dipanggil terlalu awal — aman: CPU.
    class _BustedCuda(_FakeCuda):
        def mem_get_info(self):
            raise RuntimeError("driver hiccup")
    class _BustedTorch:
        def __init__(self):
            self.cuda = _BustedCuda(available=True, free_gb=8.0)
        def device(self, kind):
            return f"device:{kind}"
    dev = _pick_pyannote_device(_Cfg(choice="auto"), _BustedTorch())
    assert dev == "device:cpu"


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

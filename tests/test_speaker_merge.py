"""Uji gerbang lindung-speaker (brief 35 §3): _protected_agglomerative HARUS
melindungi peserta nyata dari peleburan terlalu agresif, tapi tetap menyerap
fragmen over-split.

Poin inti (ground-truth OPPO): dua speaker SUBSTANTIAL yang kebetulan terdengar
mirip (jarak sedang) TAK boleh dilebur; hanya fragmen kecil yang diserap.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from polyscribe.diarization.sherpa_onnx_backend import SherpaOnnxDiarizer

merge = SherpaOnnxDiarizer._protected_agglomerative

# Titik 1-D di sumbu x -> jarak Euclidean = selisih koordinat (mudah dibaca).
FRAG, MAJOR, PROT = 0.45, 0.35, 0.05      # ambang default brief 35


def _pts(*xs):
    return np.array([[x, 0.0] for x in xs], dtype=np.float64)


def _nclusters(labels):
    return len(set(labels))


def test_two_substantial_far_not_merged():
    # Dua peserta besar, jauh -> tetap dua.
    labels = merge(_pts(0.0, 0.9), [0.4, 0.4], FRAG, MAJOR, PROT)
    assert _nclusters(labels) == 2


def test_two_substantial_moderate_distance_PROTECTED():
    # KASUS OPPO: dua peserta substantial berjarak 0.40 (mirip tapi beda orang).
    # 0.40 >= major_thr(0.35) -> JANGAN dilebur. Ini inti perbaikan brief 35.
    labels = merge(_pts(0.0, 0.40), [0.40, 0.077], FRAG, MAJOR, PROT)
    assert _nclusters(labels) == 2, "peserta substantial mirip keliru dilebur (bug OPPO)"


def test_two_substantial_very_close_merged():
    # Dua cluster substantial yang SANGAT mirip (0.30 < major_thr) = orang sama
    # ter-over-split -> dilebur.
    labels = merge(_pts(0.0, 0.30), [0.20, 0.20], FRAG, MAJOR, PROT)
    assert _nclusters(labels) == 1


def test_small_fragment_absorbed():
    # Fragmen kecil (2%) dekat peserta besar (jarak 0.40 < frag_thr 0.45) -> diserap.
    labels = merge(_pts(0.0, 0.40), [0.40, 0.02], FRAG, MAJOR, PROT)
    assert _nclusters(labels) == 1, "fragmen kecil seharusnya diserap"


def test_small_fragment_far_not_absorbed():
    # Fragmen kecil tapi JAUH (0.60 > frag_thr) -> biarkan (peserta minor distinct).
    labels = merge(_pts(0.0, 0.60), [0.40, 0.02], FRAG, MAJOR, PROT)
    assert _nclusters(labels) == 2


def test_only_merges_never_splits():
    # Jumlah cluster keluaran TAK PERNAH melebihi jumlah masukan (hanya menggabung).
    pts = _pts(0.0, 0.1, 0.2, 0.9, 1.5)
    shares = [0.3, 0.02, 0.02, 0.3, 0.3]
    labels = merge(pts, shares, FRAG, MAJOR, PROT)
    assert _nclusters(labels) <= len(pts)


def test_single_and_empty():
    assert merge(_pts(0.0), [0.5], FRAG, MAJOR, PROT) == [0]
    assert merge(np.zeros((0, 2)), [], FRAG, MAJOR, PROT) == []


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

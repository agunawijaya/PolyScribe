"""Uji isyarat spasial (brief 25): ILD/ITD, deteksi stereo-palsu, clustering.

Sintetis & determinist — tak butuh audio nyata. Yang diuji:
- ITD (GCC-PHAT) menemukan pergeseran waktu yang kita tanam,
- ILD membaca sisi mana yang lebih keras,
- korelasi mengenali stereo-palsu (mono digandakan) -> fitur mati,
- agglomerative memisahkan dua gumpalan & melebur yang identik.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from polyscribe import spatial


def _tone(n, freq=300, sr=16000, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(n) / sr
    return (np.sin(2 * np.pi * freq * t) + 0.05 * rng.standard_normal(n)).astype(np.float32)


def test_itd_recovers_known_shift():
    # R & L digeser 5 sampel satu sama lain -> |ITD| harus ~5. (Tanda = konvensi
    # GCC-PHAT; yang penting BESAR-nya benar & KONSISTEN antar-turn untuk clustering.)
    base = _tone(16000)
    left = base[5:]
    right = base[:-5]
    lag = spatial.gcc_phat(left, right, max_lag=40)
    assert abs(abs(lag) - 5) <= 1, f"ITD meleset: {lag}"
    # konsistensi tanda: geseran berlawanan -> tanda berlawanan
    lag2 = spatial.gcc_phat(right, left, max_lag=40)
    assert np.sign(lag2) == -np.sign(lag) and lag != 0


def test_ild_sign():
    # Kiri 2x lebih keras -> ILD positif (~+6 dB).
    base = _tone(16000)
    assert spatial.ild_db(base * 2.0, base) > 3.0
    assert spatial.ild_db(base, base * 2.0) < -3.0


def test_fake_stereo_detected():
    mono = _tone(16000)
    assert spatial.is_fake_stereo(mono, mono.copy())           # identik -> palsu
    assert spatial.channel_correlation(mono, mono.copy()) > 0.999


def test_true_stereo_not_flagged():
    # Dua sumber beda (fase & derau beda) -> korelasi rendah, bukan palsu.
    left = _tone(16000, freq=300, seed=1)
    right = _tone(16000, freq=440, seed=2)
    assert not spatial.is_fake_stereo(left, right)


def test_turn_features_shape_and_shortguard():
    sr = 16000
    left = _tone(sr * 3, seed=3)
    right = np.concatenate([np.zeros(4, np.float32), left])[:len(left)]
    f = spatial.turn_features(left, right, sr, 0.0, 3.0)
    assert f is not None and len(f) == 2
    # window < 0.5 dtk -> None (tak reliabel)
    assert spatial.turn_features(left, right, sr, 0.0, 0.2) is None


def test_agglomerative_separates_two_blobs():
    rng = np.random.default_rng(7)
    a = rng.standard_normal((6, 4)) * 0.05 + np.array([5, 0, 0, 0])
    b = rng.standard_normal((6, 4)) * 0.05 + np.array([-5, 0, 0, 0])
    labels = spatial.agglomerative(np.vstack([a, b]), threshold=1.0)
    assert len(set(labels)) == 2
    assert len(set(labels[:6])) == 1 and len(set(labels[6:])) == 1


def test_agglomerative_merges_identical():
    x = np.zeros((5, 3))
    labels = spatial.agglomerative(x, threshold=0.5)
    assert len(set(labels)) == 1


def test_agglomerative_edge_cases():
    assert spatial.agglomerative(np.zeros((0, 3)), 1.0) == []
    assert spatial.agglomerative(np.zeros((1, 3)), 1.0) == [0]


def test_zscore_safe_on_constant():
    out = spatial.zscore(np.array([2.0, 2.0, 2.0]))
    assert np.allclose(out, 0.0)


# --- ITD turn-splitter (brief 26) ---

def test_median_filter_kills_single_blip_keeps_nan():
    x = np.array([5, 5, -8, 5, 5], dtype=float)      # -8 tunggal = derau
    sm = spatial.median_filter_ignore_nan(x, 3)
    assert sm[2] == 5.0                               # blip dibunuh
    y = np.array([5, np.nan, np.nan], dtype=float)
    sm2 = spatial.median_filter_ignore_nan(y, 3)
    assert np.isnan(sm2[2])                           # semua-NaN tetap NaN


def test_find_boundaries_rejects_isolated_detects_sustained():
    # +5 stabil, -8 TUNGGAL (derau) di idx3, lalu -8 BERTAHAN (idx6-8), balik +5.
    hop = 0.2
    itds = np.array([5, 5, 5, -8, 5, 5, -8, -8, -8, 5, 5, 5], dtype=float)
    times = np.arange(len(itds)) * hop
    b = spatial.find_itd_boundaries(times, itds, min_jump=6.0, min_run_s=0.35, hop_s=hop)
    # dua batas MENGURUNG interjeksi: masuk (~1.2s) & keluar (~1.8s)
    assert len(b) == 2, b
    assert abs(b[0] - 1.2) < 1e-6 and abs(b[1] - 1.8) < 1e-6
    # tak ada batas di sekitar blip tunggal (0.6s)
    assert all(abs(x - 0.6) > 1e-6 for x in b)


def test_find_boundaries_flat_none():
    times = np.arange(10) * 0.2
    assert spatial.find_itd_boundaries(times, np.full(10, 5.0)) == []


def test_find_boundaries_silence_gap_does_not_false_fire():
    # keheningan (NaN) di tengah aliran +5 tak boleh jadi batas
    itds = np.array([5, 5, np.nan, np.nan, 5, 5], dtype=float)
    times = np.arange(len(itds)) * 0.2
    assert spatial.find_itd_boundaries(times, itds) == []


def test_itd_track_shape_and_silence():
    sr = 16000
    base = _tone(sr * 2, seed=5)
    right = np.concatenate([np.zeros(5, np.float32), base])[:len(base)]
    t, v = spatial.itd_track(base, right, sr, 0.0, 2.0, win_s=0.4, hop_s=0.2)
    assert len(t) == len(v) and len(t) >= 5
    # sinyal senyap -> semua NaN (gerbang energi)
    quiet = np.zeros(sr, np.float32)
    _, vq = spatial.itd_track(quiet, quiet, sr, 0.0, 1.0)
    assert np.all(np.isnan(vq))


if __name__ == "__main__":
    import traceback
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS {name}"); passed += 1
            except Exception:
                print(f"FAIL {name}"); traceback.print_exc(); failed += 1
    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)

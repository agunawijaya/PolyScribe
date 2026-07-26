"""Isyarat spasial dari stereo — informasi arah suara yang selama ini dibuang.

Rekaman ponsel (mic array, mis. OPPO) menyimpan beda halus antar kanal L/R:
  ILD (Interaural Level Difference) = beda level kiri/kanan dalam dB
       -> orang yang lebih dekat ke satu mic terdengar lebih keras di sisi itu.
  ITD (Interaural Time Difference) = beda waktu tiba (sampel), diukur GCC-PHAT
       -> arah datangnya suara (dari kiri / kanan meja).

Probe (prompts/scripts/probe_stereo.py) membuktikan tiap pembicara punya "sidik
arah" yang cukup stabil (rasio pemisahan ILD 1,46 · ITD 1,52 di Std-11). Modul ini
memanennya: fitur per-turn + clustering yang bisa mencampur fitur itu ke embedding
suara SEBELUM mengelompokkan pembicara.

Semua murni numpy — tanpa PyTorch, tanpa scipy, tanpa model baru. Ringan, offline.
"""

import numpy as np


# --- isyarat mentah per potongan L/R -------------------------------------------

def gcc_phat(a: np.ndarray, b: np.ndarray, max_lag: int = 40) -> int:
    """Beda waktu tiba a vs b dalam SAMPEL, via GCC-PHAT (whitened cross-corr).

    PHAT (phase transform) membuang magnitudo, hanya menyisakan fase -> jauh lebih
    tahan gema/dengung ruangan daripada cross-correlation biasa. Nilai + / - =
    a mendahului / tertinggal b. Diklip ke +/-max_lag (arah masuk akal, bukan gema
    jauh). Implementasi acuan dari probe_stereo.py — dipertahankan identik."""
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    if len(a) < 2 or len(b) < 2:
        return 0
    n = 1 << ((len(a) - 1).bit_length() + 1)
    A = np.fft.rfft(a, n)
    B = np.fft.rfft(b, n)
    X = A * np.conj(B)
    X /= np.abs(X) + 1e-10
    cc = np.fft.irfft(X, n)
    cc = np.concatenate((cc[-max_lag:], cc[:max_lag + 1]))
    return int(np.argmax(cc)) - max_lag


def ild_db(left: np.ndarray, right: np.ndarray) -> float:
    """Beda level kiri/kanan dalam dB: 20*log10(rms(L)/rms(R)).

    + = lebih keras di kiri, - = lebih keras di kanan. 1e-9 menjaga dari log(0)."""
    el = float(np.sqrt(np.mean(np.square(left, dtype=np.float64)))) + 1e-9
    er = float(np.sqrt(np.mean(np.square(right, dtype=np.float64)))) + 1e-9
    return 20.0 * np.log10(el / er)


def itd_samples(left: np.ndarray, right: np.ndarray,
                max_lag: int = 40, cap_seconds_sr: int = 0) -> int:
    """ITD = GCC-PHAT(L, R). cap_seconds_sr>0 memotong ke N sampel pertama
    (cukup untuk perkiraan arah, hemat FFT di turn panjang)."""
    if cap_seconds_sr and len(left) > cap_seconds_sr:
        left = left[:cap_seconds_sr]
        right = right[:cap_seconds_sr]
    return gcc_phat(left, right, max_lag=max_lag)


def channel_correlation(left: np.ndarray, right: np.ndarray) -> float:
    """Korelasi Pearson L vs R. ~1.0 = dua kanal identik = stereo PALSU (sumber
    mono digandakan) -> tak ada info arah yang bisa dipanen."""
    l = np.asarray(left, dtype=np.float64)
    r = np.asarray(right, dtype=np.float64)
    n = min(len(l), len(r))
    if n < 2:
        return 1.0
    l, r = l[:n], r[:n]
    ls, rs = l.std(), r.std()
    if ls < 1e-9 or rs < 1e-9:      # satu kanal senyap = anggap tak informatif
        return 1.0
    return float(np.mean((l - l.mean()) * (r - r.mean())) / (ls * rs))


def is_fake_stereo(left: np.ndarray, right: np.ndarray,
                   threshold: float = 0.999) -> bool:
    """True bila L/R praktis identik (korelasi > threshold) -> perlakukan sebagai
    mono, matikan fitur spasial. Aman: lebih baik nonaktif daripada memanen derau."""
    return channel_correlation(left, right) > threshold


# --- fitur per-turn ------------------------------------------------------------

def turn_features(left: np.ndarray, right: np.ndarray, sr: int,
                  start_s: float, end_s: float) -> tuple[float, float] | None:
    """(ILD, ITD) untuk satu giliran bicara [start_s, end_s). None bila potongan
    terlalu pendek untuk andal (< ~0.5 dtk). ITD dihitung dari maks 8 dtk pertama
    (sesuai probe) — cukup untuk perkiraan arah tanpa FFT raksasa."""
    i0 = max(0, int(start_s * sr))
    i1 = min(len(left), int(end_s * sr))
    if i1 - i0 < int(0.5 * sr):
        return None
    a, b = left[i0:i1], right[i0:i1]
    return ild_db(a, b), float(itd_samples(a, b, cap_seconds_sr=sr * 8))


# --- clustering aglomeratif (UPGMA, average linkage) ---------------------------

def agglomerative(vectors: np.ndarray, threshold: float) -> list[int]:
    """Kelompokkan baris `vectors` dengan average-linkage aglomeratif memakai
    jarak Euclidean; gabung pasangan terdekat sampai jarak minimum > threshold.

    Kenapa tulis sendiri: scipy/sklearn tak dibundel (paket harus ramping, offline).
    Update Lance-Williams (UPGMA) menjaga O(n^2) — n turn per rapat kecil (puluhan-
    ratusan), jadi ini instan. Kembalikan label 0..k-1 sesuai urutan turn."""
    X = np.asarray(vectors, dtype=np.float64)
    n = len(X)
    if n == 0:
        return []
    if n == 1:
        return [0]

    # matriks jarak titik-ke-titik, diagonal = inf supaya tak "menggabung diri".
    diff = X[:, None, :] - X[None, :, :]
    D = np.sqrt(np.sum(diff * diff, axis=-1))
    np.fill_diagonal(D, np.inf)

    size = [1] * n
    parent = list(range(n))     # union-find: siapa menyerap siapa
    active = list(range(n))

    while len(active) > 1:
        sub = D[np.ix_(active, active)]
        flat = int(np.argmin(sub))
        ai, bi = divmod(flat, len(active))
        if sub[ai, bi] > threshold:
            break
        ia, ib = active[ai], active[bi]
        na, nb = size[ia], size[ib]
        # jarak klaster-gabungan ke sisanya = rata-rata berbobot (UPGMA).
        for k in active:
            if k == ia or k == ib:
                continue
            D[ia, k] = D[k, ia] = (na * D[ia, k] + nb * D[ib, k]) / (na + nb)
        size[ia] = na + nb
        parent[ib] = ia
        D[ib, :] = np.inf
        D[:, ib] = np.inf
        active.remove(ib)

    def root(x: int) -> int:
        while parent[x] != x:
            x = parent[x]
        return x

    reps: dict[int, int] = {}
    labels = []
    for i in range(n):
        r = root(i)
        if r not in reps:
            reps[r] = len(reps)
        labels.append(reps[r])
    return labels


# --- ITD sebagai PENCARI BATAS giliran (brief 26) ---------------------------
# Arsitektur (diverifikasi Architect): ITD = di MANA pergantian terjadi (tajam),
# embedding = SIAPA orangnya. Jangan campur (itu kegagalan Tahap A). ITD memecah
# turn -> embedding + clustering yang ada mengenali & mengelompokkan.

def itd_track(left: np.ndarray, right: np.ndarray, sr: int,
              start_s: float, end_s: float, win_s: float = 0.4,
              hop_s: float = 0.2, rms_floor: float = 150.0,
              max_lag: int = 40):
    """Jejak ITD per jendela pendek sepanjang [start_s, end_s).

    Kembalikan (times, itds); itd = NaN untuk jendela senyap (rms < rms_floor) —
    JANGAN mengarang arah dari keheningan. Param default = yang diverifikasi
    Architect (win 0.4s, hop 0.2s, floor 150)."""
    win = int(win_s * sr)
    hop = int(hop_s * sr)
    i0 = max(0, int(start_s * sr))
    i1 = min(len(left), int(end_s * sr))
    times, itds = [], []
    i = i0
    while i + win <= i1:
        a, b = left[i:i + win], right[i:i + win]
        rms = float(np.sqrt(np.mean(a.astype(np.float64) ** 2)))
        itds.append(float("nan") if rms < rms_floor
                    else float(gcc_phat(a, b, max_lag=max_lag)))
        times.append(i / sr)
        i += hop
    return np.array(times), np.array(itds)


def median_filter_ignore_nan(x: np.ndarray, k: int = 3) -> np.ndarray:
    """Median filter lebar k yang MENGABAIKAN NaN — membunuh kedipan satu-jendela
    (derau) tanpa mengisi keheningan. Jendela yang semuanya NaN tetap NaN."""
    x = np.asarray(x, dtype=np.float64)
    n = len(x)
    out = np.full(n, np.nan)
    half = k // 2
    for i in range(n):
        seg = x[max(0, i - half):min(n, i + half + 1)]
        seg = seg[~np.isnan(seg)]
        if len(seg):
            out[i] = np.median(seg)
    return out


def find_itd_boundaries(times: np.ndarray, itds: np.ndarray,
                        min_jump: float = 6.0, min_run_s: float = 0.35,
                        hop_s: float = 0.2) -> list[float]:
    """Titik waktu (detik) di mana arah suara BERPINDAH secara BERTAHAN.

    Hanya lapor batas bila perubahan dari level saat ini >= min_jump sampel DAN
    bertahan >= min_run_s (beberapa jendela). Kembali ke level lama = derau,
    dibuang (mis. -8 tunggal di tengah aliran +5). Konservatif: lebih baik lewat
    beberapa batas daripada memecah rapat normal jadi serpihan (RAMBU brief 26).
    Setelah batas dikonfirmasi, level acuan diperbarui -> flip balik (+5 -> -8 ->
    +5) menghasilkan DUA batas, mengurung interjeksi."""
    sm = median_filter_ignore_nan(itds, 3)
    min_run_win = max(1, round(min_run_s / hop_s))

    boundaries: list[float] = []
    cur_level = None        # ITD representatif region stabil sekarang
    cand_val = None         # kandidat level baru yang sedang diuji ketahanannya
    cand_start = None
    cand_count = 0
    for i, v in enumerate(sm):
        if np.isnan(v):
            continue        # senyap: tak memutus level, tak menguatkan kandidat
        if cur_level is None:
            cur_level = v
            continue
        if abs(v - cur_level) >= min_jump:
            if cand_val is not None and abs(v - cand_val) < min_jump:
                cand_val = (cand_val * cand_count + v) / (cand_count + 1)
                cand_count += 1
            else:                       # mulai / ganti kandidat sisi baru
                cand_val, cand_start, cand_count = v, i, 1
            if cand_count >= min_run_win:
                boundaries.append(float(times[cand_start]))
                cur_level = cand_val
                cand_val, cand_start, cand_count = None, None, 0
        else:                            # kembali ke level lama -> kandidat batal
            cand_val, cand_start, cand_count = None, None, 0
    return boundaries


def zscore(values: np.ndarray) -> np.ndarray:
    """Z-score aman (std=0 -> nol). Menyeragamkan skala fitur spasial sebelum
    dicampur ke embedding, supaya ILD (dB) & ITD (sampel) sebanding."""
    v = np.asarray(values, dtype=np.float64)
    sd = v.std()
    if sd < 1e-9:
        return np.zeros_like(v)
    return (v - v.mean()) / sd

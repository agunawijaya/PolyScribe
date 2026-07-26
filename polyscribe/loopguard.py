"""Deteksi output ASR yang macet dalam loop (jaring pengaman terakhir, brief 18).

Prinsip yang tak boleh dilanggar: **user harus TAHU hasilnya rusak.** Kegagalan
senyap (menghasilkan sampah berjam-jam tanpa peringatan) adalah kegagalan terburuk.

Ini bukan pengganti perbaikan inti (`-mc 0` di whisper-cli). Ia jaring pengaman:
kalau loop tetap lolos, kita menandainya di output + memperingatkan user.

Ambang dibuat KONSERVATIF supaya rapat normal (yang memang banyak "Yeah. Okay.
Yes.") tidak ditandai palsu:
  - unit pendek (< min_words kata) diabaikan — backchannel bukan loop;
  - butuh BANYAK pengulangan near-identik berturut-turut sebelum memicu.
"""

import re
from collections import deque


def _normalize(text: str) -> str:
    """Huruf kecil, buang tanda baca, rapatkan spasi — untuk membandingkan makna."""
    t = text.lower()
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _similar(a: str, b: str) -> float:
    """Kemiripan cepat berbasis himpunan kata (Jaccard). Cukup untuk 'near-identik'."""
    if a == b:
        return 1.0
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _max_phrase_repeat(words: list[str], min_len: int = 2, max_len: int = 6) -> int:
    """Berapa kali sebuah frasa pendek berulang BERTURUT-TURUT dalam satu teks.

    Menangkap kasus whisper.cpp mengeluarkan satu segmen berisi frasa yang diulang
    di dalamnya (mis. 'so we have npr okay so we have npr okay ...')."""
    best = 1
    n = len(words)
    for plen in range(min_len, max_len + 1):
        if n < plen * 2:
            break
        i = 0
        while i + plen <= n:
            reps = 1
            while (i + (reps + 1) * plen <= n
                   and words[i:i + plen] == words[i + reps * plen:i + (reps + 1) * plen]):
                reps += 1
            if reps > best:
                best = reps
            i += 1
    return best


def _repeat_run(norm: list[str], start: int, min_len: int, max_len: int):
    """Di posisi `start`, cari frasa pendek yang paling banyak berulang BERTURUT.

    Kembalikan (plen, reps): panjang frasa (kata) dan berapa kali ia berulang
    tepat setelah dirinya sendiri. reps=1 bila tak ada pengulangan di sini."""
    n = len(norm)
    best_plen, best_reps = 0, 1
    for plen in range(min_len, max_len + 1):
        if start + plen * 2 > n:
            break
        reps = 1
        while (start + (reps + 1) * plen <= n
               and norm[start:start + plen]
               == norm[start + reps * plen:start + (reps + 1) * plen]):
            reps += 1
        if reps > best_reps:
            best_reps, best_plen = reps, plen
    return best_plen, best_reps


def collapse_token_repeats(tokens, text_of=lambda x: x,
                           min_len: int = 2, max_len: int = 6, min_repeat: int = 6):
    """Lebur frasa yang berulang BERTURUT-TURUT (>= min_repeat kali) jadi SATU instans.

    `tokens` = daftar apa pun (kata whitespace, objek Word, dst); `text_of` menarik
    teks tiap token untuk dibandingkan. Ambang = ambang loopguard yang SAMA
    (intra_repeat) — jadi hanya pengulangan yang memang dianggap loop yang dipangkas;
    teks normal (termasuk backchannel "Okay. Okay.") tak tersentuh.

    Kembalikan (tokens_terpangkas, terpangkas?)."""
    norm = [_normalize(text_of(t)) for t in tokens]
    n = len(tokens)
    out = []
    i = 0
    trimmed = False
    while i < n:
        plen, reps = _repeat_run(norm, i, min_len, max_len)
        if reps >= min_repeat:
            out.extend(tokens[i:i + plen])      # sisakan satu instans frasa
            i += plen * reps                    # lewati sisa pengulangan
            trimmed = True
        else:
            out.append(tokens[i])
            i += 1
    return out, trimmed


def collapse_repeats(text: str, **kwargs):
    """Versi string: pangkas frasa berulang di dalam satu teks jadi satu instans.

    Kembalikan (teks_baru, terpangkas?). Dipakai untuk jalur fallback level-segmen
    (tanpa word-timestamp)."""
    words = text.split()
    kept, trimmed = collapse_token_repeats(words, **kwargs)
    return " ".join(kept), trimmed


class LoopDetector:
    """Suapi teks unit-per-unit (mis. tiap segmen ASR). `feed()` mengembalikan True
    pada MOMENT sebuah loop pertama kali terdeteksi (onset), bukan tiap unit berulang
    — jadi pemanggil bisa menandai sekali per wilayah loop. Kalau output pulih lalu
    macet lagi, ia bisa memicu lagi.
    """

    def __init__(self, min_words: int = 3, sim: float = 0.85,
                 consec_trigger: int = 6, window: int = 30,
                 unique_ratio: float = 0.30, intra_repeat: int = 6):
        self.min_words = min_words          # unit lebih pendek dari ini diabaikan
        self.sim = sim                      # ambang "near-identik"
        self.consec_trigger = consec_trigger  # berapa near-dupe berturut memicu
        self.window = window                # jendela untuk cek rasio unik
        self.unique_ratio = unique_ratio    # unik/total di bawah ini = loop
        self.intra_repeat = intra_repeat    # pengulangan frasa dalam SATU teks
        self._prev = None
        self._consec = 1
        self._recent = deque(maxlen=window)
        self.in_loop = False
        self.sample = ""                    # contoh teks yang berulang (untuk pesan)

    def feed(self, text: str) -> bool:
        norm = _normalize(text)
        words = norm.split()
        if len(words) < self.min_words:
            # Backchannel pendek: jangan hitung, tapi anggap sinyal "beda" ringan
            # supaya deretan "yeah okay yes" tak dianggap lanjutan loop.
            return False

        # (a) Loop DALAM satu teks (satu segmen berisi frasa berulang).
        if _max_phrase_repeat(words) >= self.intra_repeat:
            return self._fire(text)

        # (b) Loop LINTAS unit: near-identik berturut-turut.
        if self._prev is not None and _similar(norm, self._prev) >= self.sim:
            self._consec += 1
        else:
            self._consec = 1
            if self.in_loop:
                self.in_loop = False   # sudah beda → dianggap pulih
        self._prev = norm

        # (c) Cadangan: rasio unik rendah di jendela bergerak (loop bervariasi/siklik).
        self._recent.append(norm)
        low_variety = (len(self._recent) >= self.window
                       and len(set(self._recent)) / len(self._recent) < self.unique_ratio)

        if not self.in_loop and (self._consec >= self.consec_trigger or low_variety):
            return self._fire(text)
        return False

    def _fire(self, text: str) -> bool:
        self.in_loop = True
        self.sample = text.strip()
        return True

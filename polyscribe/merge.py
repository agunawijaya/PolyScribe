"""Penggabungan ASR + diarization by overlap waktu (rancangan 01 §2.2).

ASR tahu "kapan & apa yang diucapkan". Diarization tahu "kapan siapa bicara".
Kita gabung berdasarkan tumpang-tindih waktu, di level KATA kalau ada word
timestamp (lebih tahan saat dua orang bicara dalam satu segmen ASR), fallback ke
level segmen kalau backend tak memberi kata.
"""

import re
from dataclasses import dataclass

from .asr.base import AsrSegment
from .diarization.base import SpeakerTurn


# Kata yang mengakhiri kalimat: berakhir . ! ? (boleh diikuti kutip/kurung).
_SENT_END = re.compile(r'[.!?]["\'\)\]]*$')


@dataclass
class MergedLine:
    start: float
    end: float
    speaker: str
    text: str


UNKNOWN = "SPEAKER_??"   # dipakai bila diarization kosong sama sekali


def _overlap(a_start, a_end, b_start, b_end) -> float:
    """Panjang tumpang-tindih dua interval waktu (0 kalau tak menyentuh)."""
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def _speaker_for_interval(start, end, turns, prev_speaker) -> str:
    """Pilih speaker untuk sebuah interval [start, end].

    Prioritas: overlap terbesar. Kalau tidak ada yang overlap (kata jatuh di
    celah diarization), pilih giliran dengan titik-tengah terdekat; kalau masih
    ragu, ikut speaker sebelumnya.
    """
    if not turns:
        return prev_speaker or UNKNOWN

    best_speaker = None
    best_overlap = 0.0
    for t in turns:
        ov = _overlap(start, end, t.start, t.end)
        if ov > best_overlap:
            best_overlap = ov
            best_speaker = t.speaker

    if best_speaker is not None:
        return best_speaker

    # Tidak ada overlap: pakai titik-tengah terdekat.
    mid = (start + end) / 2.0
    nearest = min(
        turns,
        key=lambda t: abs(((t.start + t.end) / 2.0) - mid),
    )
    # Kalau benar-benar jauh, lebih baik ikut kata sebelumnya (kontinuitas).
    return prev_speaker or nearest.speaker


def _group_into_lines(tokens) -> list[MergedLine]:
    """tokens = list of (start, end, text, speaker) terurut -> gabung yang
    speaker-nya sama & berurutan jadi satu baris."""
    lines: list[MergedLine] = []
    for start, end, text, speaker in tokens:
        text = text.strip()
        if not text:
            continue
        if lines and lines[-1].speaker == speaker:
            # Sambung ke blok berjalan.
            last = lines[-1]
            last.end = end
            last.text = (last.text + " " + text).strip()
        else:
            lines.append(MergedLine(start=start, end=end, speaker=speaker, text=text))
    return lines


def merge(segments: list[AsrSegment], turns: list[SpeakerTurn]) -> list[MergedLine]:
    """Gabung daftar segmen ASR dengan daftar giliran speaker jadi baris output."""
    # Kumpulkan token: kata bila ada, else segmen utuh sebagai satu token.
    tokens = []
    prev_speaker = None

    for seg in segments:
        if seg.words:
            for w in seg.words:
                sp = _speaker_for_interval(w.start, w.end, turns, prev_speaker)
                prev_speaker = sp
                tokens.append((w.start, w.end, w.text, sp))
        else:
            # Fallback level-segmen: tak ada kata, assign segmen utuh.
            sp = _speaker_for_interval(seg.start, seg.end, turns, prev_speaker)
            prev_speaker = sp
            tokens.append((seg.start, seg.end, seg.text, sp))

    # Token sudah terurut karena segmen ASR terurut; jaga-jaga urutkan lagi.
    tokens.sort(key=lambda t: t[0])
    lines = _group_into_lines(tokens)
    return relabel_contiguous(lines)


def relabel_turns_contiguous(turns: list[SpeakerTurn]) -> list[SpeakerTurn]:
    """Nomori ulang speaker di daftar TURN jadi kontigu sesuai urutan waktu.

    Dipakai pada jalur streaming (incremental write): karena kita tak bisa
    menomori ulang di akhir, label distabilkan di turns lebih dulu. Turns sudah
    terurut waktu, jadi first-appearance = urutan kemunculan di output.
    """
    mapping = {}
    for t in turns:
        if t.speaker not in mapping:
            mapping[t.speaker] = f"SPEAKER_{len(mapping):02d}"
    for t in turns:
        t.speaker = mapping[t.speaker]
    return turns


def _dominant_speaker(start, end, turns, prev_speaker) -> str:
    """Speaker dengan overlap waktu TERBESAR (dijumlah) di rentang [start,end].

    Berbeda dari _speaker_for_interval (yang menang di overlap tunggal terbesar),
    ini menjumlah overlap per-speaker sepanjang rentang — cocok untuk KALIMAT yang
    bisa menyentuh beberapa turn. Kalimat tak pernah dipecah antar-speaker; ia
    utuh diberikan ke pemilik dominan.
    """
    if not turns:
        return prev_speaker or UNKNOWN
    per = {}
    for t in turns:
        ov = _overlap(start, end, t.start, t.end)
        if ov > 0:
            per[t.speaker] = per.get(t.speaker, 0.0) + ov
    if per:
        return max(per, key=per.get)
    # Tak ada overlap (kalimat di celah): titik-tengah terdekat / ikut sebelumnya.
    mid = (start + end) / 2.0
    nearest = min(turns, key=lambda t: abs(((t.start + t.end) / 2.0) - mid))
    return prev_speaker or nearest.speaker


class StreamingMerger:
    """Gabung ASR + diarization di level KALIMAT, streaming & incremental.

    Dua prinsip (dari Track B / ground-truth 09b):
      - **Jangan pernah pecah SATU kalimat antar-speaker.** Kalimat dikelompokkan
        pakai tanda baca akhir + jeda word-timestamp, lalu utuh diberikan ke
        speaker dengan overlap dominan. (Memperbaiki #1: kalimat terpotong.)
      - **Tekan "pulau" speaker super-pendek di antara dua blok speaker SAMA**
        (pola A-[b]-A -> A). Indikator kuat pergantian palsu; aman karena hanya
        menyentuh island di antara speaker identik, TIDAK menyentuh alternasi sah
        A-B-A-B (jadi tak memperparah #2: pertukaran cepat).

    Tetap streaming: kalimat lengkap diproses jadi blok; blok di-emit begitu
    keluar dari jendela lookahead kecil (untuk deteksi island). Kalau run panjang
    terputus, sebagian besar transkrip sudah di disk.
    """

    def __init__(self, turns: list[SpeakerTurn], island_max_s: float = 4.0,
                 sentence_gap_s: float = 1.2, lookahead: int = 2):
        self.turns = turns
        self.island_max_s = island_max_s   # durasi maks sebuah "island"
        self.sentence_gap_s = sentence_gap_s  # jeda yang memaksa batas kalimat
        self.lookahead = lookahead         # blok ditahan utk deteksi island
        self.prev_speaker = None
        self._wordbuf = []   # (start,end,text) menunggu kalimat tuntas
        self._blocks = []    # MergedLine belum di-emit (jendela island)

    def _emit_sentences(self, force: bool):
        """Potong _wordbuf jadi kalimat; kalimat tuntas -> block."""
        sentences = []
        cur = []
        buf = self._wordbuf
        for i, (s, e, txt) in enumerate(buf):
            cur.append((s, e, txt))
            ends = bool(_SENT_END.search(txt.strip()))
            big_gap = (i + 1 < len(buf)) and (buf[i + 1][0] - e > self.sentence_gap_s)
            if ends or big_gap:
                sentences.append(cur)
                cur = []
        # 'cur' = kalimat belum tuntas; tahan (kecuali finish).
        if force and cur:
            sentences.append(cur)
            cur = []
        self._wordbuf = cur

        for sent in sentences:
            ss, se = sent[0][0], sent[-1][1]
            text = " ".join(w[2].strip() for w in sent).strip()
            if not text:
                continue
            sp = _dominant_speaker(ss, se, self.turns, self.prev_speaker)
            self.prev_speaker = sp
            self._append_block(ss, se, sp, text)

    def _append_block(self, ss, se, sp, text):
        if self._blocks and self._blocks[-1].speaker == sp:
            b = self._blocks[-1]
            b.end = se
            b.text = (b.text + " " + text).strip()
        else:
            self._blocks.append(MergedLine(start=ss, end=se, speaker=sp, text=text))

    def _coalesce(self, blocks):
        out = []
        for b in blocks:
            if out and out[-1].speaker == b.speaker:
                out[-1].end = b.end
                out[-1].text = (out[-1].text + " " + b.text).strip()
            else:
                out.append(MergedLine(b.start, b.end, b.speaker, b.text))
        return out

    def _suppress_islands(self):
        """A-[b]-A -> A pada _blocks; ulang sampai stabil lalu coalesce."""
        changed = True
        while changed:
            changed = False
            for i in range(1, len(self._blocks) - 1):
                b = self._blocks[i]
                left, right = self._blocks[i - 1], self._blocks[i + 1]
                if ((b.end - b.start) <= self.island_max_s
                        and left.speaker == right.speaker
                        and left.speaker != b.speaker):
                    b.speaker = left.speaker
                    changed = True
            if changed:
                self._blocks = self._coalesce(self._blocks)

    def feed(self, segment: AsrSegment) -> list[MergedLine]:
        if segment.words:
            for w in segment.words:
                if w.text.strip():
                    self._wordbuf.append((w.start, w.end, w.text))
        elif segment.text.strip():
            # Fallback: tak ada kata -> perlakukan segmen sebagai satu "kalimat".
            self._wordbuf.append((segment.start, segment.end, segment.text))

        self._emit_sentences(force=False)
        self._suppress_islands()
        # Emit blok yang sudah keluar dari jendela lookahead.
        emit = []
        while len(self._blocks) > self.lookahead:
            emit.append(self._blocks.pop(0))
        return emit

    def finish(self) -> list[MergedLine]:
        self._emit_sentences(force=True)
        self._suppress_islands()
        emit, self._blocks = self._blocks, []
        return emit


def relabel_contiguous(lines: list[MergedLine]) -> list[MergedLine]:
    """Nomori ulang speaker jadi kontigu (SPEAKER_00, 01, 02…) sesuai urutan
    kemunculan di HASIL AKHIR.

    Perlu di sini, bukan di diarizer: merge menugaskan kata ke speaker overlap
    terbesar, jadi sebagian label diarizer bisa tak muncul di output → label
    akhir bisa meloncat (00, 02, 04…). Menomori ulang di titik terakhir menjamin
    tak ada lompatan.
    """
    mapping = {}
    for ln in lines:
        if ln.speaker not in mapping:
            mapping[ln.speaker] = f"SPEAKER_{len(mapping):02d}"
    for ln in lines:
        ln.speaker = mapping[ln.speaker]
    return lines

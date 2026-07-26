"""Penulis .txt yang aman untuk teks Arab (RTL).

Format baris: `[hh:mm:ss] SPEAKER_00: teks`. Ditulis utf-8-sig (UTF-8 + BOM)
supaya Notepad Windows langsung mengenalinya sebagai UTF-8 — teks Arab tidak
jadi mojibake. Karakter Arab sudah membawa arah RTL-nya sendiri; kita TIDAK
membalik apa pun, biarkan viewer yang urus bidi.
"""

import os
from pathlib import Path

from .merge import MergedLine


# LRM (Left-to-Right Mark). Disisipkan setelah titik dua supaya di sebagian
# viewer, prefiks jam+label tidak "loncat" ke kanan saat teksnya Arab.
LRM = "‎"


def format_timestamp(seconds: float) -> str:
    """detik -> "hh:mm:ss" (jam ikut ditulis biar rekaman panjang tetap jelas)."""
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_line(line: MergedLine) -> str:
    ts = format_timestamp(line.start)
    return f"[{ts}] {line.speaker}:{LRM} {line.text}"


def render(lines: list[MergedLine]) -> str:
    return "\n".join(format_line(ln) for ln in lines) + ("\n" if lines else "")


def output_path_for(audio_path: str) -> Path:
    """Path .txt di sebelah file audio asli (nama sama, ekstensi .txt)."""
    p = Path(audio_path)
    return p.with_suffix(".txt")


def write_txt(lines: list[MergedLine], audio_path: str) -> str:
    """Tulis hasil di sebelah file audio asli. Kembalikan path .txt-nya."""
    out = output_path_for(audio_path)
    out.write_text(render(lines), encoding="utf-8-sig")
    return str(out)


class IncrementalTxtWriter:
    """Penulis .txt yang meng-append baris begitu final — bukan sekali tulis di
    akhir. Kalau run panjang terputus (mesin sleep/di-kill), transkrip parsial
    tetap ada di disk. Encoding tetap utf-8-sig (BOM di baris pertama).

    Dua pengaman kehilangan data (brief 17 #1):
      1. **Lazy open** — file BARU disentuh saat baris pertama benar-benar siap.
         Kalau run mati sebelum ada baris, `.txt` LAMA (hasil transkrip sebelumnya)
         tetap utuh; kita tak pernah membuka mode "w" yang mengosongkannya.
      2. **Tulis ke `.txt.part` lalu rename atomik** ke `.txt` saat close().
         `os.replace` di Windows atomik → hasil lama tak pernah setengah-tertimpa,
         dan bila run di-kill, transkrip parsial masih bisa diselamatkan dari
         file `.part` yang tertinggal.
    """

    def __init__(self, audio_path: str):
        self.path = output_path_for(audio_path)
        self.part_path = self.path.with_suffix(self.path.suffix + ".part")
        self._fh = None   # dibuka malas di write_line pertama

    def _ensure_open(self) -> None:
        if self._fh is None:
            # utf-8-sig menaruh BOM otomatis saat file dibuka untuk ditulis.
            self._fh = open(self.part_path, "w", encoding="utf-8-sig")

    def write_line(self, line: MergedLine) -> None:
        self._ensure_open()
        self._fh.write(format_line(line) + "\n")
        self._fh.flush()   # pastikan sampai ke disk tiap baris

    def write_note(self, text: str) -> None:
        """Tulis satu baris mentah (bukan baris transkrip) — mis. peringatan loop.
        Ikut mekanisme lazy-open + commit yang sama."""
        self._ensure_open()
        self._fh.write(text + "\n")
        self._fh.flush()

    def reset(self) -> None:
        """Buang isi .part streaming untuk ditulis ULANG dengan hasil word-level
        (brief 27). Dipanggil HANYA setelah run ASR selesai normal — jadi tak ada
        risiko interupsi lagi; re-merge di memori itu cepat. .txt LAMA tetap tak
        tersentuh (belum pernah commit). Tutup & hapus .part; write berikutnya
        lazy-open .part baru (BOM utuh)."""
        if self._fh is not None and not self._fh.closed:
            self._fh.close()
        self._fh = None
        try:
            self.part_path.unlink()
        except FileNotFoundError:
            pass

    def close(self) -> None:
        """Commit: tutup lalu rename atomik .part -> .txt.

        Dipakai pada selesai normal DAN batal rapi (Stop) — di kedua kasus isi
        .part valid sampai titik henti, jadi layak jadi .txt. Kalau belum pernah
        menulis apa pun, tak melakukan apa-apa (.txt lama utuh)."""
        if self._fh is None:
            return
        if not self._fh.closed:
            self._fh.close()
        # Baru sekarang .txt lama tergantikan, dan hanya oleh hasil lengkap-sampai-
        # titik-henti. Rename di Windows atomik.
        os.replace(self.part_path, self.path)

    def discard(self) -> None:
        """Batal-karena-error: tutup handle TANPA rename.

        .txt lama (hasil bagus sebelumnya) dibiarkan utuh; file .part yang berisi
        parsial ditinggalkan supaya masih bisa diselamatkan manual bila perlu."""
        if self._fh is not None and not self._fh.closed:
            self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        # Keluar normal -> commit; keluar karena exception -> jangan timpa .txt.
        if exc and exc[0] is not None:
            self.discard()
        else:
            self.close()

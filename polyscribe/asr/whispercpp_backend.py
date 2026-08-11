"""Backend ASR B — whisper.cpp large-v3 lewat Vulkan (iGPU Radeon 860M).

Dipanggil sebagai SUBPROCESS ke vendor/whisper-cli/whisper-cli.exe, bukan lewat
binding Python. Alasannya (rancangan 01 §1.1): gampang dibundel, kode GPU native
terisolasi dari proses Python (crash tak menyeret app), tak perlu compile binding.

Alur (brief 17 #2): whisper-cli MENCETAK tiap segmen ke stdout SELAGI men-decode
(`[00:00:03.000 --> 00:00:07.000]  teks`), bukan cuma menulis JSON di akhir. Jadi
kita baca stdout baris-per-baris, parse jadi AsrSegment saat muncul, dan langsung
diteruskan ke pipeline untuk di-merge & di-append. Ini membuat perlindungan
interupsi NYATA di jalur Vulkan (default AMD) — bukan cuma di jalur CPU — dan
membuat progress + cuplikan teks GUI benar-benar hidup mengikuti waktu audio.

Trade-off yang disengaja (sesuai brief: "jangan korbankan ketahanan demi presisi
kata"): kita pakai timestamp level-SEGMEN dari stdout, bukan level-kata dari JSON
akhir. Dalam praktik segmen whisper-cli pendek (kecuali window pembuka ~30 dtk),
jadi atribusi pembicara tetap cukup halus, dan merge level-kalimat + island
suppression (Track B) tetap berlaku.
"""

import json
import queue
import re
import subprocess
import threading
from pathlib import Path
from typing import Iterator

from .base import AsrBackend, AsrSegment, Word
from .. import audio
from ..progress import ProgressEvent


# Baris segmen di stdout: "[00:00:03.000 --> 00:00:07.000]   teks di sini".
_SEG_RE = re.compile(
    r"^\[(\d\d):(\d\d):(\d\d)\.(\d\d\d)\s*-->\s*(\d\d):(\d\d):(\d\d)\.(\d\d\d)\]\s*(.*)$"
)
# Baris konfirmasi Vulkan (untuk log/verifikasi jujur backend mana yang dipakai).
_VULKAN_RE = re.compile(r"using Vulkan\d+ backend")


def _is_symbol_only(text: str) -> bool:
    """True bila teks TAK memuat huruf/angka sama sekali (murni tanda baca/simbol).

    Segmen sampah whisper-cli seperti "- - -", "...", ". . ." dibuang; apa pun yang
    mengandung huruf/angka SELALU dipertahankan (tak menyentuh teks nyata)."""
    return not any(c.isalnum() for c in text)


def _words_from_tokens(tokens) -> list:
    """Kelompokkan token BPE whisper-cli jadi KATA dengan stempel waktu.

    Konvensi whisper: token yang teksnya diawali spasi = awal kata baru; token
    tanpa spasi awal (sub-kata / tanda baca seperti '?' ',') menempel ke kata
    berjalan. Token spesial ('[_BEG_]', '[_TT_..]') dilewati. Offsets dalam ms.
    Gabungan teks kata mereproduksi teks segmen (decode sama seperti stdout)."""
    words = []
    cur_text = ""
    cur_start = None
    cur_end = None

    def _flush():
        nonlocal cur_text, cur_start, cur_end
        if cur_start is not None and cur_text.strip():
            end = cur_end if cur_end is not None and cur_end >= cur_start else cur_start
            words.append(Word(start=cur_start, end=end, text=cur_text.strip()))
        cur_text, cur_start, cur_end = "", None, None

    for tok in tokens:
        txt = tok.get("text", "")
        if txt.startswith("[_"):          # token spesial / marker timestamp
            continue
        off = tok.get("offsets", {})
        s = off.get("from", 0) / 1000.0
        e = off.get("to", 0) / 1000.0
        if txt.startswith(" ") or cur_start is None:
            _flush()
            cur_text, cur_start, cur_end = txt, s, e
        else:
            cur_text += txt
            cur_end = e
    _flush()
    return words


def _parse_seg_line(line: str):
    """'[hh:mm:ss.mmm --> hh:mm:ss.mmm] teks' -> (start_s, end_s, teks) | None."""
    m = _SEG_RE.match(line)
    if not m:
        return None
    g = m.groups()
    start = int(g[0]) * 3600 + int(g[1]) * 60 + int(g[2]) + int(g[3]) / 1000.0
    end = int(g[4]) * 3600 + int(g[5]) * 60 + int(g[6]) + int(g[7]) / 1000.0
    text = g[8].strip()
    return start, end, text


class WhisperCppVulkanBackend(AsrBackend):
    name = "whispercpp-vulkan"

    def __init__(self, config):
        self.config = config
        self.exe = Path(config.whispercli_exe)
        self.model = Path(config.whisper_ggml_path)
        self.primary_language = getattr(config, "primary_language", "en")
        self._used_vulkan = False   # diisi dari stderr saat run
        # Word-level refine (brief 27): whisper-cli menulis JSON word-level di
        # samping stream. Diisi HANYA bila run selesai normal (bukan dibatalkan).
        self._json_path = None
        self._completed_ok = False

    def load(self) -> None:
        # Tak ada model yang dimuat ke proses ini — whisper-cli memuatnya sendiri
        # per-run. Cukup pastikan binary & model ada, dengan pesan yang jelas.
        if not self.exe.exists():
            raise FileNotFoundError(
                f"whisper-cli.exe tidak ada di {self.exe}. Siapkan binary Vulkan "
                f"di vendor/whisper-cli/ (lihat brief M1b)."
            )
        if not self.model.exists():
            raise FileNotFoundError(
                f"Model GGML tidak ada di {self.model}. Jalankan "
                f"scripts/download_models.py --only whisper-ggml."
            )

    def transcribe(self, wav_16k_mono_path: str, progress,
                   cancel_event=None) -> Iterator[AsrSegment]:
        self.load()
        self._completed_ok = False
        # JSON word-level ditulis di samping WAV (base tanpa ekstensi -> .json).
        base = str(Path(wav_16k_mono_path).with_suffix(""))
        self._json_path = base + ".json"

        # whisper.cpp mendeteksi SATU bahasa per file (bukan per-window). Untuk
        # konsisten dengan Backend A: "auto" -> biar dia deteksi; selain itu kunci
        # ke bahasa prioritas (default English).
        lang = "auto" if self.primary_language == "auto" else self.primary_language

        # Total durasi untuk menghitung fraksi progress (sama seperti Backend A).
        try:
            total = audio.wav_duration_seconds(wav_16k_mono_path)
        except Exception:
            total = 0.0

        cmd = self._build_cmd(wav_16k_mono_path, base, lang)

        # stdout = segmen (dibaca progresif); stderr = log Vulkan/info. text +
        # bufsize=1 supaya baris tak nge-buffer. Kedua stream dibaca di thread
        # pembaca sendiri -> loop utama bisa cek cancel tiap ~0.2 s (Stop cepat).
        # PENTING (BUG-1 Arab): whisper-cli mencetak teks UTF-8. Tanpa encoding=
        # eksplisit, text=True memakai locale Windows (cp1252) -> byte Arab memicu
        # UnicodeDecodeError di thread pembaca -> run hang & .txt kosong. Kunci
        # UTF-8 + errors="replace" (jangan pernah mati gara-gara satu byte aneh).
        return self._run(cmd, progress, cancel_event, total,
                         wav_16k_mono_path, lang)

    def _build_cmd(self, wav_16k_mono_path: str, base: str, lang: str) -> list:
        """Susun baris perintah whisper-cli. Dipisah dari transcribe() supaya bisa
        diuji unit — flag yang salah/absen pernah lolos diam-diam (asr_initial_prompt
        tak pernah tersambung ke backend ini sampai 2026-08-10)."""
        cmd = [
            str(self.exe),
            "-m", str(self.model),
            "-f", str(wav_16k_mono_path),
            "-l", lang,
            "-t", str(self._threads()),
            # --- Cegah loop halusinasi (brief 18) TANPA membunuh teks (brief 22) ---
            # Default whisper.cpp -mc -1 mewariskan transkrip sebelumnya sebagai
            # prompt chunk berikut; sekali loop mulai ia jadi konteks yang memperkuat
            # diri & TAK pernah pulih (whisper.cpp tak punya prompt_reset_on_temperature
            # seperti faster-whisper). P0 sempat pakai -mc 0 (mati total) — itu membunuh
            # loop TAPI juga tanda baca/akurasi kata → merge runtuh jadi satu blok.
            # Solusi: konteks PENDEK (default 8): cukup untuk tanda baca & granularitas,
            # terlalu pendek jadi bahan bakar loop. loopguard tetap jadi jaring pengaman.
            # PENTING: fallback WAJIB 8, bukan 32 — 32 meloop parah (38 penanda di
            # Std-12). Bila atribut config hilang, jangan diam-diam kembali ke nilai loop.
            "-mc", str(getattr(self.config, "whispercpp_max_context", 8)),
            # Kunci pengaman decoder-fail SECARA EKSPLISIT (jangan andalkan default:
            # bila binary diganti, default bisa beda dan bug ini kembali diam-diam).
            # Fallback temperature DIBIARKAN menyala (jangan pakai --no-fallback).
            "-et", "2.40",     # entropy threshold decoder-fail
            "-lpt", "-1.00",   # log-prob threshold decoder-fail
            "-nth", "0.60",    # no-speech threshold
            "-tpi", "0.20",    # temperature increment untuk fallback
            # Word-level timestamp (brief 27): JSON penuh di samping stream stdout.
            # TAK mengubah decoding/teks stdout (terbukti: stdout identik dgn/tanpa
            # flag ini) — hanya MENAMBAH file JSON dgn stempel waktu per-token untuk
            # re-merge presisi di akhir. Streaming stdout (ketahanan) tetap utuh.
            "-oj", "-ojf",
            "-of", base,
        ]

        # Initial prompt — knob `asr_initial_prompt` SEBELUMNYA hanya tersambung ke
        # faster-whisper, jadi di laptop AMD (yang selalu memakai backend ini) ia
        # diam-diam tak berefek apa pun. Ditemukan 2026-08-10 saat mengejar akar
        # tanda baca yang runtuh. Gunanya: menyuapkan contoh kalimat BERTANDA BACA
        # supaya whisper tetap di pola output yang benar.
        # `--carry-initial-prompt` menyuntik ulang contoh itu di SETIAP jendela,
        # bukan cuma jendela pertama — penting karena tanda baca terbukti runtuh
        # per-wilayah di tengah/akhir file, bukan cuma di awal (rekaman 22: bagus
        # 16-20 per 100 kata di menit 5-35, lalu 0,0 di menit 35-45).
        # Prompt HARUS sebahasa audio — lihat Config.effective_initial_prompt.
        getter = getattr(self.config, "effective_initial_prompt", None)
        prompt = (getter() if callable(getter)
                  else getattr(self.config, "asr_initial_prompt", "") or "").strip()
        if prompt:
            cmd += ["--prompt", prompt]
            if getattr(self.config, "asr_carry_initial_prompt", True):
                cmd += ["--carry-initial-prompt"]
        return cmd

    def _run(self, cmd, progress, cancel_event, total, wav_16k_mono_path, lang):
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        # stderr cuma untuk konfirmasi Vulkan — baca di thread, buang sisanya.
        def _read_stderr():
            for line in proc.stderr:
                if _VULKAN_RE.search(line):
                    self._used_vulkan = True

        threading.Thread(target=_read_stderr, daemon=True).start()

        # stdout -> antrean; loop utama konsumsi dengan timeout supaya responsif
        # terhadap cancel walau tak ada baris baru.
        line_q: queue.Queue = queue.Queue()

        def _read_stdout():
            for line in proc.stdout:
                line_q.put(line)
            line_q.put(None)   # sentinel EOF

        threading.Thread(target=_read_stdout, daemon=True).start()

        cancelled = False
        while True:
            # Batal kooperatif: matikan subprocess. Karena kita sudah men-stream
            # & meng-append segmen selama ini, transkrip PARSIAL sudah aman di
            # disk (beda dari perilaku lama yang cuma menulis di akhir).
            if cancel_event is not None and cancel_event.is_set():
                proc.terminate()
                cancelled = True
                break
            try:
                line = line_q.get(timeout=0.2)
            except queue.Empty:
                continue
            if line is None:
                break   # stdout habis, proses selesai
            parsed = _parse_seg_line(line)
            if parsed is None:
                continue
            start, end, text = parsed
            if not text:
                continue
            # Buang segmen sampah: whisper-cli sesekali mengeluarkan segmen yang
            # ISINYA murni tanda hubung/titik/simbol ("- - -", "...") pada bagian
            # senyap/berisik. Di Std-12 ini ~14,6% segmen. Buang bila TAK ada
            # huruf/angka sama sekali; segmen dengan huruf/angka selalu dipertahankan.
            if _is_symbol_only(text):
                continue
            out = AsrSegment(start=start, end=end, text=text,
                             language=lang, words=[])
            frac = (end / total) if total else 0.0
            progress.emit(ProgressEvent(
                stage="transcribe", fraction=min(max(frac, 0.0), 1.0),
                message="transkripsi (Vulkan)", text_snippet=text,
            ))
            yield out

        proc.wait()
        if cancelled:
            return
        if proc.returncode != 0:
            raise RuntimeError(
                f"whisper-cli gagal (exit {proc.returncode}) untuk {wav_16k_mono_path}"
            )
        # Selesai NORMAL: JSON word-level valid & lengkap -> refine boleh dipakai.
        self._completed_ok = True

    def refine_segments(self):
        """Segmen ASR dengan WORD-LEVEL timestamp dari JSON — atau None.

        Dipanggil pipeline SETELAH stream selesai NORMAL (brief 27). Mengembalikan
        None bila run dibatalkan / JSON tak ada / gagal parse -> pipeline pakai hasil
        streaming level-segmen (aman, tak ada regresi ketahanan). Teks TETAP dari
        decode yang sama (stdout identik), jadi hanya presisi WAKTU yang bertambah;
        merge bisa menempatkan tiap kalimat pada jam yang tepat -> atribusi speaker
        lebih akurat (mis. pertukaran cepat #2)."""
        if not self._completed_ok or not self._json_path:
            return None
        p = Path(self._json_path)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
        finally:
            # JSON hanya file kerja sementara — bersihkan.
            try:
                p.unlink()
            except OSError:
                pass

        lang = "auto" if self.primary_language == "auto" else self.primary_language
        segs = []
        for seg in data.get("transcription", []):
            words = _words_from_tokens(seg.get("tokens", []))
            off = seg.get("offsets", {})
            start = off.get("from", 0) / 1000.0
            end = off.get("to", 0) / 1000.0
            text = (seg.get("text", "") or "").strip()
            if not text or _is_symbol_only(text):
                continue
            segs.append(AsrSegment(start=start, end=end, text=text,
                                   language=lang, words=words))
        return segs or None

    def _threads(self) -> int:
        # Bagian CPU (mel, sampling) tetap butuh thread; sisanya di GPU. Pakai
        # separuh logical core, minimal 4 — angka aman, tak rakus.
        import os
        return max(4, (os.cpu_count() or 8) // 2)

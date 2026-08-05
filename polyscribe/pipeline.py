"""Orkestrasi pipeline: audio -> diar -> asr(stream) -> merge -> .txt.

Urutan sengaja: **diarization dulu** (cepat, ~6× realtime), baru ASR di-stream.
Karena label speaker sudah diketahui sebelum ASR jalan, tiap segmen ASR bisa
langsung digabung & DITULIS INKREMENTAL ke .txt. Kalau run panjang terputus
(mesin sleep/di-kill), transkrip parsial tetap aman di disk — bukan hilang total
karena baru ditulis di akhir.
"""

import os
import tempfile
import time
from dataclasses import dataclass, replace
from pathlib import Path

from . import audio
from .asr import select_asr_backend
from .diarization import select_diarizer, load_diarizer_with_fallback
from .diarization.cleanup import cleanup_turns
from .hardware import detect
from .merge import StreamingMerger, relabel_turns_contiguous, MergedLine
from .formatting import IncrementalTxtWriter, output_path_for, format_timestamp
from .loopguard import LoopDetector, collapse_repeats, collapse_token_repeats
from .progress import ProgressEvent, ProgressSink


# Penanda yang disisipkan saat loop dipangkas — user WAJIB tahu bahwa bagian ini
# diedit otomatis (jangan pernah memangkas diam-diam).
_LOOP_NOTE = ("=== PERINGATAN: kemungkinan loop/halusinasi ASR terdeteksi — "
              "pengulangan otomatis DIPANGKAS (disisakan satu instans). "
              "Periksa bagian ini. ===")


def _cancel_log_path() -> Path:
    """File log kecil untuk melacak siapa yang men-cancel run (bug misterius
    user 2026-08: Mode Cepat berakhir 'Dihentikan' tanpa user pencet Stop).

    Ditaruh di %TEMP% agar tak mengotori repo & tak butuh izin tulis proyek.
    Setiap baris = satu event bersumber (gui_stop / pipeline_saw_cancel / ...).
    Bila Result.cancelled=True tapi log TAK punya baris 'gui_stop' dekat waktunya,
    ada aktor lain yang set cancel_event -> perlu diselidiki."""
    return Path(os.environ.get("TEMP", tempfile.gettempdir())) / "polyscribe_cancel.log"


def log_cancel_event(source: str, detail: str = "") -> None:
    """Tambah satu baris ke log cancel. Aman dipanggil dari proses mana pun
    (parent GUI atau child pipeline) — best-effort, tak boleh menggagalkan run
    kalau file tak bisa ditulis."""
    try:
        line = (f"{time.strftime('%Y-%m-%d %H:%M:%S')} pid={os.getpid()} "
                f"source={source} {detail}\n")
        with open(_cancel_log_path(), "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass  # log rusak/permission — jangan biarkan diagnostik menjatuhkan run.


def _guard_segment(detector, seg):
    """Loopguard atas SATU segmen ASR: deteksi + pangkas. Kembalikan (seg_out, note).

    Dua aksi, pakai deteksi & ambang loopguard yang SAMA (tak ada ambang baru):
      - **Pangkas dalam-segmen**: frasa yang berulang di dalam satu segmen dilebur
        jadi satu instans. Bila ada word-timestamp, dipangkas di level KATA (supaya
        merge word-level ikut bersih); selain itu di level teks.
      - **Tekan lintas-segmen**: setelah loop terdeteksi (onset), segmen kelanjutan
        yang near-identik ditekan (seg_out=None) sampai output pulih.
    note != None hanya saat zona ini benar-benar dipangkas/ditandai -> caller menulis
    penanda PERINGATAN. Teks non-loop tak pernah berubah."""
    if not seg.text:
        return seg, None
    was_in_loop = detector.in_loop
    fired = detector.feed(seg.text)
    # Kelanjutan loop lintas-segmen (sudah di dalam loop, bukan onset) -> tekan penuh.
    # Onset sudah menaruh satu penanda; segmen ulangan berikutnya cukup dibuang.
    if was_in_loop and detector.in_loop and not fired:
        return None, None
    # Pangkas pengulangan DALAM segmen ini.
    if seg.words:
        new_words, trimmed = collapse_token_repeats(seg.words, text_of=lambda w: w.text)
        seg_out = replace(seg, words=new_words) if trimmed else seg
    else:
        new_text, trimmed = collapse_repeats(seg.text)
        seg_out = replace(seg, text=new_text) if trimmed else seg
    note = _LOOP_NOTE if (fired or trimmed) else None
    return seg_out, note


@dataclass
class Result:
    txt_path: str
    lines: list
    duration: float
    speakers: list       # daftar label speaker unik yang muncul
    cancelled: bool = False   # True bila dihentikan user (transkrip parsial)
    loop_detected: bool = False   # True bila terdeteksi loop/halusinasi ASR
    loop_times: list = None       # timestamp (detik) tiap onset loop, untuk pesan


def transcribe_file(audio_path: str, config, sink: ProgressSink,
                    cancel_event=None) -> Result:
    # cancel_event: threading.Event opsional dari GUI. Default None = tak bisa
    # dibatalkan (perilaku lama CLI). Batal itu kooperatif: kita cek di antara
    # segmen ASR, lalu tutup rapi. Karena .txt ditulis inkremental, transkrip
    # parsial tetap aman di disk.
    # Instrumentasi cancel (bug user 2026-08): setiap kali pipeline melihat
    # cancel_event ter-set, catat SEKALI dengan lokasi. Kalau log akhirnya berisi
    # 'pipeline_saw_cancel' tanpa 'gui_stop' terdekat, cancel_event ter-set dari
    # sumber lain (bukan tombol Stop). Flag lokal supaya log tak spam.
    _cancel_logged = {"done": False}

    def _is_cancelled() -> bool:
        set_now = cancel_event is not None and cancel_event.is_set()
        if set_now and not _cancel_logged["done"]:
            log_cancel_event(source="pipeline_saw_cancel",
                             detail=f"first observed in transcribe_file for {audio_path}")
            _cancel_logged["done"] = True
        return set_now

    # Validasi file lebih awal — sebelum emit progress apa pun — supaya tidak
    # muncul "memuat model 0%" sekejap lalu error (membingungkan).
    if not Path(audio_path).exists():
        raise FileNotFoundError(f"File audio tidak ditemukan: {audio_path}")

    caps = detect()

    asr = select_asr_backend(caps, config)
    diarizer = select_diarizer(config)

    # --- Tahap load ---
    sink.emit(ProgressEvent(stage="load", fraction=0.0,
                            message=f"memuat model ({asr.name} + {diarizer.name})"))

    # Decode ke satu WAV 16k mono yang dipakai bersama ASR & diarization.
    work_dir = Path(tempfile.mkdtemp(prefix="polyscribe_"))
    wav16k = str(work_dir / "audio_16k_mono.wav")
    audio.decode_to_16k_mono(audio_path, wav16k)
    duration = audio.wav_duration_seconds(wav16k)

    # Decode juga versi STEREO untuk isyarat arah diarization (brief 25/26). Ini
    # SUPLEMEN — ASR tetap mono. None bila sumber mono / stereo palsu -> diarizer
    # otomatis jalan seperti biasa (tanpa spasial), tak ada yang crash.
    wav_stereo = None
    if getattr(config, "use_spatial_cues", False) or getattr(config, "use_itd_split", False):
        try:
            wav_stereo = audio.decode_to_16k_stereo(
                audio_path, str(work_dir / "audio_16k_stereo.wav"))
        except Exception:
            wav_stereo = None      # gagal decode stereo tak boleh menggagalkan run

    asr.load()
    # Muat diarizer dengan jaring pengaman RUNTIME: kalau pyannote (Akurat) gagal
    # dimuat karena alasan APA PUN (bukan cuma paket absen — itu sudah dicek di UI),
    # jatuh anggun ke sherpa + pesan ramah, JANGAN matikan app (brief 43). diarizer
    # bisa tertukar ke sherpa di sini; sisa pipeline pakai yang dikembalikan.
    diarizer = load_diarizer_with_fallback(diarizer, config, sink)
    sink.emit(ProgressEvent(stage="load", fraction=1.0, message="model siap"))

    # --- Diarization DULU (cepat) supaya label speaker siap sebelum ASR ---
    turns = diarizer.diarize(wav16k, sink, stereo_path=wav_stereo)
    turns = cleanup_turns(
        turns,
        min_turn=getattr(config, "diar_min_turn", 1.0),
        min_speaker_frac=getattr(config, "diar_min_speaker_frac", 0.015),
    )
    # Label distabilkan di depan (kontigu, urutan waktu) — perlu untuk streaming.
    turns = relabel_turns_contiguous(turns)

    txt_path = str(output_path_for(audio_path))

    # Batal sebelum ASR dimulai: belum ada transkrip, kembalikan hasil kosong.
    if _is_cancelled():
        _cleanup_wav(wav16k, work_dir, wav_stereo)
        return Result(txt_path=txt_path, lines=[], duration=duration,
                      speakers=[], cancelled=True)

    # --- ASR di-stream: tiap segmen langsung digabung & ditulis inkremental ---
    merger = StreamingMerger(
        turns,
        island_max_s=getattr(config, "merge_island_max_s", 4.0),
    )
    writer = IncrementalTxtWriter(audio_path)
    detector = LoopDetector()   # jaring pengaman: tandai loop halusinasi (brief 18)
    loop_times: list[float] = []
    lines: list[MergedLine] = []
    cancelled = False
    try:
        for seg in asr.transcribe(wav16k, sink, cancel_event):
            # Jaring pengaman loop: kalau ASR macet mengulang, PANGKAS pengulangannya
            # (sisakan satu instans) & TANDAI di output — jangan diam-diam menghasilkan
            # sampah berjam-jam, tapi juga jangan mencetaknya utuh.
            seg2, note = _guard_segment(detector, seg)
            if note:
                ts = format_timestamp(seg.start)
                writer.write_note(f"[{ts}] {note}")
                loop_times.append(seg.start)
                sink.emit(ProgressEvent(
                    stage="transcribe", fraction=0.0,
                    message=f"PERINGATAN: loop ASR dipangkas di {ts}"))
            if seg2 is not None:
                for line in merger.feed(seg2):
                    writer.write_line(line)
                    lines.append(line)
            # Cek batal di antara segmen (batas kalimat aman untuk berhenti).
            if _is_cancelled():
                cancelled = True
                break
        # Backend bisa balik TANPA segmen sama sekali saat dibatalkan (mis. Vulkan:
        # subprocess dimatikan sebelum sempat menulis apa pun). Loop di atas tak
        # pernah iterasi -> tetap tandai batal di sini.
        if _is_cancelled():
            cancelled = True
        # Tutup blok terakhir yang masih terbuka — juga saat batal, supaya
        # transkrip parsial rapi sampai titik henti.
        for line in merger.finish():
            writer.write_line(line)
            lines.append(line)

        # --- Penghalusan WORD-LEVEL (brief 27) ---
        # Streaming di atas menulis level-SEGMEN (ketahanan interupsi). Bila run
        # SELESAI NORMAL & backend punya word-timestamp (whisper-cli JSON), re-merge
        # dengan presisi kata: tiap KALIMAT ditempatkan pada waktu yang tepat -> merge
        # bisa memberikan interjeksi cepat ke speaker yang benar (#2). Teks TAK berubah
        # (decode sama). Batal/tak didukung -> pakai hasil streaming, tak ada regresi.
        if not cancelled and getattr(config, "use_word_refine", True):
            refined = None
            refine = getattr(asr, "refine_segments", None)
            if callable(refine):
                refined = refine()
            if refined:
                r_lines, r_loop_times = _remerge_wordlevel(
                    refined, turns, config, writer, detector_cls=LoopDetector)
                lines = r_lines
                loop_times = r_loop_times
        # Selesai normal ATAU batal rapi: commit (.part -> .txt) atomik.
        writer.close()
    except BaseException:
        # Error/kill di tengah: JANGAN timpa .txt lama yang mungkin bagus.
        # .part parsial ditinggalkan untuk penyelamatan manual.
        writer.discard()
        raise

    speakers = sorted({ln.speaker for ln in lines})
    if cancelled:
        final_msg = "dihentikan (parsial)"
    elif loop_times:
        final_msg = f"selesai DENGAN PERINGATAN loop ({len(loop_times)}x) -> {txt_path}"
    else:
        final_msg = f"selesai -> {txt_path}"
    sink.emit(ProgressEvent(stage="done", fraction=1.0, message=final_msg))

    _cleanup_wav(wav16k, work_dir, wav_stereo)
    return Result(txt_path=txt_path, lines=lines, duration=duration,
                  speakers=speakers, cancelled=cancelled,
                  loop_detected=bool(loop_times), loop_times=loop_times)


def _remerge_wordlevel(refined, turns, config, writer, detector_cls):
    """Re-merge segmen word-level jadi output final & tulis ULANG .part (brief 27).

    Dipakai hanya pada selesai-normal. Menjalankan merge + loop-detector yang SAMA
    seperti jalur streaming, tapi atas segmen ber-word-timestamp -> atribusi speaker
    per-kalimat lebih presisi. Teks sama (decode identik) jadi peringatan loop juga
    sama. Kembalikan (lines, loop_times)."""
    merger = StreamingMerger(
        turns, island_max_s=getattr(config, "merge_island_max_s", 4.0))
    detector = detector_cls()
    # Kumpulkan output berurutan (note & line) dulu, baru tulis ulang .part sekali.
    items = []            # ("note", str) | ("line", MergedLine)
    loop_times: list[float] = []
    for seg in refined:
        seg2, note = _guard_segment(detector, seg)
        if note:
            ts = format_timestamp(seg.start)
            items.append(("note", f"[{ts}] {note}"))
            loop_times.append(seg.start)
        if seg2 is not None:
            for line in merger.feed(seg2):
                items.append(("line", line))
    for line in merger.finish():
        items.append(("line", line))

    writer.reset()        # buang .part streaming, tulis ulang versi word-level
    lines = []
    for kind, payload in items:
        if kind == "note":
            writer.write_note(payload)
        else:
            writer.write_line(payload)
            lines.append(payload)
    return lines, loop_times


class _QueueProgressSink(ProgressSink):
    """Sink yang menaruh event ke sebuah Queue (thread ATAU antar-proses).

    Dipakai oleh titik-masuk proses terpisah (`run_pipeline_to_queue`) supaya
    progress dari proses anak mengalir balik ke UI induk. ProgressEvent adalah
    dataclass -> picklable, aman lewat multiprocessing.Queue."""

    def __init__(self, q):
        self.q = q

    def emit(self, event: ProgressEvent) -> None:
        self.q.put(("progress", event))


def run_pipeline_to_queue(audio_path, config, out_queue, cancel_event=None) -> None:
    """Titik masuk untuk menjalankan pipeline di PROSES terpisah (anti-freeze GUI).

    Diarization sherpa menahan GIL sampai beberapa menit di file panjang -> kalau
    jalan di thread, UI Tkinter ikut beku ("Not Responding") dan mengundang
    force-quit (baru itu kehilangan data). Menjalankannya di proses lain memberi
    GIL sendiri -> UI induk tetap hidup. Progress & hasil dikirim lewat `out_queue`
    (multiprocessing.Queue). Fungsi ini HARUS top-level (picklable) untuk spawn.

    Kontrak antrean sama seperti jalur thread lama: ("progress", event) selama
    jalan, lalu tepat satu ("done", Result) atau ("error", Exception) di akhir."""
    # Baseline log (bug user 2026-08): catat state awal cancel_event saat child
    # spawn. Kalau sudah True di sini, artinya event ter-set SEBELUM child jalan
    # -> masalah di parent (mis. event ter-reuse dari run sebelumnya). Kalau False,
    # tapi Result akhir cancelled=True, artinya event ter-set di TENGAH jalan.
    initial_set = cancel_event is not None and cancel_event.is_set()
    log_cancel_event(source="pipeline_start",
                     detail=f"initial cancel_event.is_set()={initial_set} for {audio_path}")
    try:
        sink = _QueueProgressSink(out_queue)
        res = transcribe_file(audio_path, config, sink, cancel_event=cancel_event)
        out_queue.put(("done", res))
    except FileNotFoundError as e:
        out_queue.put(("error", e))              # picklable, tipe dipertahankan
    except BaseException as e:                   # pastikan apa pun bisa di-pickle
        out_queue.put(("error", RuntimeError(str(e))))


def _cleanup_wav(wav16k: str, work_dir: Path, wav_stereo: str = None) -> None:
    """Hapus WAV sementara (mono + stereo), sisa JSON word-level, & foldernya
    (best-effort). JSON bisa tertinggal bila run dibatalkan (refine tak dipanggil)."""
    try:
        Path(wav16k).unlink(missing_ok=True)
        if wav_stereo:
            Path(wav_stereo).unlink(missing_ok=True)
        for leftover in work_dir.glob("*"):    # mis. audio_16k_mono.json parsial
            try:
                leftover.unlink()
            except OSError:
                pass
        work_dir.rmdir()
    except OSError:
        pass

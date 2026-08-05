"""Backend ASR A — faster-whisper large-v3 (baseline).

Ini backend yang selalu jalan: CPU int8 di mana pun, atau CUDA float16 kalau
mesinnya NVIDIA. Word-level timestamp aktif supaya merge bisa per kata.

Catatan penting (dari rancangan): JANGAN kunci `language`. large-v3 punya
kemampuan code-switching bawaan; kita biarkan bahasa dideteksi otomatis per
segmen supaya rekaman campur EN/AR/ID tertranskripsi apa adanya.
"""

from typing import Iterator

from .base import AsrBackend, AsrSegment, Word
from ..progress import ProgressEvent


class FasterWhisperBackend(AsrBackend):
    name = "faster-whisper"

    def __init__(self, model_dir, device="cpu", compute_type="int8",
                 primary_language="en"):
        self.model_dir = str(model_dir)
        self.device = device
        self.compute_type = compute_type
        # "en" -> kunci ke English (stabil di awal file); "auto" -> deteksi penuh.
        self.primary_language = primary_language
        self._model = None
        # Cache untuk refine_segments() — dipakai pipeline._remerge_wordlevel
        # SETELAH stream selesai NORMAL. Sebelum brief ini, faster-whisper TAK
        # punya method ini (cuma whispercpp yg punya) — akibatnya jalur presisi
        # word-level tak pernah dipakai di NVIDIA, atribusi speaker jatuh ke
        # streaming yg mengelompokkan per-KALIMAT saja. Word-timestamp sudah
        # dikumpulkan (word_timestamps=True), tinggal expose ke pipeline.
        self._cached_segments: list = []
        self._completed_ok: bool = False

    def load(self) -> None:
        # Import ditunda ke sini supaya `import polyscribe` tidak menyeret
        # ctranslate2 kalau backend ini tak jadi dipakai.
        from faster_whisper import WhisperModel

        # local_files_only=True: wajib offline, tak boleh menyentuh jaringan.
        self._model = WhisperModel(
            self.model_dir,
            device=self.device,
            compute_type=self.compute_type,
            local_files_only=True,
        )

    def transcribe(self, wav_16k_mono_path: str, progress,
                   cancel_event=None) -> Iterator[AsrSegment]:
        if self._model is None:
            self.load()

        # Reset cache tiap run — kalau backend dipakai ulang untuk file berbeda,
        # jangan bocor segmen file sebelumnya ke refine_segments().
        self._cached_segments = []
        self._completed_ok = False

        # PENTING: `multilingual=True` membuat Whisper mendeteksi bahasa ulang
        # PER-WINDOW dan MENGABAIKAN `language` — itu sebabnya pembukaan English
        # Gulf tertebak Melayu walau language="en". Jadi:
        #   - "auto"  -> language=None + multilingual=True  (deteksi penuh,
        #                code-switching bebas; untuk file multibahasa spt SIRA)
        #   - "en"/lain -> language=<kode> + multilingual=False  (kunci bahasa,
        #                stabil di awal file)
        if self.primary_language == "auto":
            lang, multilingual = None, True
        else:
            lang, multilingual = self.primary_language, False

        # Knob VAD & initial_prompt di-inject dari luar (config -> selector). Default
        # backward-compatible: vad_filter=True + tak ada prompt. Bug user 2026-08:
        # audio dgn overlap tinggi + VAD kadang bikin Whisper tak beri titik ->
        # merger kita gagal potong kalimat -> paragraf raksasa. Set vad_filter=False
        # via config.vad_filter untuk uji. initial_prompt = contoh terpunctuasi ->
        # Whisper cenderung ikut pola output tsb.
        vad = bool(getattr(self, "vad_filter", True))
        init_prompt = getattr(self, "initial_prompt", "") or None

        # word_timestamps=True -> tiap segmen bawa daftar kata dgn start/end.
        segments, info = self._model.transcribe(
            wav_16k_mono_path,
            language=lang,
            multilingual=multilingual,
            word_timestamps=True,
            vad_filter=vad,
            initial_prompt=init_prompt,
        )

        total = float(getattr(info, "duration", 0.0)) or 0.0

        for seg in segments:
            # Batal kooperatif: cek sebelum memproses tiap segmen. GeneratorExit
            # saat pemanggil berhenti menarik juga menghentikan iterasi CTranslate2.
            if cancel_event is not None and cancel_event.is_set():
                return

            words = []
            if seg.words:
                for w in seg.words:
                    words.append(Word(start=w.start, end=w.end, text=w.word))

            out = AsrSegment(
                start=seg.start,
                end=seg.end,
                text=seg.text.strip(),
                language=getattr(seg, "language", None) or info.language or "",
                words=words,
            )

            # Simpan salinan untuk refine_segments() akhir-run. AsrSegment adalah
            # dataclass; simpan referensi cukup — tak diubah setelah yield.
            self._cached_segments.append(out)

            # Progress mengikuti posisi waktu audio yang sudah ditranskripsi.
            frac = (seg.end / total) if total else 0.0
            progress.emit(ProgressEvent(
                stage="transcribe",
                fraction=min(max(frac, 0.0), 1.0),
                message="transkripsi",
                text_snippet=out.text,
            ))

            yield out

        # Loop natural exit (tak di-cancel) -> tandai selesai. Kalau pemanggil break
        # atau generator di-GC di tengah, kode ini TAK jalan -> _completed_ok tetap
        # False -> refine_segments() kembalikan None -> tak ada re-merge, streaming
        # output yg sudah di-commit tetap dipakai (ketahanan interupsi terjaga).
        self._completed_ok = True

    def refine_segments(self):
        """Kembalikan semua segmen ASR (dgn word timestamp) untuk re-merge akhir-run.

        Kontrak sama dgn WhisperCppVulkanBackend.refine_segments(): dipanggil
        pipeline SETELAH stream selesai NORMAL. Kalau run dibatalkan/gagal di
        tengah, kembalikan None -> pipeline pakai output streaming yg sudah
        di-commit. Teks TIDAK berubah (decode sama), yang berubah cuma presisi
        penempatan: `_remerge_wordlevel` bisa alokasikan tiap kalimat ke speaker
        yg tepat via word-level overlap, tak lagi terjebak dominan-per-segmen.
        """
        if not self._completed_ok or not self._cached_segments:
            return None
        return list(self._cached_segments)

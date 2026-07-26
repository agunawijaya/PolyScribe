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

        # word_timestamps=True -> tiap segmen bawa daftar kata dgn start/end.
        segments, info = self._model.transcribe(
            wav_16k_mono_path,
            language=lang,
            multilingual=multilingual,
            word_timestamps=True,
            vad_filter=True,          # buang keheningan panjang, lebih rapi & cepat
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

            # Progress mengikuti posisi waktu audio yang sudah ditranskripsi.
            frac = (seg.end / total) if total else 0.0
            progress.emit(ProgressEvent(
                stage="transcribe",
                fraction=min(max(frac, 0.0), 1.0),
                message="transkripsi",
                text_snippet=out.text,
            ))

            yield out

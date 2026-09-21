"""Backend: Google Web Speech via library `speech_recognition`.

Ini yang dipakai markitdown Microsoft. `recognize_google()` tak butuh API key —
dia memakai demo API key hard-coded ke endpoint Chrome Speech Google. Sengaja
disediakan sebagai "pembanding markitdown"; **jangan pakai untuk produksi**.

Batasan-batasan yang membuat backend ini terkonstruksi tak seperti yang lain:
- Tak ada timestamp -> pipeline akan pakai pseudo linear (lihat base.py).
- Tak ada segmen -> seluruh audio dikirim sebagai satu recognize call. Kalau
  klip >~1 menit sering timeout / kembalikan hasil pendek — kita chunk 30 dtk
  untuk memberi progres yg terlihat & menghindari timeout.
- Bahasa hanya English (config `primary_language="en"` mode default cocok);
  bahasa lain tetap dikirim tapi hasilnya seringkali kosong.
"""

import io
import wave
from typing import Iterator

from .base import (
    CloudAsrBackend, CloudAuthError, CloudTransportError,
    AsrSegment, emit_progress, cancelled,
)


# Panjang chunk saat memecah WAV. 30 dtk = kompromi: cukup pendek supaya progres
# terlihat & tak timeout, cukup panjang supaya konteks Whisper... eh, ini bukan
# Whisper. Cukup panjang supaya recognize tak dipenuhi overhead HTTP.
_CHUNK_SECONDS = 30.0


class GoogleWebSpeechBackend(CloudAsrBackend):
    name = "cloud:google_web"
    provider_key = "google_web"
    needs_key = False
    has_diarization = False
    has_timestamps = False

    def load(self) -> None:
        try:
            import speech_recognition   # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "Backend Google Web Speech butuh library `SpeechRecognition`. "
                "Jalankan: pip install -r requirements-cloud.txt"
            ) from e

    def transcribe(self, wav_16k_mono_path: str, progress,
                   cancel_event=None) -> Iterator[AsrSegment]:
        import speech_recognition as sr

        # Pemetaan bahasa PolyScribe -> kode BCP-47 Google.
        lang = getattr(self.config, "primary_language", "en")
        if lang in ("auto", ""):
            lang_tag = "en-US"    # Google Web Speech tak punya auto
        elif lang == "en":
            lang_tag = "en-US"
        elif lang == "ar":
            lang_tag = "ar-EG"    # default Arab regional (kualitasnya buruk pula)
        elif lang == "id":
            lang_tag = "id-ID"
        else:
            lang_tag = lang

        recognizer = sr.Recognizer()

        # Pecah WAV per chunk_seconds jadi buffer WAV terpisah. Kirim satu per
        # satu ke Google, gabung hasilnya dgn offset waktu yg tepat. Ini juga
        # sumber progress: user melihat bar bergerak per chunk selesai.
        with wave.open(wav_16k_mono_path, "rb") as w:
            rate = w.getframerate()
            channels = w.getnchannels()
            sampwidth = w.getsampwidth()
            n_frames = w.getnframes()
            total_dur = n_frames / rate
            frames_per_chunk = int(_CHUNK_SECONDS * rate)

            offset = 0.0
            i = 0
            while offset < total_dur:
                if cancelled(cancel_event):
                    return
                w.setpos(int(offset * rate))
                take = min(frames_per_chunk, n_frames - int(offset * rate))
                if take <= 0:
                    break
                raw = w.readframes(take)

                # Bungkus jadi WAV in-memory (SpeechRecognition perlu WAV file).
                buf = io.BytesIO()
                with wave.open(buf, "wb") as cw:
                    cw.setnchannels(channels)
                    cw.setsampwidth(sampwidth)
                    cw.setframerate(rate)
                    cw.writeframes(raw)
                buf.seek(0)

                text = _recognize_chunk(recognizer, sr, buf, lang_tag)

                chunk_end = offset + take / rate
                if text.strip():
                    yield AsrSegment(
                        start=offset,
                        end=chunk_end,
                        text=text.strip(),
                        language=lang_tag.split("-")[0],
                        words=[],
                    )
                emit_progress(progress, chunk_end / max(total_dur, 1e-9),
                              text[:60])
                offset = chunk_end
                i += 1


def _recognize_chunk(recognizer, sr_module, wav_buf: io.BytesIO,
                     lang_tag: str) -> str:
    """Kirim satu chunk. Diamkan kegagalan per-chunk (Google sering kembalikan
    UnknownValueError untuk audio ambigu/hening) — kembalikan string kosong &
    lanjut. Kegagalan auth/network diangkat sbg exception ramah GUI.

    Sengaja terpisah dari method utama: mudah di-mock di tes tanpa perlu WAV
    beneran (lihat tests/test_cloud_backend_mocked.py)."""
    try:
        with sr_module.AudioFile(wav_buf) as source:
            audio = recognizer.record(source)
        return recognizer.recognize_google(audio, language=lang_tag) or ""
    except sr_module.UnknownValueError:
        return ""    # chunk hening / tak dikenali — normal, bukan error
    except sr_module.RequestError as e:
        # Endpoint tak resmi Google mati / rate-limit / network. Bedakan pesannya.
        msg = str(e).lower()
        if "quota" in msg or "429" in msg or "rate" in msg:
            raise CloudTransportError(
                "Google Web Speech: rate limit / kuota habis. Endpoint ini "
                "adalah demo tak resmi yg dibagi ke semua user library "
                "SpeechRecognition di dunia — coba backend berbayar (Groq/"
                "Deepgram) atau tunggu."
            ) from e
        raise CloudTransportError(
            f"Google Web Speech gagal: {e}. Endpoint ini demo tak resmi, "
            "tidak ada SLA & bisa mati sewaktu-waktu."
        ) from e

"""Uji parsing response satu backend cloud (Deepgram) tanpa memanggil API sungguhan.

Fokus:
- Response Deepgram Nova-3 yg berformat wajar (words + paragraphs.sentences)
  diparse ke list AsrSegment yg tepat.
- Error 401 -> CloudAuthError; 429 -> CloudQuotaError; 5xx -> CloudTransportError.
- refine_segments() mengembalikan segmen yg sama setelah stream selesai NORMAL.
- Cancel di tengah menghentikan iterator.

Tidak menguji tiap provider — pola parsing berbeda per provider. Sampel Deepgram
karena adapter-nya paling kompleks (word-level + sentence grouping).
"""

import io
import os
import sys
import types
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_wav(path: str, seconds: float = 1.0) -> None:
    """WAV mono 16 kHz sunyi untuk umpan adapter (tak dipakai isinya oleh mock)."""
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * seconds))


class _FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or (str(payload) if payload else "")

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _install_fake_requests(response):
    """Pasang modul `requests` palsu yg selalu mengembalikan response tertentu.
    Kembalikan modul palsu untuk inspection."""
    fake = types.ModuleType("requests")

    class RequestException(Exception):
        pass
    fake.RequestException = RequestException

    calls: list[dict] = []

    def post(url, headers=None, params=None, data=None, files=None,
             json=None, timeout=None):
        calls.append({"url": url, "headers": headers, "params": params,
                      "data_len": len(data) if isinstance(data, bytes) else None,
                      "files": files is not None,
                      "json": json, "timeout": timeout})
        return response

    def get(url, headers=None, params=None, timeout=None):
        calls.append({"method": "get", "url": url})
        return response

    fake.post = post
    fake.get = get
    fake._calls = calls

    sys.modules["requests"] = fake
    return fake


def _deepgram_sample_response():
    """Bentuk sederhana response Deepgram: satu paragraph, 2 kalimat, 5 kata."""
    return {
        "results": {
            "channels": [{
                "detected_language": "en",
                "alternatives": [{
                    "transcript": "Hello world. This is Deepgram.",
                    "paragraphs": {
                        "paragraphs": [{
                            "sentences": [
                                {"text": "Hello world.", "start": 0.0, "end": 1.0},
                                {"text": "This is Deepgram.", "start": 1.2, "end": 2.5},
                            ]
                        }]
                    },
                    "words": [
                        {"word": "hello", "punctuated_word": "Hello",
                         "start": 0.0, "end": 0.4},
                        {"word": "world", "punctuated_word": "world.",
                         "start": 0.5, "end": 1.0},
                        {"word": "this", "punctuated_word": "This",
                         "start": 1.2, "end": 1.4},
                        {"word": "is", "punctuated_word": "is",
                         "start": 1.5, "end": 1.7},
                        {"word": "deepgram", "punctuated_word": "Deepgram.",
                         "start": 1.8, "end": 2.5},
                    ]
                }]
            }]
        }
    }


def _fresh_deepgram_backend(response):
    """Instansiasi backend Deepgram dgn requests palsu terpasang & API key
    injected langsung (tanpa keystore)."""
    _install_fake_requests(response)
    # Buang cached module supaya import baru menangkap fake requests.
    for mod in list(sys.modules):
        if mod.startswith("polyscribe.asr.cloud"):
            del sys.modules[mod]
    from polyscribe.asr.cloud import build_backend
    from polyscribe.config import Config
    cfg = Config()
    be = build_backend("deepgram", cfg)
    be._api_key = "fake-key"    # inject langsung, skip load()
    return be


class _NullSink:
    def emit(self, event):
        pass


def test_deepgram_parses_sentences_and_words(tmp_path=None):
    if tmp_path is None:
        import tempfile
        tmp_path = tempfile.mkdtemp()
    wav = os.path.join(str(tmp_path), "in.wav")
    _make_wav(wav, seconds=3.0)

    resp = _FakeResponse(200, _deepgram_sample_response())
    be = _fresh_deepgram_backend(resp)
    segs = list(be.transcribe(wav, _NullSink()))
    assert len(segs) == 2
    assert segs[0].text == "Hello world."
    assert segs[0].start == 0.0 and segs[0].end == 1.0
    assert segs[1].text == "This is Deepgram."
    assert len(segs[0].words) == 2, f"words in seg1: {segs[0].words}"
    assert len(segs[1].words) == 3, f"words in seg2: {segs[1].words}"


def test_deepgram_401_raises_auth_error():
    import tempfile
    wav = os.path.join(tempfile.mkdtemp(), "in.wav")
    _make_wav(wav)

    resp = _FakeResponse(401, text="unauthorized")
    be = _fresh_deepgram_backend(resp)
    from polyscribe.asr.cloud.base import CloudAuthError
    try:
        list(be.transcribe(wav, _NullSink()))
    except CloudAuthError as e:
        assert "API key" in str(e) or "ditolak" in str(e)
        return
    raise AssertionError("401 seharusnya melempar CloudAuthError")


def test_deepgram_429_raises_quota_error():
    import tempfile
    wav = os.path.join(tempfile.mkdtemp(), "in.wav")
    _make_wav(wav)

    resp = _FakeResponse(429, text="rate limit")
    be = _fresh_deepgram_backend(resp)
    from polyscribe.asr.cloud.base import CloudQuotaError
    try:
        list(be.transcribe(wav, _NullSink()))
    except CloudQuotaError:
        return
    raise AssertionError("429 seharusnya melempar CloudQuotaError")


def test_deepgram_5xx_raises_transport_error():
    import tempfile
    wav = os.path.join(tempfile.mkdtemp(), "in.wav")
    _make_wav(wav)

    resp = _FakeResponse(503, text="upstream unavailable")
    be = _fresh_deepgram_backend(resp)
    from polyscribe.asr.cloud.base import CloudTransportError
    try:
        list(be.transcribe(wav, _NullSink()))
    except CloudTransportError:
        return
    raise AssertionError("5xx seharusnya melempar CloudTransportError")


def test_refine_segments_returns_cached_after_normal_completion():
    import tempfile
    wav = os.path.join(tempfile.mkdtemp(), "in.wav")
    _make_wav(wav, seconds=3.0)

    resp = _FakeResponse(200, _deepgram_sample_response())
    be = _fresh_deepgram_backend(resp)

    # Belum jalan -> None
    assert be.refine_segments() is None

    segs = list(be.transcribe(wav, _NullSink()))
    refined = be.refine_segments()
    assert refined is not None
    assert len(refined) == len(segs)


def test_pseudo_segments_for_no_timestamp_provider():
    """base.pseudo_segments_from_text distribusi linear atas kalimat.

    Dipakai backend Google Web Speech yg tak beri timestamp — memastikan merge.py
    tetap dapat waktu masuk akal."""
    from polyscribe.asr.cloud.base import pseudo_segments_from_text
    segs = pseudo_segments_from_text("Hello world. This is test. Final one.", 30.0)
    assert len(segs) == 3
    assert segs[0].start == 0.0
    assert segs[-1].end == 30.0
    # Distribusi merata.
    for i in range(len(segs) - 1):
        assert abs((segs[i + 1].start - segs[i].start) - 10.0) < 0.01


def test_pseudo_segments_handles_arabic_punctuation():
    """Brief 53: _SENT_END termasuk ؟۔ untuk Arab. Pseudo segmenter harus ikut."""
    from polyscribe.asr.cloud.base import pseudo_segments_from_text
    ar = "مرحبا العالم. كيف حالك؟ أنا بخير."
    segs = pseudo_segments_from_text(ar, 15.0, language="ar")
    assert len(segs) == 3, f"Arab 3 kalimat tapi dapat {len(segs)} segmen"


if __name__ == "__main__":
    import traceback
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
                passed += 1
            except Exception:
                print(f"FAIL {name}")
                traceback.print_exc()
                failed += 1
    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)

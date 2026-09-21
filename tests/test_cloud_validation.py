"""Uji validasi ukuran/durasi audio terhadap batas provider cloud.

Batas KERAS = user tak boleh mulai run (mis. Google Cloud 60 dtk). Warning =
boleh lanjut, tapi tampilkan risiko (mis. Google Web rate limit share).

Kita tak butuh ffprobe di tes — monkeypatch `_estimate_duration` untuk beri
angka durasi apa pun yg kita mau. Fokus di logika keputusan, bukan probing.
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _dummy_audio() -> str:
    """Path yang PASTI ada — validasi butuh path exists check."""
    p = Path(tempfile.mkdtemp(prefix="ps_valtest_")) / "dummy.wav"
    p.write_bytes(b"RIFF")   # isinya tak dipakai; validasi cek durasi via probe.
    return str(p)


def _patch_duration(monkey_value: float):
    """Ganti _estimate_duration sementara. Return objek dgn .restore()."""
    from polyscribe.asr.cloud import validation as v
    orig = v._estimate_duration
    v._estimate_duration = lambda _path: monkey_value

    class Ctx:
        def restore(self):
            v._estimate_duration = orig
    return Ctx()


def test_missing_file_errors():
    from polyscribe.asr.cloud import validate_audio
    verd = validate_audio("groq", "C:\\path\\yang\\tak\\ada.wav")
    assert verd.ok is False
    assert "tidak ditemukan" in verd.error.lower() or "tak ditemukan" in verd.error.lower()


def test_unknown_provider_passes_with_warning():
    """Provider tak dikenal -> tak menolak (biar selector yg complain), tapi
    beri warning bahwa batas tak divalidasi."""
    from polyscribe.asr.cloud import validate_audio
    verd = validate_audio("bogus_provider", _dummy_audio())
    assert verd.ok is True
    assert verd.warning


def test_google_cloud_rejects_over_60_seconds():
    """Batas KERAS Google Cloud (sync mode) = 60 dtk. File 90 dtk harus ditolak
    dgn pesan yg menyebut solusinya."""
    from polyscribe.asr.cloud import validate_audio
    ctx = _patch_duration(90.0)
    try:
        verd = validate_audio("google_cloud", _dummy_audio())
    finally:
        ctx.restore()
    assert verd.ok is False, "90 dtk > 60 dtk seharusnya ditolak"
    assert "60" in verd.error
    # Pesan wajib menyebut alternatif — jangan menutup tanpa jalan keluar.
    low = verd.error.lower()
    assert "groq" in low or "deepgram" in low or "provider lain" in low


def test_google_cloud_accepts_under_60_seconds():
    from polyscribe.asr.cloud import validate_audio
    ctx = _patch_duration(45.0)
    try:
        verd = validate_audio("google_cloud", _dummy_audio())
    finally:
        ctx.restore()
    assert verd.ok is True


def test_deepgram_accepts_1_hour_file():
    """Deepgram batas 10 jam / 2 GB. 1 jam sah."""
    from polyscribe.asr.cloud import validate_audio
    ctx = _patch_duration(3600.0)
    try:
        verd = validate_audio("deepgram", _dummy_audio())
    finally:
        ctx.restore()
    assert verd.ok is True


def test_deepgram_rejects_over_10_hours():
    from polyscribe.asr.cloud import validate_audio
    ctx = _patch_duration(11 * 3600.0)
    try:
        verd = validate_audio("deepgram", _dummy_audio())
    finally:
        ctx.restore()
    assert verd.ok is False
    assert "10 jam" in verd.error or "10.00 jam" in verd.error


def test_azure_rejects_over_2_hours():
    """Fast Transcription API = 2 jam."""
    from polyscribe.asr.cloud import validate_audio
    ctx = _patch_duration(3 * 3600.0)
    try:
        verd = validate_audio("azure_speech", _dummy_audio())
    finally:
        ctx.restore()
    assert verd.ok is False
    assert "2 jam" in verd.error or "2.00 jam" in verd.error


def test_groq_auto_chunks_1_hour_file():
    """Groq auto-chunk -> tak ada batas total; file 1 jam sah tanpa warning ketat."""
    from polyscribe.asr.cloud import validate_audio
    ctx = _patch_duration(3600.0)
    try:
        verd = validate_audio("groq", _dummy_audio())
    finally:
        ctx.restore()
    assert verd.ok is True


def test_google_web_warns_on_long_files():
    """Google Web share rate limit dgn semua user library speech_recognition.
    File > 15 mnt = > 30 chunk -> warning ramah tapi bukan blocker."""
    from polyscribe.asr.cloud import validate_audio
    ctx = _patch_duration(20 * 60.0)
    try:
        verd = validate_audio("google_web", _dummy_audio())
    finally:
        ctx.restore()
    assert verd.ok is True
    assert verd.warning
    # Warning harus menyebut rate limit + rekomendasi alternatif.
    low = verd.warning.lower()
    assert "rate" in low or "limit" in low or "kuota" in low
    assert "groq" in low or "deepgram" in low


def test_google_web_no_warning_on_short_files():
    """File pendek Google Web -> aman, tak ada peringatan panjang."""
    from polyscribe.asr.cloud import validate_audio
    ctx = _patch_duration(3 * 60.0)   # 3 menit = 6 chunk = aman
    try:
        verd = validate_audio("google_web", _dummy_audio())
    finally:
        ctx.restore()
    assert verd.ok is True
    # Warning boleh muncul (warn_notes dari registry), tapi bukan yg 'rate limit'
    if verd.warning:
        # Isi harus mengingatkan rate limit sebagai fakta, TIDAK memaksa alternatif.
        assert "50" in verd.warning or "share" in verd.warning.lower() \
               or "kuota" in verd.warning.lower() or "50/hari" in verd.warning \
               or "rate" in verd.warning.lower()


def test_unmeasurable_duration_falls_back_to_warning():
    """Kalau probe durasi gagal (angka 0), validasi TIDAK menolak — pipeline
    tetap coba jalan, tapi kasih warning kalau provider punya batas ketat."""
    from polyscribe.asr.cloud import validate_audio
    ctx = _patch_duration(0.0)
    try:
        verd = validate_audio("google_cloud", _dummy_audio())
    finally:
        ctx.restore()
    assert verd.ok is True         # tak menolak
    assert verd.warning            # tapi kasih tahu batasnya


def test_provider_info_has_limits_set():
    """Sanity: semua provider PUNYA metadata batas (bukan 0 semua)."""
    from polyscribe.asr.cloud import list_providers
    for p in list_providers():
        # Auto-chunk boleh max_size_mb > 0 (batas per-chunk); yg tidak boleh
        # semua-nol adalah provider non-auto — mereka HARUS punya minimal
        # satu batas keras yg dinyatakan.
        if not p.auto_chunks:
            assert p.max_duration_s > 0 or p.max_size_mb > 0, \
                f"{p.key} bukan auto-chunk tapi tak menyatakan batas apapun"


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

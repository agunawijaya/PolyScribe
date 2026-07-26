"""Uji regresi BUG-1 (brief 35): jalur GPU HARUS membaca teks subprocess sebagai
UTF-8, bukan locale Windows (cp1252).

Arab adalah syarat inti proyek. Bug lolos berbulan-bulan karena uji rutin hampir
semuanya Inggris (ASCII murni, aman di cp1252). Mulai sekarang Arab jadi bagian
tetap uji rutin — file ini yang menjaganya.

Bug asli: `subprocess.Popen(cmd, text=True)` tanpa `encoding=` -> Python memakai
cp1252 -> byte UTF-8 Arab memicu UnicodeDecodeError di thread pembaca -> run hang,
.txt kosong. Perbaikan: `encoding="utf-8", errors="replace"`.
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Contoh Arab nyata (dari transkrip SIRA lewat Vulkan): "stasiun konstruksi".
ARABIC = "محطة الإنشاء حسنًا"
_FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "fixtures", "ar_sira_90s.mp3")


def _emit_arabic_bytes_cmd():
    """Perintah python kecil yang mencetak Arab sebagai byte UTF-8 mentah ke stdout
    (meniru whisper-cli yang selalu mengeluarkan UTF-8, apa pun locale OS)."""
    code = "import sys; sys.stdout.buffer.write(%r.encode('utf-8'))" % ARABIC
    return [sys.executable, "-c", code]


def test_utf8_pipe_decodes_arabic():
    # Baca pipe dengan setelan yang SAMA seperti whispercpp_backend (encoding utf-8).
    # Harus round-trip persis, tanpa crash.
    proc = subprocess.Popen(
        _emit_arabic_bytes_cmd(),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    out, _ = proc.communicate(timeout=30)
    assert ARABIC in out, f"Arab tak round-trip lewat pipe UTF-8: {out!r}"


def test_local_cp1252_encoding_breaks_arabic():
    # Bukti akar bug: byte Arab yang SAMA lewat cp1252 (locale Windows lama) TAK
    # pernah menghasilkan Arab yang benar — entah mojibake, entah UnicodeDecodeError.
    proc = subprocess.Popen(
        _emit_arabic_bytes_cmd(),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="cp1252", errors="strict", bufsize=1,
    )
    try:
        out, _ = proc.communicate(timeout=30)
    except UnicodeDecodeError:
        return  # persis kegagalan yang menyebabkan run hang -> bug terbukti
    assert ARABIC not in out, "cp1252 seharusnya merusak Arab, tapi malah benar?"


def test_backend_popen_uses_utf8():
    # Regresi langsung atas KODE kita: whispercpp_backend HARUS meneruskan
    # encoding="utf-8" ke subprocess.Popen. Kalau binary/model tak ada di mesin ini,
    # lewati diam-diam (tetap dijaga oleh dua tes mekanisme di atas).
    from polyscribe.asr import whispercpp_backend as wc
    from polyscribe.config import Config

    backend = wc.WhisperCppVulkanBackend(Config())
    try:
        backend.load()
    except FileNotFoundError:
        return  # tak ada whisper-cli/model di lingkungan ini

    captured = {}
    real_popen = wc.subprocess.Popen

    class _FakePopen:
        def __init__(self, *a, **kw):
            captured.update(kw)
            raise RuntimeError("stop-after-capture")   # jangan benar-benar jalan

    wc.subprocess.Popen = _FakePopen
    try:
        gen = backend.transcribe("nonexistent_16k.wav", _NullSink())
        next(gen)   # picu badan generator sampai Popen dipanggil
    except RuntimeError:
        pass
    finally:
        wc.subprocess.Popen = real_popen

    assert captured.get("encoding") == "utf-8", \
        f"Popen tak dibuka sebagai UTF-8 (BUG-1 kembali!): encoding={captured.get('encoding')!r}"
    assert captured.get("errors") == "replace", \
        "errors='replace' hilang -> satu byte aneh bisa mematikan run"


def test_arabic_fixture_present():
    # Aset Arab wajib ada di tests/fixtures supaya jalur Arab selalu bisa diuji.
    assert os.path.exists(_FIXTURE), (
        f"Fixture Arab hilang: {_FIXTURE}. Uji rutin TIDAK boleh hanya-Inggris "
        f"(brief 35). Buat ulang dari SIRA.mp3 (ffmpeg -ss 0 -t 90).")


class _NullSink:
    def emit(self, *a, **k):
        pass


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

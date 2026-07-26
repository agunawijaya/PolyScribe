# Troubleshooting — PolyScribe

Masalah yang **spesifik ke aplikasi ini** (bukan yang bisa di-Google umum).
Kumpulan dari sesi bootstrap NVIDIA & pengalaman kalibrasi historis.

Cari yang cocok dengan pesan error atau gejala yang kamu alami.

---

## Setup — Windows / Python

### `python.exe` bukan Python beneran

**Gejala:** `python --version` membuka Microsoft Store, atau menghasilkan
Python versi aneh, atau perintah "hang" tanpa output.

**Sebab:** Windows menaruh **stub Python di WindowsApps** yang mengarahkan ke
Microsoft Store. Bukan interpreter Python beneran.

**Solusi:** install Python 3.11 dari winget:
```powershell
winget install --id Python.Python.3.11 --source winget --silent
```
Path resmi: `C:\Users\<user>\AppData\Local\Programs\Python\Python311\python.exe`.
Verifikasi dengan `py -0p`.

**Kenapa 3.11 dan bukan 3.13/3.14:** Python Store bermasalah untuk native lib
& PyInstaller. Wheel `numpy`, `ctranslate2`, `sherpa-onnx` versi yang di-kunci
di `requirements.lock.txt` belum tentu punya wheel untuk 3.13/3.14 → pip akan
coba build dari source dan gagal tanpa toolchain C++.

---

### `pip install` untuk `numpy` / `ctranslate2` build dari source lalu gagal

Kemungkinan besar kamu pakai Python selain 3.11. Lihat di atas.

---

## Runtime — CUDA / NVIDIA

### `RuntimeError: Library cublas64_12.dll is not found or cannot be loaded`

**Gejala:** faster-whisper load model di CUDA sukses, tapi crash saat
`encode()` benar-benar jalan.

**Sebab:** sejak `ctranslate2 4.5`, cuBLAS & cuDNN **tidak dibundel**. Windows
`LoadLibraryW` default hanya melihat PATH — tidak melihat
`os.add_dll_directory`.

**Solusi:**
```powershell
& $py -m pip install -r requirements-cuda.txt
```
Ini install `nvidia-cublas-cu12` + `nvidia-cudnn-cu12` + `torch cu126`. Helper
`_bootstrap_windows_cuda_dlls()` di `polyscribe/__init__.py` akan menambahkan
folder DLL ke `PATH` secara otomatis saat paket di-import.

Kalau sudah install tapi masih error, cek:
```powershell
& $py -c "import site, os; [print(p) for p in site.getsitepackages() if os.path.isdir(p+r'\nvidia\cublas\bin')]"
```
Harus print minimal satu path. Kalau kosong, paket tidak terpasang di venv
yang benar.

---

### `torchcodec` gagal load DLL (banyak `libtorchcodec_core*.dll`)

**Gejala:** warning panjang di stderr saat `--diarizer pyannote`, tapi
pipeline lolos.

**Sebab:** `torchcodec` (ditarik pyannote) butuh binding native FFmpeg yang
setup-nya rumit di Windows. Warning bising tapi tidak fatal.

**Solusi:** **tidak perlu diperbaiki.** `polyscribe/diarization/pyannote_backend.py`
sudah antisipasi ini dengan menyuapkan audio in-memory (`{'waveform': tensor,
'sample_rate': int}`) ke pipeline, bukan lewat path yang butuh torchcodec.
Warning bisa diabaikan.

Kalau kamu ingin menghilangkan noise, filter dengan:
```python
import warnings
warnings.filterwarnings("ignore", message=".*torchcodec.*")
```
di top skrip kamu.

---

### `pip install -r requirements-pyannote.txt` menghapus `torch cu126` dan
### install `torch 2.13.0` (CPU)

**Gejala:** setelah install pyannote, `torch.cuda.is_available()` jadi False
padahal sebelumnya True.

**Sebab:** pyannote.audio 4.x menuntut `torch>=2.13`. Kalau versi cu126 yang
sudah terpasang lebih lama, pip resolver upgrade ke torch terbaru **dari PyPI
default** (yang CPU-only).

**Solusi:** ikuti urutan yang benar (didokumentasikan di header
`requirements-cuda.txt`):
```powershell
& $py -m pip install -r requirements.txt            # jalur inti
& $py -m pip install -r requirements-cuda.txt       # torch cu126 + cublas + cudnn
& $py -m pip install -r requirements-pyannote.txt   # pyannote (torch sudah satisified)
```

Kalau sudah kadung terjadi:
```powershell
& $py -m pip install torch==2.13.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu126 --force-reinstall --no-deps
```

---

### Torch CUDA hanya dukung sampai versi tertentu di index tertentu

**Gejala:** `pip install torch==X.Y.Z --index-url https://download.pytorch.org/whl/cu124`
gagal dengan "No matching distribution found".

**Sebab:** setiap CUDA index (cu118, cu121, cu124, cu126, cu128) punya rentang
versi torch yang berbeda. cu124 topi di `torch 2.6.0`. cu126 lebih baru.

**Cek dulu:**
```powershell
& $py -m pip index versions torch --index-url https://download.pytorch.org/whl/cu126
```
Pilih index yang punya versi yang kamu butuhkan.

---

### `find_spec("pyannote.audio")` raise `ModuleNotFoundError`

Bug ini sudah **diperbaiki** di [polyscribe/diarization/__init__.py](polyscribe/diarization/__init__.py).
Kalau ketemu di fork lama, cara fix: bungkus dengan try/except:
```python
try:
    have_pyannote = importlib.util.find_spec("pyannote.audio") is not None
except ModuleNotFoundError:
    have_pyannote = False
```

`find_spec` pada sub-modul mengimpor parent (`pyannote`) dulu untuk mencari
`audio` di dalamnya — kalau parent-nya tak ada, `ModuleNotFoundError` naik ke
caller (bukan return None).

---

## Runtime — model pyannote

### `download_models.py --only pyannote` gagal 401 Unauthorized

**Sebab:** model pyannote/speaker-diarization-community-1 ter-**gate** di
HuggingFace. Butuh:
1. HF account + access token dari <https://huggingface.co/settings/tokens>
2. Klik **"Agree and access repository"** di
   <https://huggingface.co/pyannote/speaker-diarization-community-1>

**Solusi:** setelah dua langkah di atas:
```powershell
& $py scripts\download_models.py --only pyannote --hf-token hf_xxxxxxxxxxxx
```
Token hanya dipakai sekali saat build. Runtime tetap offline
(`HF_HUB_OFFLINE=1`), tidak butuh token.

---

### Pipeline pyannote crash dengan error `k2_fsa` atau `speechbrain`

**Sebab:** `speechbrain 1.1` lazy-import `speechbrain.integrations.k2_fsa`
saat pipeline dimuat. Kalau paket `k2` tak ada, import itu meledak.

**Solusi:** sudah di-handle otomatis. `polyscribe/diarization/pyannote_backend.py::load()`
mendaftarkan modul `k2` KOSONG (stub) di `sys.modules` sebelum memuat pyannote.

**JANGAN** install `k2` beneran — library FST berat yang butuh build khusus
dan tak dipakai jalur diarization kita sama sekali.

---

### `torchcodec is not installed correctly` → audio decode gagal

Berbeda dari warning yang harmless di atas. Kalau **pipeline betul-betul
berhenti** karena decode gagal, kemungkinan besar audio input format aneh.

**Solusi:** convert ke WAV 16 kHz mono dulu dengan ffmpeg:
```powershell
ffmpeg -i "problematic.m4a" -ar 16000 -ac 1 "problematic.wav"
& $py -m polyscribe.cli "problematic.wav"
```

---

## Runtime — CLI / output

### CLI exit 0 tapi tidak ada `.txt` yang ditulis

**Sebab:** ASR emit 0 segmen (audio terlalu sunyi / VAD Whisper skip semua).
`IncrementalTxtWriter` pakai pola "lazy open" — file `.txt` baru disentuh saat
baris pertama benar-benar siap. Kalau tidak ada baris, `.txt` lama tetap utuh
(atau tidak dibuat sama sekali).

**Ini bukan bug** — sengaja begini supaya run "kosong" tidak menimpa `.txt`
bagus dari run sebelumnya.

**Cek:** apakah audio input punya suara? Coba:
```powershell
ffplay "audio.mp3"
```

---

### `.txt` yang dihasilkan berisi karakter aneh / mojibake

**Sebab:** salah encoding. Aplikasi menulis `utf-8-sig` (BOM). Editor lama
Notepad kadang mis-detect.

**Solusi:** buka dengan Notepad++, VS Code, atau Notepad Windows 11 (modern) —
mereka handle utf-8-sig dengan benar.

---

### Progress bar berantakan di terminal Windows

**Sebab:** carriage return (`\r`) di Progress conflict dengan terminal yang
tidak support ANSI. Aplikasi memaksa UTF-8 (`sys.stdout.reconfigure`), tapi
handling `\r` tergantung terminal.

**Solusi:** pakai **Windows Terminal** (dari Microsoft Store) alih-alih
`cmd.exe` legacy. Atau abaikan visualnya — `.txt` output tetap benar.

---

### Peringatan "loop halusinasi ASR terdeteksi" di `.txt`

**Bukan error.** Whisper kadang macet mengulang frasa yang sama, terutama di
segmen sunyi panjang. Loop guard menangkap ini, pangkas pengulangan
(sisakan satu instans), dan tandai bagian itu dengan `=== PERINGATAN ===`.

Periksa bagian bertanda tersebut secara manual — teks di sekitarnya mungkin
tidak akurat. Ini fitur, bukan bug.

---

## Tests

### <a name="tests-arab-gagal"></a>`test_arabic_encoding.py::test_arabic_fixture_present` gagal

**Sebab:** test mengharapkan fixture `tests/fixtures/ar_sira_90s.mp3`. Folder
`tests/fixtures/` di-`.gitignore` (rekaman tidak masuk repo per NFR-1).

**Solusi:** buat fixture sekali dari audio Arab kamu sendiri:
```powershell
& $py prompts\scripts\make_fixtures.py
```
Butuh source `SIRA.mp3` (atau audio Arab lain — sesuaikan `make_fixtures.py`).

Kalau tidak punya audio Arab dan hanya ingin skip test ini, CI baseline
sebaiknya di-set mengizinkan 74/75 lulus di lingkungan tanpa fixture.

---

### `test_loopguard.py::test_no_false_positive_on_real_std11` "lolos" tapi tanpa assertion nyata

**Ini sengaja.** Test membaca transkrip Std-11 kalau ada; kalau tidak, lewat
diam-diam (jaring pengaman, bukan gerbang keras).

Untuk mengaktifkan gate real-file, set env var sebelum test:
```powershell
$env:POLYSCRIBE_STD11_TRANSCRIPT = "C:\path\to\transcript_q5_0.txt"
& $py tests\test_loopguard.py
```

---

## Path & migrasi

### Repo dipindah ke drive lain, `PolyScribe.bat` klik-dua-kali error

**Sebab:** launcher `.bat` sekarang pakai `%~dp0` (folder .bat itu sendiri),
jadi seharusnya tidak error. Kalau kamu pakai versi lama yang hardcode
`C:\Project\PolyScribe`, pull versi terbaru.

---

### Contoh perintah di doc lama pakai `C:\Project\PolyScribe`

Doc sudah di-update pakai path relatif. Kalau ada yang tersisa, tolong buka
issue — bug docs.

Format yang benar: masuk ke folder repo dulu, lalu perintah pakai path
relatif:
```powershell
cd <path\ke\PolyScribe>
$py = ".\.venv\Scripts\python.exe"
& $py -m polyscribe.cli ...
```

---

## Kalau tidak ada yang cocok

1. Cek [GitHub Issues](../../issues) — mungkin sudah dilaporkan.
2. Buka issue baru pakai template `bug_report.md`. Sertakan:
   - OS + versi
   - Python versi (`py -0p`)
   - GPU + driver (`nvidia-smi` untuk NVIDIA, `dxdiag` untuk AMD)
   - Perintah yang dijalankan
   - Output error lengkap
   - Apakah masalah reproducible?

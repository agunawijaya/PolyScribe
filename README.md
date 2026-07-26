# PolyScribe

Aplikasi desktop Windows untuk **transkripsi + diarization** (siapa bicara kapan)
rekaman rapat, berjalan **sepenuhnya offline**. Mendukung audio **Inggris, Arab,
dan Indonesia** — boleh tercampur dalam satu rekaman.

Hasil akhir: satu file `.txt` (timestamp + label pembicara + teks) di sebelah file
audio aslinya.

```
[00:00:03] Pembicara 1: Selamat pagi semuanya, kita mulai standup hari ini.
[00:00:08] Pembicara 2: Oke, dari sisi backend kemarin sudah selesai integrasi...
```

> **Catatan privasi & ukuran repo:** repositori ini **tidak** menyertakan model AI
> (berukuran GB), binary native, maupun rekaman/transkrip asli. Anda mengunduh
> model sendiri sekali di awal (lihat [Unduh model](#3-unduh-model)). Semuanya dari
> sumber resmi — bukan dari repo ini.

---

## Fitur

- **Offline penuh.** Tidak ada panggilan cloud, tidak ada login/token di jalur utama.
- **Auto-detect jumlah pembicara.** Tidak perlu memasukkan jumlah pembicara manual.
- **Multi-bahasa & campur bahasa** dalam satu rekaman (EN / AR / ID).
- **Dua mode diarization** yang bisa ditukar:
  - **Akurat (`pyannote`)** — default, overlap-aware, memisahkan pertukaran cepat.
  - **Cepat (`sherpa`)** — cadangan ringan berbasis CPU; fallback otomatis bila
    model pyannote/PyTorch tidak terpasang (aplikasi tidak pernah crash).
- **Multi-hardware dari satu kode sumber**, dipilih lewat deteksi runtime:
  - GPU **NVIDIA** → CUDA (cepat).
  - iGPU **AMD Radeon** → Vulkan lewat `whisper.cpp`.
  - **CPU** int8 → baseline universal yang selalu jalan.
- **GUI sederhana** untuk pengguna non-teknis (progress hidup + tombol Stop) dan
  **CLI** untuk pemakaian lanjutan/batch.

---

## Persyaratan

- **Windows 10/11**
- **Python 3.11** (disarankan; bukan Python 3.13 dari Microsoft Store — Store
  bermasalah untuk native lib)
- Ruang disk ± **5–6 GB** untuk model
- Opsional: GPU NVIDIA (CUDA) atau iGPU AMD (Vulkan) untuk pemrosesan lebih cepat

---

## Instalasi

### 1. Clone repositori

```powershell
git clone https://github.com/<user>/PolyScribe.git
cd PolyScribe
```

### 2. Buat virtual environment & pasang dependency

```powershell
py -3.11 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

> Untuk reproduksi versi persis seperti mesin pengembang, gunakan
> `requirements.lock.txt`.

### 3. Unduh model

Model **tidak** ada di repo — unduh sekali dengan skrip bawaan (perlu internet saat
ini saja; setelah itu runtime sepenuhnya offline):

```powershell
$py = ".\.venv\Scripts\python.exe"

# Model inti (plan A): faster-whisper large-v3 + diarization sherpa + GGML Vulkan
& $py scripts\download_models.py

# (opsional) hanya sebagian, mis. model Vulkan saja:
& $py scripts\download_models.py --only whisper-ggml
```

Skrip mengunduh langsung dari sumber resmi:

| Model | Sumber | Tujuan |
|-------|--------|--------|
| faster-whisper large-v3 (CTranslate2) | Hugging Face `Systran/faster-whisper-large-v3` | `models/faster-whisper-large-v3/` |
| Diarization segmentation + embedding | GitHub rilis `k2-fsa/sherpa-onnx` | `models/diarization/` |
| whisper.cpp GGML large-v3 (q5_0) | Hugging Face `ggerganov/whisper.cpp` | `models/whisper/` |

> Bila unduhan menggantung di 0 byte, matikan backend Xet:
> `` $env:HF_HUB_DISABLE_XET = "1" `` (skrip sudah menyetel ini secara default).

### 4. (Opsional) Mode Akurat — pyannote

Mode default sudah pyannote **jika** modelnya tersedia; bila tidak, aplikasi
otomatis memakai mode Cepat. Untuk mengaktifkan mode Akurat:

```powershell
# Tambahan PyTorch CPU (~ ratusan MB) — sengaja dipisah dari jalur inti
& $py -m pip install -r requirements-pyannote.txt

# Terima lisensi model di halaman HF-nya dulu, lalu unduh sekali dengan token HF:
& $py scripts\download_models.py --only pyannote --hf-token <TOKEN_HF>
```

Terima lisensi di:
<https://hf.co/pyannote/speaker-diarization-community-1>

Token HF **hanya** dipakai untuk unduhan build ini. **Runtime tetap offline tanpa
akun/token** (`HF_HUB_OFFLINE`).

### 5. Vulkan (khusus laptop AMD, opsional)

Jalur cepat untuk iGPU AMD Radeon memakai `whisper.cpp` (Vulkan). Binary-nya
**tidak** ikut di repo; taruh manual di `vendor/whisper-cli/` (whisper-cli.exe + DLL
Vulkan). Tanpa ini aplikasi tetap jalan — otomatis fallback ke CPU.

---

## Pemakaian

### GUI (paling mudah)

```powershell
& .\.venv\Scripts\python.exe -m polyscribe.gui
```

Atau klik dua kali **`PolyScribe.bat`** (peluncur; asumsikan proyek di
`C:\Project\PolyScribe` — sesuaikan bila lokasinya beda).

### CLI

```powershell
$py = ".\.venv\Scripts\python.exe"

# Transkripsi satu file (default = mode Akurat/pyannote):
& $py -m polyscribe.cli "rekaman.mp3"

# Mode Cepat (sherpa):
& $py -m polyscribe.cli "rekaman.mp3" --diarizer sherpa

# File multibahasa (auto-deteksi bahasa per segmen):
& $py -m polyscribe.cli "rekaman.mp3" --language auto

# Paksa CPU (nonaktifkan Vulkan):
& $py -m polyscribe.cli "rekaman.mp3" --no-vulkan
```

Output `.txt` ditulis di folder yang sama dengan file audio.

---

## Struktur proyek (ringkas)

```
polyscribe/     kode aplikasi (pipeline, ASR, diarization, GUI, CLI)
  asr/          backend ASR (faster-whisper, whisper.cpp Vulkan)
  diarization/  backend diarization (sherpa-onnx, pyannote) — pluggable
models/          model AI (TIDAK di-commit — unduh via scripts/)
vendor/          binary native Vulkan (TIDAK di-commit — siapkan manual)
scripts/         download_models.py, benchmark, tools
tests/           unit test
```

Lihat [ABOUT.md](ABOUT.md) untuk latar belakang, arsitektur, dan ruang lingkup.

---

## Ruang lingkup v1

v1 dipakai langsung dari virtual environment (belum dipaket jadi `.exe`).
Packaging installer, profil build NVIDIA, dan distribusi ditunda ke tahap
berikutnya. Detail di [ABOUT.md](ABOUT.md).

---

## Lisensi

Belum ditetapkan. Tambahkan file `LICENSE` sebelum mendistribusikan ulang. Model
pihak ketiga (Whisper, pyannote, sherpa-onnx) tunduk pada lisensinya
masing-masing.

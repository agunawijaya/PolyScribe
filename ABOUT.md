# About PolyScribe

PolyScribe adalah aplikasi desktop Windows untuk **transkripsi dan diarization**
(memisahkan "siapa berbicara kapan") rekaman rapat, yang berjalan **sepenuhnya
offline** di laptop pribadi. Dibuat untuk kebutuhan rapat berbahasa **Inggris,
Arab, dan Indonesia** yang sering tercampur dalam satu rekaman.

## Tujuan

Mengubah satu file audio rapat menjadi satu transkrip `.txt` yang rapi —
lengkap dengan timestamp dan label pembicara — tanpa mengirim apa pun ke cloud.
Privasi rekaman rapat adalah alasan utama aplikasi ini offline penuh.

## Cara kerja (pipeline)

```
audio  ->  decode 16k mono  ->  ( transkripsi  ||  diarization )
       ->  merge berdasarkan overlap waktu  ->  tulis .txt di sebelah audio
```

Dua titik dibuat **pluggable** lewat interface, sehingga backend bisa ditukar
tanpa membongkar aplikasi:

- **ASR (`AsrBackend`)** — mesin transkripsi.
- **Diarization (`Diarizer`)** — mesin pemisah pembicara.

## Multi-hardware, satu kode sumber

Aplikasi wajib jalan di dua jenis laptop lewat **satu kode sumber**; yang berbeda
hanya binary/dependency yang dibundel. Backend dan device dipilih lewat **deteksi
runtime**, bukan di-hard-code per vendor:

| Prioritas | Hardware | Jalur |
|-----------|----------|-------|
| 1 | GPU NVIDIA | faster-whisper + CUDA (cepat) |
| 2 | iGPU AMD Radeon | whisper.cpp + Vulkan |
| 3 | CPU apa pun | faster-whisper int8 (baseline universal) |

## Pilihan diarization

- **Akurat — `pyannote` (default).** Overlap-aware, lebih baik memisahkan
  pertukaran cepat antar pembicara. Menambah PyTorch (dipisah di
  `requirements-pyannote.txt`), sekitar 2,5× lebih lambat, embedding di CPU
  (otomatis CUDA di laptop NVIDIA).
- **Cepat — `sherpa` (sherpa-onnx).** Berbasis CPU, ringan. Menjadi **fallback
  otomatis** bila model/PyTorch pyannote tidak tersedia — aplikasi tidak pernah
  crash.

Jumlah pembicara **selalu auto-detect**; tidak ada input manual. Model pyannote
diunduh sekali saat penyiapan (perlu token HF + persetujuan lisensi); **runtime
tetap offline tanpa akun** (`HF_HUB_OFFLINE`).

## Ruang lingkup v1

v1 ditujukan untuk **dipakai sendiri** langsung dari virtual environment — **bukan**
untuk distribusi massal. Yang sudah selesai: core CLI, kualitas diarization, serta
GUI dengan progress hidup.

**Ditunda ke tahap berikutnya:** packaging `.exe` (PyInstaller), build profile
per-hardware (installer terpisah AMD/Vulkan vs NVIDIA/CUDA), manifest model, dan
distribusi. Untuk v1, menjalankan dari `.venv` sudah cukup.

## Batasan desain (prinsip)

- **Offline penuh** — tidak ada panggilan cloud, tidak ada login/token di jalur utama.
- **Tidak hard-code satu vendor** — pemilihan backend lewat deteksi runtime.
- **Modul diarization pluggable** — plan A (sherpa) dan plan B (pyannote) bisa
  ditukar tanpa membongkar pipeline.
- **Jumlah pembicara selalu auto** — tidak pernah ditanyakan ke pengguna.

## Teknologi

Python 3.11 · faster-whisper (Whisper large-v3) · whisper.cpp (Vulkan) ·
sherpa-onnx · pyannote.audio · onnxruntime · PyTorch (opsional, mode Akurat) ·
soundfile · Tkinter (GUI).

## Model & atribusi

Model tidak disertakan dalam repositori ini dan diunduh dari sumber resminya:

- **Whisper large-v3** (OpenAI) — via `Systran/faster-whisper-large-v3` dan
  `ggerganov/whisper.cpp` di Hugging Face.
- **sherpa-onnx** (k2-fsa) — model segmentation & speaker embedding dari halaman
  rilis GitHub.
- **pyannote** — `pyannote/speaker-diarization-community-1` di Hugging Face.

Masing-masing tunduk pada lisensinya sendiri.

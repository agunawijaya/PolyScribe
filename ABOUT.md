# About PolyScribe

PolyScribe adalah aplikasi desktop Windows untuk **transkripsi dan diarization**
(memisahkan "siapa berbicara kapan") rekaman rapat, **offline-first** di laptop
pribadi. Dibuat untuk kebutuhan rapat berbahasa **Inggris, Arab, dan Indonesia**
yang sering tercampur dalam satu rekaman.

## Tujuan

Mengubah satu file audio rapat menjadi satu transkrip `.txt` yang rapi —
lengkap dengan timestamp dan label pembicara. Jalur default 100% di laptop
kamu, tanpa mengirim apa pun ke cloud — privasi rekaman rapat adalah alasan
utama aplikasi ini offline-first. Jalur cloud opsional (7 provider) tersedia
sebagai pilihan eksplisit user per rekaman bila kualitas tertinggi lebih
penting dari privasi mutlak; tak pernah dipilih otomatis.

## Cara kerja (pipeline)

```
audio  ->  decode 16k mono  ->  ( transkripsi  ||  diarization )
       ->  merge berdasarkan overlap waktu  ->  tulis .txt di sebelah audio
```

Dua titik dibuat **pluggable** lewat interface, sehingga backend bisa ditukar
tanpa membongkar aplikasi:

- **ASR (`AsrBackend`)** — mesin transkripsi.
- **Diarization (`Diarizer`)** — mesin pemisah pembicara.

## Multi-hardware: jalan di mana-mana, tidak harus seragam

Aplikasi wajib **jalan** di tiga kelas mesin — NVIDIA (CUDA, acuan kualitas),
AMD (iGPU Radeon lewat Vulkan), dan CPU-only — lewat **satu kode sumber**.
Kualitas, kecepatan, dan tumpukan backend **boleh berbeda antar kelas**; memaksa
keseragaman justru menurunkan mesin kuat ke batas mesin terlemah. Backend dan
device dipilih lewat **deteksi runtime**, bukan di-hard-code per vendor:

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

## Cloud opsional (bila butuh kualitas maksimum)

Sejak 2026-09-21, PolyScribe menyediakan 7 backend cloud sebagai opsi opt-in
— bukan default, dan tak pernah dipilih otomatis. Berguna untuk rekaman yang
bukan sensitif (podcast publik, kuliah terbuka) di mana kualitas paling tinggi
lebih penting dari privasi mutlak: Groq (Whisper large-v3, termurah ~$0.04/jam),
Deepgram Nova-3 (kualitas tertinggi ~$0.26/jam), OpenAI Whisper, AssemblyAI,
Azure, Google Cloud, dan Google Web Speech (gratis, sama dgn markitdown Microsoft).

API key user disimpan di **Windows Credential Manager** (write-once — setelah
simpan, hanya bisa Diganti/Dihapus, TAK PERNAH ditampilkan kembali). Diarization
tetap lokal (pyannote/sherpa); cloud hanya menggantikan lapisan ASR.

## Batasan desain (prinsip)

- **Offline-first, cloud opt-in** — jalur default tanpa panggilan cloud;
  cloud harus dipilih user secara eksplisit, tak pernah otomatis.
- **Tidak hard-code satu vendor** — pemilihan backend lewat deteksi runtime.
- **Modul ASR & diarization pluggable** — ASR (faster-whisper / whisper.cpp /
  cloud), diarization (sherpa / pyannote) bisa ditukar tanpa membongkar pipeline.
- **Diarization tak pernah cloud** — konsistensi output antar-provider +
  kesederhanaan merge.
- **Jumlah pembicara selalu auto** — tidak pernah ditanyakan ke pengguna.
- **API key user tak pernah plaintext** — vault OS-native saja.

## Teknologi

Python 3.11 · faster-whisper (Whisper large-v3) · whisper.cpp (Vulkan) ·
sherpa-onnx · pyannote.audio · onnxruntime · PyTorch (opsional, mode Akurat) ·
soundfile · Tkinter (GUI) · keyring (Windows Credential Manager, mode cloud) ·
requests (HTTP ke provider cloud, opsional).

## Model & atribusi

Model tidak disertakan dalam repositori ini dan diunduh dari sumber resminya:

- **Whisper large-v3** (OpenAI) — via `Systran/faster-whisper-large-v3` dan
  `ggerganov/whisper.cpp` di Hugging Face.
- **sherpa-onnx** (k2-fsa) — model segmentation & speaker embedding dari halaman
  rilis GitHub.
- **pyannote** — `pyannote/speaker-diarization-community-1` di Hugging Face.

Masing-masing tunduk pada lisensinya sendiri.

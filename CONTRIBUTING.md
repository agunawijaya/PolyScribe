# Contributing to PolyScribe

Terima kasih atas minatnya. PolyScribe adalah aplikasi desktop offline dengan
scope yang sudah diketahui — dokumen ini menjelaskan bagaimana kontribusi bisa
mendarat dengan mulus tanpa merusak apa yang sudah bekerja.

Baca dulu:
- [PRODUCT_SPEC.md](docs/PRODUCT_SPEC.md) — apa yang dalam scope dan apa yang tidak
- [ARCHITECTURE.md](docs/ARCHITECTURE.md) — bagaimana modul-modul berbicara
- [CLAUDE.md](CLAUDE.md) — konvensi & perintah yang sudah terverifikasi

---

## Sebelum mulai

**Kontribusi yang paling dihargai:**
- Backend baru mengikuti interface `AsrBackend` / `Diarizer`
  (mis. Intel Arc XPU, AMD ROCm, Apple MPS).
- Perbaikan bug yang datang dengan test case.
- Perbaikan pesan error jadi lebih informatif dan Bahasa Indonesia natural.
- Peningkatan performa yang **terbukti angkanya** (bukan micro-optimization
  spekulatif).

**Kontribusi yang biasanya ditolak:**
- Menambah panggilan jaringan di jalur runtime (NFR-1: offline penuh).
- Menambah input "jumlah pembicara" manual di UI (§6.3 anti-feature).
- Refactor besar tanpa isu / diskusi terlebih dahulu.
- Menambah dependency besar (ratusan MB) untuk fitur kecil.
- Menyentuh `polyscribe/pipeline.py` untuk hal yang sebenarnya milik backend.

Kalau ragu, buka **issue** dulu sebelum menulis PR panjang.

---

## Development setup

**Prasyarat:** Windows 10/11, Python 3.11 (bukan 3.13 Store), git.

```powershell
git clone https://github.com/agunawijaya/PolyScribe.git
cd PolyScribe

# Jalur inti (semua kontributor)
py -3.11 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Tambahan (opsional, tergantung apa yang kamu kerjakan)
& .\.venv\Scripts\python.exe -m pip install -r requirements-cuda.txt       # kalau menyentuh CUDA
& .\.venv\Scripts\python.exe -m pip install -r requirements-pyannote.txt   # kalau menyentuh mode Akurat

# Model — sekali; butuh internet
& .\.venv\Scripts\python.exe scripts\download_models.py
```

Kalau menyentuh mode Akurat, kamu juga butuh model pyannote — lihat
[CARA_UNDUH_PYANNOTE.md](CARA_UNDUH_PYANNOTE.md).

---

## Menjalankan test

```powershell
$py = ".\.venv\Scripts\python.exe"
Get-ChildItem tests\test_*.py | ForEach-Object { & $py $_.FullName }
```

Target: **75 lulus** (74 sekarang di mesin tanpa fixture Arab —
lihat [TROUBLESHOOTING.md](TROUBLESHOOTING.md#tests-arab-gagal)). PR yang
menurunkan jumlah test lulus akan ditolak.

Kalau menambah fitur:
- Tambahkan minimal 1 test unit yang mendemonstrasikan fitur bekerja.
- Kalau menyentuh pipeline pemrosesan audio, verifikasi manual dengan file audio
  berdurasi ≥ 30 menit. Bug parah proyek ini historis lolos karena hanya diuji
  di klip pendek — lihat prinsip "uji di file penuh" di
  [HANDOFF_NVIDIA_PM.md](HANDOFF_NVIDIA_PM.md).

---

## Aturan kode

**Gaya:** "humanized code". Komentar Bahasa Indonesia natural, seperlunya, nama
variabel jelas, tidak over-engineering.

- Komentar menjelaskan **kenapa**, bukan **apa** (kode sudah bilang apa).
- Nama fungsi/variabel deskriptif; hindari singkatan misterius.
- Jangan tambah abstraksi untuk skenario hipotetis.
- Kode Python tetap Bahasa Inggris (identifier, docstring API); komentar
  dan pesan user dalam Bahasa Indonesia.
- Encoding: selalu `encoding="utf-8", errors="replace"` untuk subprocess di
  Windows — `text=True` sendirian diam-diam memakai cp1252 dan crash di
  konten non-Latin.

**Menambah backend baru:**

1. Implementasi interface di `polyscribe/asr/base.py` (untuk ASR) atau
   `polyscribe/diarization/base.py` (untuk diarization).
2. Tambah file backend di `polyscribe/asr/<nama>_backend.py` atau
   `polyscribe/diarization/<nama>_backend.py`.
3. Daftarkan di `polyscribe/asr/__init__.py` atau
   `polyscribe/diarization/__init__.py` — logika pemilihan runtime.
4. **Jangan** menyentuh `polyscribe/pipeline.py`; kalau perlu, kemungkinan
   besar interface-nya yang perlu diperluas (bahas dulu di issue).
5. Handle absence gracefully — kalau library backend tidak terpasang, jangan
   crash saat import; beri pesan ramah saat user coba pakai.

**Perubahan yang menyentuh lebih dari satu kelas hardware:**

Ada tiga kelas target: Windows NVIDIA dGPU (acuan kualitas), Windows AMD Radeon
iGPU, dan CPU-only. Verifikasi di kelas yang terdampak sebisa mungkin; kalau tak
punya aksesnya, sebutkan di PR description supaya reviewer bisa test.

Kualitas & tumpukan backend **boleh berbeda** antar kelas — backend CUDA-only sah
untuk profil NVIDIA selama kelas lain tetap jalan. Yang TIDAK boleh: menurunkan
kualitas mesin kuat demi menyamakannya dengan mesin lemah, dan menyeret kompromi
khusus satu kelas (mis. `whispercpp_max_context` yang milik jalur Vulkan) menjadi
default global.

Backend & device dipilih lewat **deteksi runtime**, bukan hard-code vendor.
Jangan menambah cek `if platform == 'nvidia'`; gunakan
`polyscribe.hardware.detect()`.

---

## Privasi & git

**JANGAN** commit hal-hal ini:
- Rekaman audio (`.mp3`, `.wav`, `.m4a`) atau transkrip rapat asli (`.txt`
  yang berisi hasil transkripsi rapat nyata).
- HuggingFace token.
- Path absolut spesifik ke mesin lokal kamu.
- Isi folder `models/`, `vendor/`, `.venv/`, `prompts/`.

`.gitignore` sudah menutup sebagian besar dari ini, tapi **selalu jalankan
`git status` sebelum commit**. Kalau ada `.mp3` atau transkrip di daftar
staged, berhenti dan investigasi.

Jangan tambah dokumentasi yang hardcode path absolut kamu (mis.
`C:\Users\<username>\...`). Gunakan `<path/ke/PolyScribe>` sebagai placeholder.

---

## Alur PR

1. **Fork & branch:** buat branch dengan nama deskriptif (mis.
   `feature/rocm-backend`, `fix/loopguard-arabic`).
2. **Commit:** pesan singkat dan jelas (Bahasa Indonesia atau Inggris,
   konsisten dalam satu PR). Sertakan **kenapa** perubahan dilakukan di body
   commit.
3. **Test:** jalankan test suite; sertakan bukti hasil di PR description.
4. **PR title:** deskriptif, tidak lebih dari 70 karakter.
5. **PR body:** ikuti template `.github/PULL_REQUEST_TEMPLATE.md` (otomatis
   muncul saat buka PR).
6. **Response:** siap merespon feedback dalam waktu wajar. PR yang tidak
   ada aktivitas > 1 bulan bisa ditutup dan dibuka ulang saat siap.

---

## Isu terbuka yang ramah kontributor

Cek [issue dengan label `good-first-issue`](../../issues?q=label%3Agood-first-issue)
di GitHub. Kalau tidak ada, lihat "Non-goals & TBD" di
[PRODUCT_SPEC.md](docs/PRODUCT_SPEC.md#63-explicit-anti-features) atau
"Known limitations" di [PRODUCT_SPEC.md §10](docs/PRODUCT_SPEC.md#10-known-limitations--open-questions)
untuk ide.

Menambah backend untuk hardware baru (Intel Arc XPU, AMD ROCm, Apple MPS)
adalah kontribusi paling bernilai saat ini — infrastruktur pluggable sudah
siap, tinggal implementasi + integration.

---

## Kode etik

Bersikap sopan dan sabar. Aplikasi ini dipakai oleh orang non-teknis untuk
pekerjaan mereka — feedback konstruktif menghormati pengguna akhir. Personal
attacks, spam, dan konten kebencian tidak diterima.

Kontak untuk laporan kerentanan keamanan: lihat [SECURITY.md](SECURITY.md).

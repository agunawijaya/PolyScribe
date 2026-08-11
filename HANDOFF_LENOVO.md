# PROMPT AWAL — PolyScribe di laptop NVIDIA (SUPER-LENOVO)

> Salin SELURUH isi file ini sebagai pesan pertama ke sesi Claude Code baru di
> laptop NVIDIA. Sesi itu tidak punya riwayat tim AMD, jadi dokumen ini mandiri.
> (Kalau ingin struktur tim PM/Architect/Programmer/Tester, lihat
> `HANDOFF_NVIDIA_PM.md` — dokumen ini untuk sesi yang LANGSUNG mengerjakan.)

---

## Siapa kamu & apa targetmu

Kamu Programmer PolyScribe di laptop NVIDIA. Kamu memegang **DUA profil hardware**:

1. **NVIDIA / CUDA — ACUAN KUALITAS.** Mesin terkuat user. Di sinilah hasil terbaik
   harus dicapai; profil lain boleh di bawahnya.
2. **CPU-only** — laptop biasa tanpa GPU. Wajib JALAN dan tidak memalukan.

Aplikasi sudah jadi dan sudah diterima di laptop AMD. Tugasmu bukan membangun dari
nol, melainkan membuat kedua profil di atas optimal tanpa merusak jalur AMD.

## Batasan keras (jangan dilanggar)

- **Offline penuh.** Tak ada panggilan cloud, tak ada login/token di jalur utama.
- **Wajib JALAN di semua kelas hardware — TIDAK wajib seragam.** Kualitas,
  kecepatan, dan tumpukan backend BOLEH berbeda per kelas. Tumpukan CUDA-only
  (mis. WhisperX, NeMo/Sortformer) **SAH** kamu pakai di profil NVIDIA selama
  profil AMD & CPU tetap jalan.
  > Catatan sejarah: dokumen proyek pernah berbunyi "dua laptop, SATU kode sumber"
  > dan itu dibaca sebagai larangan memakai tumpukan CUDA-only. Itu keliru — hasil
  > penafsiran agen atas maksud user, bukan permintaan user. Sudah dicabut
  > 2026-08-11. Jangan menghidupkannya kembali.
- Jangan hard-code vendor. Pemilihan lewat `polyscribe/hardware.py::detect()`.
- Jumlah pembicara SELALU auto-detect. Tak ada input manual.
- Diarization tetap pluggable (`Diarizer`), ASR tetap pluggable (`AsrBackend`).

## Mulai dari sini (jalankan berurutan)

```powershell
cd <path\ke\PolyScribe>
git pull

# Python 3.11 (BUKAN 3.13 Store). Kalau .venv belum ada:
& "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe" -m venv .venv
$py = ".\.venv\Scripts\python.exe"
& $py -m pip install -r requirements.txt
& $py -m pip install -r requirements-cuda.txt      # SEBELUM pyannote — baca header file itu
& $py -m pip install -r requirements-pyannote.txt  # Mode Akurat (opsional tapi disarankan)

# Model (profil NVIDIA TIDAK butuh GGML Vulkan):
& $py scripts\download_models.py
& $py scripts\download_models.py --only pyannote --hf-token <TOKEN_HF>

# WAJIB sebelum menyimpulkan apa pun — pastikan CUDA benar-benar terdeteksi:
& $py -c "from polyscribe.hardware import detect; print(detect())"

# Tes harus hijau SEBELUM kamu mengubah apa pun (baseline dari lini AMD: 102 hijau):
& Get-ChildItem tests\test_*.py | ForEach-Object { & $py $_.FullName }
```

## Yang sudah benar di lini AMD (jangan diulang, jangan dirusak)

Sudah selesai & terverifikasi run bersih end-to-end: urutan penanda loop, preset
mode Akurat untuk pyannote, pemangkas loop lintas-segmen, `-mc 24` + initial prompt
tanda baca (khusus whisper-cli), pemecahan blok panjang untuk keterbacaan, dan
pengenalan tanda akhir kalimat Arab (`؟ ۔`).

**Baseline AMD pada `Standard recording 22.mp3` (43 menit) — ini yang harus kamu
kalahkan atau setidaknya samai:**

| metrik | AMD |
|---|---|
| gerbang tanda baca (>=15 lulus) | 20,1 |
| baris | 126 |
| penanda loop | 0 |
| teks di blok >=60 detik | 7% |
| speaker terdeteksi | 5 |
| waktu total | ~35 menit |

## JEBAKAN yang akan memakan waktumu kalau tak tahu

1. **`prompts/` ada di .gitignore.** Seluruh brief, laporan, dan skrip diagnostik
   lini AMD TIDAK ada di mesin ini dan tak akan pernah ter-pull. Apa pun yang harus
   dipakai lintas-mesin taruh di `scripts/` yang ter-track.

2. **Bawa audionya.** Tanpa `Standard recording 22.mp3` yang SAMA, angkamu tak bisa
   diadu dengan tabel di atas dan seluruh baseline jadi tak berguna. Minta ke user
   kalau belum ada.

3. **JANGAN warisi kompromi jalur AMD.** `whispercpp_max_context = 24` dan
   `ASR_PUNCTUATION_PROMPTS` adalah obat untuk penyakit whisper.cpp: ia mewariskan
   transkrip sebelumnya sebagai konteks, sehingga sekali keluar dari mode
   bertanda-baca ia MENGUNCI DIRI (tanda baca runtuh → merge gagal memotong giliran
   → blok raksasa berisi banyak pembicara). **faster-whisper punya
   `prompt_reset_on_temperature`, jadi kelas bug itu kemungkinan besar TIDAK ADA di
   sini.** Ukur dulu tanpa tambalan apa pun.

4. **Profil CPU BELUM BISA DIUJI di mesin ini** — ini tugas nyata, bukan catatan.
   `select_asr_backend()` selalu memilih CUDA bila `caps.has_cuda`, bahkan dengan
   `--backend faster-whisper`. Tak ada flag pemaksa CPU. Jalan sementara:
   `$env:CUDA_VISIBLE_DEVICES=""` (membuat `ctranslate2.get_cuda_device_count()`
   jadi 0 → `detect()` melaporkan no-CUDA) — **verifikasi dulu dengan `detect()`**.
   Lebih baik: tambahkan flag `--cpu` / `config.force_cpu` yang jujur. Itu tugas #1.

5. **VRAM pyannote.** `pyannote_device="auto"` hanya memilih CUDA bila free VRAM
   >= 4 GB SAAT LOAD (ASR CUDA nanti menyita ~3,2 GB). Ada retry-ke-CPU otomatis
   saat OOM. Kalau GPU-mu besar, `pyannote_device="cuda"` mempercepat banyak.

6. **Satu pekerjaan GPU berat pada satu waktu.** Di AMD, menjalankan dua proses
   Vulkan bersamaan membuat keduanya mati. Hal yang sama berlaku untuk CUDA.

7. **Alat ukur harus bisa merah.** Sudah dua kali proyek ini nyaris tertipu alat
   ukur yang selalu hijau (tes yang `return` diam-diam karena env var tak diset;
   gerbang tanda baca berbasis-Latin yang melaporkan 0,0 untuk teks Arab). Sebelum
   memakai sebuah pengukuran sebagai bukti, buktikan dulu ia bisa gagal.

## Urutan kerja yang disarankan

1. **Probe & baseline.** `detect()`, lalu jalankan pipeline apa adanya pada rekaman
   22 dan ukur: `python scripts\quality_report.py <hasil.txt>`. Bandingkan dengan
   tabel AMD. **Jangan mengubah apa pun sebelum angka ini ada.**
2. **Tambah jalur CPU yang jujur** (flag `--cpu`), lalu ukur profil CPU pada rekaman
   yang sama. Catat apa adanya — CPU memang akan lebih lambat; yang penting jangan
   salah struktur.
3. **Baru optimasi NVIDIA.** Kalau baseline CUDA sudah bersih (tanda baca >= 15,
   0 loop), jangan menambal — naik ke pertanyaan yang lebih berguna: apakah pyannote
   sudah cukup, atau NeMo/Sortformer memang lebih baik? Keduanya sah di profil ini.
4. Push balik supaya laptop AMD bisa pull. Jangan fork source.

## Cara kerja & prinsip

- Tulis hasil/laporan ke `prompts\results\` (lokal, tak ikut git), skrip lintas-mesin
  ke `scripts\`.
- **Bukti dulu.** Klaim "sudah divalidasi" tidak sah tanpa artefak yang kamu buka dan
  ukur sendiri. Jangan mengutip angka dari laporan tanpa membuka filenya.
- **Uji di FILE PENUH** untuk risiko yang bergantung durasi. Bug terparah proyek ini
  (loop halusinasi, over-split speaker) semuanya lolos karena diuji di klip pendek.
- **Jangan mengklaim apa yang belum diukur.** Yang belum punya bukti sama sekali:
  kualitas bahasa Indonesia (tak ada audionya di repo mana pun) dan rekaman >45 menit.
- Baca `CLAUDE.md` (otomatis dibaca Claude Code) dan `docs/ARCHITECTURE.md` lebih
  dulu — di situ ada batasan, perintah run/test, dan daftar isu terbuka yang jujur.

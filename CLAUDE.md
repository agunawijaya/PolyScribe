# CLAUDE.md — PolyScribe

Panduan untuk setiap Claude Code (Programmer / Tester) yang bekerja di proyek ini.
Baca ini dulu sebelum menyentuh kode.

## Apa ini
Aplikasi desktop Windows 11 untuk transkripsi + diarization audio rapat, offline.
Bahasa audio: Inggris / Arab / Indonesia, boleh campur di tengah satu rekaman.
Output: satu file .txt (timestamp + label pembicara + teks) di sebelah file audio.

## RUANG LINGKUP v1 (dibekukan — baca ini sebelum mengambil kerja)
v1 = dipakai SENDIRI oleh user di laptop AMD ini. BUKAN untuk distribusi.
DIKERJAKAN: core CLI (selesai), kualitas diarization, GUI + progress hidup (M2).
DITUNDA — jangan dikerjakan: packaging .exe/PyInstaller & build profile (M3),
manifest model / ketahanan link mati / provisioning manual, profil & probe laptop
NVIDIA. Jalan dari venv saja sudah cukup untuk v1.

## Batasan keras (jangan dilanggar)
- Offline penuh. Tidak ada panggilan cloud. Tidak ada login / token pada jalur
  utama (plan A).
- Target hardware = TIGA KELAS mesin. Aplikasi WAJIB **jalan** di ketiganya:
  (1) NVIDIA (CUDA) — **acuan kualitas**, mesin terkuat user;
  (2) AMD Ryzen AI 7 350 — iGPU Radeon 860M (Vulkan) / CPU. Tidak ada CUDA;
  (3) Laptop biasa CPU-only.
  **Kualitas, kecepatan, dan TUMPUKAN backend BOLEH berbeda antar kelas** — user
  secara eksplisit mengizinkannya demi hasil terbaik per mesin (2026-08-11).
  Artinya: tumpukan CUDA-only (mis. WhisperX, NeMo/Sortformer) SAH dipakai di
  profil NVIDIA. Yang tetap wajib: profil lain tetap jalan, tak ada hard-code
  vendor, pemilihan lewat DETEKSI RUNTIME + build profile.

  KOREKSI SEJARAH — jangan hidupkan lagi batasan lama. Sampai 2026-08-11 dokumen
  ini menulis "Target hardware ADA DUA ... WAJIB jalan lewat SATU kode sumber".
  Itu bukan kata user: jejaknya di `prompts\02_pm_to_architect_revision.md` §2,
  di mana agen ber-peran PM MENAFSIRKAN maksud user ("«Fork» yang user maksud
  diwujudkan di level BUILD, bukan source") lalu menuliskannya sebagai requirement.
  Tafsiran itu menyebar ke ARCHITECTURE.md & PRODUCT_SPEC.md, naik pangkat jadi
  "batasan keras", dan membuat agen berikutnya membuang opsi CUDA-only tanpa pernah
  menanyakannya. Tiga dokumen yang saling konsisten BUKAN verifikasi — itu satu
  klaim yang disalin tiga kali. Telusuri batasan ke sumbernya sebelum mematuhinya.

  Catatan teknis: kualitas terbaik per mesin TIDAK menuntut fork kode sumber —
  `AsrBackend`/`Diarizer` yang pluggable memang untuk itu. Satu basis kode tetap
  praktik yang baik; yang dicabut adalah keharusan KUALITAS/BACKEND yang seragam.
- Diarization plan A = sherpa-onnx. Modulnya HARUS tetap bisa ditukar (pluggable)
  supaya plan B (pyannote) bisa dipasang tanpa membongkar aplikasi.
- Jumlah pembicara selalu auto-detect. Tidak ada input jumlah pembicara manual.

## Alur kerja antar-agen (WAJIB)
- Tugas / prompt dibaca dari:  prompts\
- Tulis hasil / jawaban ke:    prompts\results\
- Taruh script ke:             prompts\scripts\
Jangan menjawab hanya di chat — selalu tuliskan output ke results\ agar pemberi
tugas bisa membacanya kembali.
Laporan naik satu tingkat: Programmer/Tester -> Architect (yang memutuskan
teknis) -> PM. PM tidak membaca laporan engineer langsung; PM bertanya lewat
Architect.

## Gaya kode
"Humanize the code": komentar natural dan seperlunya, nama variabel jelas, mudah
dibaca manusia, tidak over-engineer.

## Arsitektur, struktur folder, dependency

**Arsitektur singkat.** Pipeline: audio -> decode 16k mono -> (transkripsi ||
diarization) -> merge by overlap waktu -> tulis .txt di sebelah audio. Dua titik
dibuat pluggable lewat interface: ASR (AsrBackend) dan diarization (Diarizer).
Ganti backend = ganti satu kelas; pipeline tidak berubah.

**Runtime & multi-hardware.** Satu kode sumber jalan di tiga kelas mesin (NVIDIA
/ AMD-Vulkan / CPU-only); yang beda: binary & dependency yang dibundel per build
profile, DAN — sejak 2026-08-11 — boleh juga tumpukan backend-nya (lihat Batasan).
- ASR backend A = faster-whisper large-v3. Dengan device='auto' dia otomatis
  pakai CUDA di laptop NVIDIA (cepat) dan CPU int8 di laptop AMD (baseline yang
  selalu jalan). Satu backend menutup dua mesin.
- ASR backend B = whisper.cpp large-v3 via Vulkan (subprocess ke
  vendor/whisper-cli/whisper-cli.exe) = jalur cepat untuk iGPU Radeon 860M di
  laptop AMD. Otomatis fallback ke CPU bila Vulkan tak ada.
- Diarization = dua backend pluggable lewat kontrak `Diarizer`.
  **`pyannote` (Akurat) = DEFAULT** — overlap-aware, memisahkan pertukaran cepat;
  ~2,5× lebih lambat (embedding di CPU; auto CUDA di laptop NVIDIA). **`sherpa`
  (Cepat)** = cadangan cepat (CPU); **fallback otomatis** bila PyTorch/model pyannote
  tak ada — tak pernah crash. Dipilih lewat `config.diarizer_choice`, dropdown GUI,
  atau `--diarizer`. Speaker count SELALU auto. Model pyannote diunduh **sekali saat
  build** (token HF); **runtime tetap offline, tanpa akun** (`HF_HUB_OFFLINE`).
  Knob cleanup/merge (`diar_min_turn`, `diar_min_speaker_frac`, `merge_island_max_s`)
  adalah **tuning sherpa** dan punya PRESET SENDIRI untuk pyannote (semua 0, brief 50)
  lewat `Config.tuning_for_diarizer()` — dipilih dari diarizer yang benar-benar
  dipakai (sesudah fallback), bukan yang diminta.
  Knob khusus sherpa (lebur-centroid, ITD-split, spatial) **tidak dipakai pyannote** —
  terbukti lewat `.txt` byte-identik ON vs OFF (brief 37).
- Pemilihan backend/device lewat DETEKSI RUNTIME, bukan hard-code vendor.
- Prioritas backend ASR: CUDA (NVIDIA) -> Vulkan (iGPU AMD) -> CPU int8 (universal).
  PENTING: faster-whisper device='auto' hanya memilih cuda-atau-cpu, TAK pernah
  Vulkan. Pemilihan Vulkan lewat polyscribe/hardware.py + selector di
  asr/__init__.py — jangan menyerahkannya ke device='auto'.
- Build: dua profil (build/profile_amd.spec, profile_nvidia.spec) -> dua installer.
  Paket pip IDENTIK di kedua profil; yang beda hanya native lib/model yang
  dibundel (Vulkan whisper-cli untuk AMD; cuBLAS+cuDNN untuk NVIDIA).

**Lingkungan.** Python 3.11 (venv terpisah), bukan Python 3.13 Store yang
terpasang (Store bermasalah untuk native lib & PyInstaller).

**Struktur folder (ringkas).**
    polyscribe\  audio.py, pipeline.py, merge.py, formatting.py, progress.py,
                 loopguard.py, spatial.py, hardware.py, cli.py, gui.py,
                 asr\ (base, faster_whisper_backend, whispercpp_backend),
                 diarization\ (base, sherpa_onnx_backend, pyannote_backend, cleanup)
    models\      whisper\, faster-whisper-large-v3\, diarization\ (sherpa +
                 pyannote\ community-1)  (offline, no-commit)
    vendor\      whisper-cli\ (binary Vulkan + dll)
    scripts\     download_models.py, benchmark_backends.py, tester_diar_count.py
    prompts\scripts\  make_fixtures.py + skrip diagnostik/uji per-brief
    tests\       test_*.py (10 file, 75 tes), fixtures\ (klip uji incl. Arab)

**Dependency inti.** faster-whisper, sherpa-onnx, onnxruntime, soundfile, numpy,
imageio-ffmpeg (runtime); pyinstaller (build); tkinter (GUI, bawaan). **Mode Akurat
(pyannote)** menambah pyannote.audio + PyTorch (CPU ~494 MB) — DIPISAH di
`requirements-pyannote.txt` supaya jalur inti (plan A) tak terseret PyTorch. Versi
dikunci lewat pip freeze setelah instalasi pertama yang berhasil. whisper-cli
Vulkan bukan paket pip — disiapkan manual di vendor/. Build profile per-hardware
(CUDA vs AMD/Vulkan) membundel binary berbeda; detail di design revision.

**Catatan realitas versi (mesin ini):** torch 2.13.0+cpu memaksa pyannote.audio 4.x
(3.x tak ter-import). Model pyannote 4.x = `speaker-diarization-community-1`
(self-contained seg+emb+PLDA). torchcodec gagal load DLL di Windows -> backend
menyuapkan audio in-memory (`{"waveform","sample_rate"}`), bukan path.

## Perintah build / run / test
Semua perintah di bawah SUDAH dijalankan sendiri (kebijakan: hanya perintah terbukti
yang masuk sini). Semua pakai Python 3.11 di .venv. Jalankan dari root repo:

    cd <path\ke\PolyScribe>          # apa pun path yang kamu clone
    $py = ".\.venv\Scripts\python.exe"

Unduh model (faster-whisper + diarization sherpa + GGML untuk Vulkan):
    & $py scripts\download_models.py
    & $py scripts\download_models.py --only whisper-ggml

Mode Akurat / pyannote (OPSIONAL — sekali saat build; runtime tetap offline):
    & $py -m pip install -r requirements-pyannote.txt       # PyTorch CPU ~494 MB
    & $py scripts\download_models.py --only pyannote --hf-token <TOKEN_HF>
    # terima lisensi pyannote/speaker-diarization-community-1 di HF dulu.
    # Kalau langkah ini dilewati, app tetap jalan: otomatis jatuh ke mode Cepat.

Transkripsi (1 audio -> 1 .txt di sebelah audio; auto Vulkan di AMD):
    & $py -m polyscribe.cli "rekaman.mp3"                    # default = Akurat (pyannote)
    & $py -m polyscribe.cli "rekaman.mp3" --diarizer sherpa   # Cepat (lebih cepat)
    & $py -m polyscribe.cli "rekaman.mp3" --diarizer pyannote # eksplisit Akurat
    & $py -m polyscribe.cli "rekaman.mp3" --no-vulkan        # paksa CPU
    & $py -m polyscribe.cli "rekaman.mp3" --language auto     # file multibahasa

GUI (jendela untuk user non-teknis; toggle mode + Stop + progress hidup):
    & $py -m polyscribe.gui

Gerbang bukti Vulkan (binary hidup + benar-benar GPU):
    & vendor\whisper-cli\whisper-cli.exe --help

Benchmark CPU vs Vulkan di klip sama:
    & $py scripts\benchmark_backends.py "rekaman.mp3" --seconds 300 --compare

Hitung cepat jumlah speaker file penuh (diarization-saja, tahan interupsi):
    & $py scripts\tester_diar_count.py "rekaman.mp3"

Buat klip uji (sekali; TERMASUK klip Arab — uji rutin dilarang hanya-Inggris):
    & $py prompts\scripts\make_fixtures.py

Setup awal (sekali, dari nol) — Python 3.11, BUKAN 3.13 Store. Jalankan dari root repo:
    winget install --id Python.Python.3.11 --source winget --silent
    & "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe" -m venv .venv
    & $py -m pip install --upgrade pip
    & $py -m pip install -r requirements.txt
    & $py -m pip freeze > requirements.lock.txt          # kunci versi

Setup tambahan untuk mesin ber-GPU NVIDIA (brief NVIDIA_00/01/02):
    & $py -m pip install -r requirements-cuda.txt        # SEBELUM pyannote — lihat header file itu

Reproduksi di mesin lain (pakai versi terkunci):
    & $py -m pip install -r requirements.lock.txt

Unit test (96 hijau; jalankan semua 11 file di tests\):
    & Get-ChildItem tests\test_*.py | ForEach-Object { & $py $_.FullName }
    # atau per file, mis.:  & $py tests\test_merge.py ; & $py tests\test_diarizer_toggle.py

## Config default v1 (verbatim — nilai efektif di config.py)

    diarizer_choice        = "pyannote"   # Akurat (default) | "sherpa" = Cepat
    whispercpp_max_context = 24           # brief 51: naik dari 8. Tanda baca 8,2->13,1
                                          # & loop 2->0 di rekaman 43 mnt. Regime
                                          # >45 mnt BELUM teruji (file uji hilang).
    primary_language       = "en"         # "auto" untuk file multibahasa
    asr_initial_prompt     = ""           # kosong = pakai contoh tanda baca per bahasa
    asr_carry_initial_prompt = True       # ulangi contoh itu di SETIAP jendela
    # Contoh tanda baca default HANYA untuk "en" (ASR_PUNCTUATION_PROMPTS). Brief 51:
    # prompt Inggris pada audio Arab bikin whisper MENERJEMAHKAN; prompt Arab bikin
    # output runtuh. Jangan menambah bahasa tanpa mengukur di fixture bahasa itu.
    allow_vulkan           = True
    use_word_refine        = True
    use_speaker_merge      = True         # hanya berlaku untuk sherpa
    use_itd_split          = True         # hanya berlaku untuk sherpa
    use_spatial_cues       = False        # terbukti tak bermanfaat

    # knob cleanup/merge: dipilih per-diarizer (Config.tuning_for_diarizer)
    diar_min_turn          = 0.5   / pyannote: 0.0    # preset Akurat = tanpa perataan
    diar_min_speaker_frac  = 0.010 / pyannote: 0.0
    merge_island_max_s     = 4.0   / pyannote: 0.0

## Isu terbuka v1 (jujur)
1. **pyannote selalu ~5 speaker di file panjang** — koheren sejauh diuji, tapi BELUM
   diuji pada rapat berpeserta banyak (8+). Kalau muncul rapat besar, verifikasi jumlah.
2. **Micro-triple 25:28-25:30** ("Yeah."/"Exactly.") masih menyatu — batas **ASR**
   (satu segmen Whisper), bukan diarization. Seri dengan OPPO, bukan kalah.
3. **Mode Akurat ~2,5× lebih lambat** — rekaman 1 jam ≈ 1 jam pemrosesan.
4. **Sisa halusinasi lokal** (2 titik di Std-12) — ditandai & dipangkas, tak meluas.
5. **Ditunda (ruang lingkup beku):** packaging .exe, profil NVIDIA, distribusi.

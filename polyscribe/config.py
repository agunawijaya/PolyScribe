"""Konfigurasi runtime PolyScribe.

Satu tempat untuk semua pilihan yang menentukan backend, path model, dan knob
diarization. Nilai default aman untuk laptop AMD (profil "amd"), tapi semuanya
bisa ditimpa dari CLI atau dari profile.json bawaan build.
"""

from dataclasses import dataclass, field
from pathlib import Path


# Root proyek = folder yang memuat paket ini. Model & vendor dicari relatif ke
# sini supaya jalan sama saat dev maupun setelah dibundel.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = PROJECT_ROOT / "models"


# Contoh pola tanda baca per bahasa (brief 51). Dipakai sebagai initial prompt untuk
# whisper-cli: bukan untuk memberi tahu ISI rapat, hanya untuk MENUNJUKKAN pola output
# yang benar (titik, koma, tanya) supaya whisper tak tergelincir ke mode tanpa tanda
# baca — keadaan yang mengunci diri karena konteks yang diwariskannya juga tanpa tanda
# baca. Kalimat sengaja generik dan TANPA nama orang/tempat: prompt berisi nama terbukti
# memicu halusinasi nama saat audio ambigu.
#
# HANYA "en" — sengaja. Dua percobaan di fixture Arab 90 detik, keduanya GAGAL:
#   - prompt INGGRIS pada audio Arab -> whisper MENERJEMAHKAN, bukan mentranskripsi
#     (100% huruf Arab jadi 0%; teks keluar sebagai kalimat Inggris);
#   - prompt ARAB pada audio Arab -> output runtuh jadi 3 segmen identik
#     (tanpa prompt: 15 segmen, teks Arab wajar, 5,3 tanda baca/100 kata).
# Keduanya kerusakan SENYAP yang jauh lebih buruk daripada tanda baca yang hilang.
# Indonesia belum diuji (tak ada fixture), jadi juga tak diberi prompt. Prinsipnya:
# knob ini hanya menyala di jalur yang sudah diukur.
#
# Catatan teknis: dengan -mc 24 whisper hanya memakai ~23 token TERAKHIR dari prompt
# ("initial prompt is too long ... will use only the last N tokens"). Jadi ekor kalimat
# harus contoh tanda baca yang baik — itu sebabnya string di bawah diakhiri kalimat
# pendek bertitik. Jangan mengubah teksnya tanpa mengukur ulang; angka 13,1 -> 20,1
# diukur dengan string PERSIS ini.
ASR_PUNCTUATION_PROMPTS = {
    "en": ("Okay, so let me explain how it works. First, we check the shelf. "
           "Then, if the book is missing, we report it. Yes, that is correct. "
           "Thank you very much."),
}


@dataclass
class Config:
    # --- pemilihan hardware / backend ---
    build_profile: str = "amd"        # ditimpa oleh profile.json bawaan build
    allow_vulkan: bool = True         # matikan untuk memaksa CPU di AMD
    asr_backend: str = "auto"         # "auto" | "faster-whisper" | "whispercpp"
    asr_compute_type: str = ""        # kosong = biar selector yang pilih

    # --- ASR knob untuk kualitas transkrip (bug user 2026-08 kualitas rendah) ---
    # VAD filter: buang keheningan sebelum decode. Default **False** untuk PolyScribe
    # (audio rapat) — perubahan dari True awal setelah A/B test klip 6-menit
    # file 19 (brief BUG_2026-08-05_text_quality): VAD=True menghasilkan Whisper
    # nyaris tanpa titik/koma -> merger kita gagal potong kalimat -> paragraf
    # raksasa yg menelan interjeksi orang lain (satu SPEAKER_XX turn 4 menit
    # padahal 6 orang bicara). VAD=False memberi Whisper konteks utuh -> punctuation
    # kembali, proper nouns tepat (Digital Dubai, Symphony, dst). Trade-off: sedikit
    # lebih lambat & keheningan panjang ikut diproses (kadang halusinasi). Untuk
    # audio single-speaker bersih, set True bisa lebih cepat.
    vad_filter: bool = False
    # Initial prompt: contoh text yang di-prepend sebelum decode. Berguna untuk
    # "nudge" Whisper ke pola output tertentu — mis. tanda baca lengkap, atau
    # nama-nama peserta/istilah teknis. Kosong = tak ada nudge. Efek verifikasi
    # A/B: dgn prompt yg berisi nama peserta ("Jaffar Labs, Digital Dubai, MBRL"),
    # Whisper lebih akurat mengeja proper nouns. Trade-off: bisa halusinasi nama
    # dari prompt saat audio ambigu (mis. loop "Customer Hagen" 3x). Rekomendasi:
    # isi HANYA bila Anda tahu nama peserta & istilah teknis file.
    asr_initial_prompt: str = ""
    # Ulangi initial prompt di SETIAP jendela (whisper-cli --carry-initial-prompt),
    # bukan hanya jendela pertama. Relevan karena tanda baca runtuh per-WILAYAH di
    # tengah/akhir file, bukan cuma di awal — nudge sekali di awal tak menolong
    # wilayah menit ke-35. Tak berefek bila asr_initial_prompt kosong.
    asr_carry_initial_prompt: bool = True

    # --- bahasa ASR ---
    # "en" (default, prioritas English) meneruskan language="en" ke Whisper agar
    # deteksi bahasa stabil di awal file (menghapus salah-deteksi Inggris->Melayu).
    # "auto" = deteksi penuh per-window (untuk file yang benar-benar multibahasa,
    # mis. SIRA). Trade-off "en": segmen Arab insidental didekode sebagai Inggris.
    primary_language: str = "en"

    # --- diarization ---
    # Brief 37: default DIUBAH ke "pyannote" (mode "Akurat"). Verifikasi Architect:
    # pyannote memisahkan pertukaran cepat ke orang berbeda (sherpa menelannya) &
    # menutup over-split Std-12 (10 -> 5) dengan TEKS ASR IDENTIK — kebenaran di atas
    # kecepatan. Ongkosnya diarization ~2,5x lebih lambat di CPU. User memilih per
    # rekaman lewat toggle GUI / --diarizer. Kalau model pyannote tak terpasang,
    # selector JATUH aman ke "sherpa" (lihat diarization/__init__.py) — tak crash.
    diarizer_choice: str = "pyannote"   # "pyannote" (Akurat, default) | "sherpa" (Cepat)
    # Device pyannote — "auto" (default): pakai CUDA hanya bila free VRAM cukup
    # sesudah ASR (yang lebih dulu masuk GPU); kalau tidak, CPU. Akar (bug user 2026-08):
    # laptop RTX 4060 8 GB — faster-whisper large-v3 float16 makan ~3,2 GB VRAM, sisa
    # ~3,7 GB tak cukup untuk pyannote community-1 memproses file 1 jam -> CUDA OOM
    # ("CUDA failed with error out of memory") saat `_pipeline(audio_in)`. "cpu" =
    # paksa CPU (paling aman; ~2,5x lebih lambat tapi TAK PERNAH OOM). "cuda" = paksa
    # CUDA (untuk mesin ber-VRAM besar; masih ada retry-CPU otomatis kalau OOM).
    pyannote_device: str = "auto"
    # Ambang free VRAM (GB) untuk "auto" memilih CUDA. Nilai = pyannote peak estimate
    # (~2 GB untuk community-1 di file panjang) + margin. Di bawah ini -> CPU.
    pyannote_min_free_vram_gb: float = 4.0
    # 0.9 = hasil tuning M1c di file rapat 45 menit: bersama min_duration_on=1.0
    # + pembersih pasca-diarization, menurunkan over-split dari ~40 label jadi
    # ~7 speaker yang masuk akal. (0.7 dari M1 over-split parah di file panjang.)
    cluster_threshold: float = 0.9    # knob auto speaker-count; dituned di M1/M1c

    # Knob segmentation sherpa: segmen sub-detik = biang over-split di file panjang.
    # min_duration_on menyaring blip aktif ultra-pendek; min_duration_off
    # menjembatani jeda pendek antar giliran speaker sama. Dituned di M1c.
    diar_min_duration_on: float = 1.0
    diar_min_duration_off: float = 0.5

    # Pembersih pasca-diarization (jaring pengaman, independen dari diarizer):
    # turn lebih pendek dari diar_min_turn diserap ke speaker tetangga dominan, dan
    # speaker yang total bicaranya di bawah diar_min_speaker_frac dari TOTAL bicara
    # dianggap spurious lalu dilebur.
    # Track B: dilonggarkan dari 1.0/0.015 -> 0.5/0.010. Setelan lama meruntuhkan
    # pertukaran cepat (peserta minor spt orang IT hilang). 0.5/0.010 memulihkan
    # sebagian pergantian speaker di pertukaran cepat, dengan jumlah speaker
    # file-penuh naik tipis saja (6 -> 7, bukan meledak). Over-split kosmetik
    # sisa dibersihkan di lapis merge (island suppression).
    diar_min_turn: float = 0.5
    diar_min_speaker_frac: float = 0.010

    # --- preset mode AKURAT (pyannote) — brief 50 ---
    # Ketiga knob di atas + merge_island_max_s adalah hasil tuning SHERPA: obat untuk
    # over-split sherpa yang kasar. pyannote tak punya penyakit itu (overlap-aware,
    # embedding lebih tajam), jadi knob yang sama justru MENGHAPUS keunggulannya —
    # cleanup menyerap turn pendek dan island-suppression melebur blok <=4 s yang
    # terjepit di antara dua blok speaker sama, yaitu bentuk persis interjeksi cepat.
    # Nilai 0 = tanpa perataan; ini config yang dipakai brief 39 saat memvalidasi
    # pyannote jadi default, tapi TAK PERNAH di-wire ke produk (report 38 §6c).
    # Bukti brief 50 (Standard recording 22, teks ASR identik):
    #   Cepat 72 baris / 42% kata di blok >=60s | Akurat-lama 70 / 44% (tak lebih baik
    #   dari Cepat padahal 2,3x lebih lambat) | Akurat-preset 89 / 37%.
    # Dari 9 pulau yang dulu dihapus, mayoritas terbukti pergantian NYATA (dicek isi;
    # Whisper bahkan menandainya dgn "- "). Sisa cacat: sesekali satu kata terpotong.
    pyannote_diar_min_turn: float = 0.0
    pyannote_diar_min_speaker_frac: float = 0.0
    pyannote_merge_island_max_s: float = 0.0

    # Merge level-kalimat (Track B): "island" = blok speaker pendek terjepit di
    # antara dua blok speaker SAMA (A-[b]-A). <= nilai ini dilebur ke speaker
    # tetangga (indikator kuat pergantian palsu #1). 4.0s cukup menutup kasus 09b
    # tanpa menyentuh alternasi sah A-B-A-B (#2).
    merge_island_max_s: float = 4.0

    # whisper.cpp --max-context (Vulkan). P0 (brief 18) sempat menyetel 0 untuk
    # membunuh loop halusinasi — TAPI itu juga membunuh tanda baca & konsistensi
    # kata (regresi brief 22): tanpa konteks, whisper tak menaruh titik/koma, dan
    # merge (yang memecah giliran per KALIMAT via tanda baca) runtuh jadi satu blok.
    # Konteks PENDEK memulihkan teks tanpa jadi bahan bakar loop. Sweep di file loop
    # Std-12 (region 0-20 mnt): -mc 0=0 loop, 8=0, 12=2, 14=0, 16=1, 32=38(!). Zona
    # 8-16 low-loop tapi berisik/stokastik; 32 katastrofik. Dipilih 8 = nilai terbesar
    # yang ANDAL bebas loop (setara baseline -mc 0), sambil memulihkan teks: di klip
    # Std-11 giliran 1->5 & tanda baca 3.3->25.1/100kata (di atas baseline LAMA 15.2).
    # word-level JSON & -ml TAK menambah granularitas (akar = tanda baca, bukan
    # word-timestamp — terbukti: segment/word/-ml identik di -mc sama). loopguard
    # TETAP menyala sebagai jaring pengaman terakhir.
    #
    # BRIEF 51 — DINAIKKAN 8 -> 24. Nilai 8 dipilih dari sweep di atas yang menimbang
    # LOOP saja; rekaman user 22 (43 mnt) menunjukkan ongkos sisi lain terlalu mahal:
    # tanda baca runtuh ke 8,2/100 kata (gerbang sahih brief 39 = 15) -> merge, yang
    # memotong giliran per KALIMAT, melebur 37% teks jadi blok >=60 detik berisi
    # beberapa pembicara. Sweep di file itu (ASR diulang, diarization sama):
    #   -mc  8: tanda baca  8,2 | 2 loop | 11 blok besar | 37% teks | (baseline)
    #   -mc 12: tanda baca  3,2 | 2 loop | 13 blok besar | 46% teks
    #   -mc 16: tanda baca  4,3 | 0 loop | 13 blok besar | 43% teks
    #   -mc 24: tanda baca 13,1 | 0 loop |  7 blok besar | 24% teks  <- menang semua
    # Loop TURUN saat konteks naik di file ini (2,2,0,0) — bukan naik. 24 juga paling
    # cepat. Zona 12-16 berisik, sesuai catatan brief 23.
    #
    # RISIKO YANG BELUM TERUKUR (jujur): sweep brief 23 yang memilih 8 diukur di
    # Std-12 PENUH (102 mnt) dgn loop di 47:37 & 1:12:21. Bukti terpanjang yang ada
    # sekarang cuma 43 mnt — file Std-12 sudah tak ada di mesin ini, jadi regime
    # >45 mnt TAK teruji. Kalau muncul rekaman panjang, jalankan
    # prompts\scripts\tester51_mc_loopgate.py (ganti FIXTURE) sebelum percaya diri.
    # Peringan: loopguard kini memangkas loop LINTAS-segmen & selalu menandai, jadi
    # kegagalan terlihat, tak senyap. Untuk kembali ke perilaku lama: setel 8 di sini.
    whispercpp_max_context: int = 24

    # Substring nama file model embedding pilihan (kosong = auto, WeSpeaker/ResNet
    # diutamakan). Diisi mis. "wespeaker" untuk mengunci model tertentu.
    diar_embedding: str = ""

    # --- lebur speaker over-split file panjang (brief 29) ---
    # Akar masalah: cluster_threshold di-tuning di file 45 mnt jebol di 102 mnt
    # (Std-12: 15 speaker utk ~6 orang). Makin panjang -> makin banyak variasi suara
    # -> orang sama dipecah jadi beberapa cluster. Obat: SETELAH clustering native,
    # lebur cluster yang CENTROID embedding-nya mirip (agglomerative atas centroid,
    # spatial.py). HANYA menggabung (tak pernah memecah) -> aman dari over-split &
    # tak menghapus peserta minor (beda dari min_speaker_frac). Ambang berbasis
    # KEMIRIPAN SUARA, bukan jumlah turn -> generalisasi lintas durasi.
    use_speaker_merge: bool = True
    # Ambang jarak Euclidean antar-centroid unit (= sqrt(2(1-cosine))).
    #
    # BRIEF 35 §3 — LINDUNGI SPEAKER: ambang tunggal 0.55 (brief 29) TERBUKTI SALAH
    # (ground-truth OPPO 25:04): ia melebur peserta NYATA yang berbeda. Akarnya:
    # peserta distinct bisa terdengar mirip (Std-11 SPEAKER_04 7,7% berjarak 0.409
    # dari SPEAKER_00) — SEDEKAT fragmen over-split. Obat: ambang BERGANTUNG PORSI,
    # dua tingkat, keduanya LEBIH KETAT dari 0.55:
    #   - dua speaker "substantial" (porsi >= merge_protect_frac) hanya dilebur bila
    #     centroid SANGAT mirip (< merge_major_threshold) — melindungi peserta nyata;
    #   - selain itu (ada fragmen kecil) diserap bila < merge_fragment_threshold.
    # Sweep cache brief 35 (merge_global_sweep.py): 0.45/0.35 -> Std-11 KEMBALI 7
    # (peserta yang keliru dilebur pulih) & Std-12 15->10 (jauh dari 15; ~7 tak bisa
    # dicapai TANPA melebur ulang speaker distinct Std-11 — batas embedding, wilayah
    # pyannote). Tetap HANYA menggabung -> tak menambah over-split.
    merge_fragment_threshold: float = 0.45   # serap fragmen kecil (dulu blanket 0.55)
    merge_major_threshold: float = 0.35      # lebur dua speaker substantial: harus dekat
    merge_protect_frac: float = 0.05         # porsi >= ini = "peserta nyata", dilindungi

    # --- isyarat spasial dari stereo (brief 25) ---
    # Rekaman ponsel stereo menyimpan arah suara (ILD/ITD). Infrastruktur untuk
    # mencampurnya ke embedding SEBELUM clustering ADA (spatial.py + re-cluster di
    # sherpa backend), TAPI dimatikan default: uji brief 25 (Std-12 penuh) TAK
    # membuktikan spasial-di-clustering menyembuhkan over-split (native cleanup=15;
    # w=0..0.4 -> 10..14, dan w=0 sudah 10 -> perbaikan dari re-cluster, BUKAN dari
    # arah). Menyalakannya menggantikan clustering native yang SUDAH tervalidasi
    # (deliverable brief 24) tanpa manfaat terbukti. Nyalakan hanya untuk eksperimen.
    # Jalan yang TERBUKTI (Tahap B) = ITD sebagai pemecah-turn, bukan clustering.
    use_spatial_cues: bool = False
    # Bobot fitur spasial (z-score) relatif embedding (L2-normal). 0 = embedding
    # murni (re-cluster tanpa arah); 0.2-0.4 mencampur arah.
    spatial_weight: float = 0.3
    # Ambang jarak Euclidean untuk agglomerative clustering augmented (dikalibrasi
    # di klip 5-mnt agar w=0 mendekati baseline sherpa native).
    spatial_cluster_threshold: float = 0.95

    # --- pemecah-turn berbasis ITD (brief 26) — serang #2 ---
    # ITD = pencari BATAS (di mana pergantian terjadi), BUKAN identitas. Memecah
    # turn sherpa di lompatan arah yang BERTAHAN, lalu sub-turn dikenali oleh
    # embedding + dipetakan ke speaker yang SUDAH ada (tak menciptakan speaker baru
    # -> aman dari over-split). Segmenter, clustering, ASR TAK diubah. Otomatis
    # nonaktif bila sumber mono / stereo palsu.
    # Brief 26: mekanisme BEKERJA di lapis diarization (interjeksi -8 di 183.8s benar
    # dikenali SPEAKER_04) tapi #2 tak muncul di .txt karena merge menugaskan teks
    # per-SEGMEN-ASR yang atomik. Brief 27 MEMPERBAIKI penghalang itu: word-level
    # timestamp dari whisper-cli JSON dikembalikan (tanpa mengubah decoding/teks),
    # jadi merge kini menempatkan tiap kalimat pada waktu yang tepat. Dengan itu
    # pemecah ITD BARU berguna -> dinyalakan default (timpaan Architect brief 27).
    # Urutan: ITD memecah -> embedding mengenali -> merge menempatkan per kalimat.
    use_itd_split: bool = True

    # Penghalusan word-level di akhir run (brief 27): re-merge dgn word-timestamp
    # dari whisper-cli JSON untuk .txt final yang lebih presisi. Tak mengubah teks
    # (decode sama). Matikan untuk kembali ke atribusi level-segmen lama.
    use_word_refine: bool = True
    # Lompatan ITD minimum (sampel) untuk dianggap pergantian arah. Konservatif:
    # rentang antar-speaker se-file ~±5,7 jadi >=6 memisahkan sisi berlawanan.
    itd_min_jump: float = 6.0
    # Durasi minimum arah baru harus bertahan (detik) sebelum diakui batas —
    # membunuh kedipan derau satu-jendela. Konservatif demi anti over-split.
    itd_min_run: float = 0.35

    # --- model (offline; diisi absolut saat runtime bila kosong) ---
    whisper_model: str = "large-v3"   # nama subfolder di models/faster-whisper-*
    models_dir: Path = field(default_factory=lambda: MODELS_DIR)

    def effective_initial_prompt(self) -> str:
        """Initial prompt yang benar-benar dipakai backend whisper-cli.

        Urutan: prompt eksplisit dari user menang; kalau kosong, pakai contoh pola
        tanda baca SEBAHASA audio dari ASR_PUNCTUATION_PROMPTS. Bahasa "auto" tak
        dapat prompt (lihat catatan tabel: salah bahasa = whisper menerjemahkan).

        Sengaja TIDAK dipakai faster-whisper: keruntuhan tanda baca yang jadi alasan
        knob ini diukur pada whisper.cpp (yang mewariskan transkrip sebagai konteks
        lewat -mc). Jangan mengubah backend yang belum diukur."""
        explicit = (self.asr_initial_prompt or "").strip()
        if explicit:
            return explicit
        return ASR_PUNCTUATION_PROMPTS.get(str(self.primary_language).lower(), "")

    def tuning_for_diarizer(self, diarizer_name: str):
        """(min_turn, min_speaker_frac, island_max_s) untuk diarizer yang BENAR-BENAR
        dipakai — bukan yang diminta.

        Dipanggil setelah fallback diselesaikan, jadi kalau mode Akurat jatuh ke
        sherpa, knob sherpa ikut terpakai. Lihat catatan preset di atas."""
        if diarizer_name == "pyannote":
            return (self.pyannote_diar_min_turn,
                    self.pyannote_diar_min_speaker_frac,
                    self.pyannote_merge_island_max_s)
        return (self.diar_min_turn, self.diar_min_speaker_frac,
                self.merge_island_max_s)

    @property
    def faster_whisper_dir(self) -> Path:
        """Folder model CTranslate2 untuk backend A."""
        return self.models_dir / f"faster-whisper-{self.whisper_model}"

    @property
    def diarization_dir(self) -> Path:
        """Folder model diarization sherpa-onnx (segmentation + embedding)."""
        return self.models_dir / "diarization"

    @property
    def whisper_ggml_path(self) -> Path:
        """Model GGML untuk whisper.cpp Backend B (Vulkan)."""
        return self.models_dir / "whisper" / "ggml-large-v3-q5_0.bin"

    @property
    def whispercli_exe(self) -> Path:
        """Binary whisper-cli Vulkan (subprocess Backend B)."""
        return PROJECT_ROOT / "vendor" / "whisper-cli" / "whisper-cli.exe"

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


@dataclass
class Config:
    # --- pemilihan hardware / backend ---
    build_profile: str = "amd"        # ditimpa oleh profile.json bawaan build
    allow_vulkan: bool = True         # matikan untuk memaksa CPU di AMD
    asr_backend: str = "auto"         # "auto" | "faster-whisper" | "whispercpp"
    asr_compute_type: str = ""        # kosong = biar selector yang pilih

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
    whispercpp_max_context: int = 8

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

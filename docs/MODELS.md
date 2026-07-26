# Models — PolyScribe

Daftar model AI yang dipakai PolyScribe: sumber, lisensi, ukuran, lokasi disk,
dan cara download. **Model tidak di-commit** ke repo — diunduh sekali di setup
via `scripts/download_models.py`.

---

## Ringkasan

| Model | Peran | Sumber | Lisensi | Ukuran | Wajib? |
|-------|-------|--------|---------|--------|--------|
| Whisper large-v3 (CTranslate2) | ASR utama | HF `Systran/faster-whisper-large-v3` | MIT | ~3.1 GB | ✅ ya |
| sherpa segmentation (pyannote-3.0) | Diarization Cepat | GitHub `k2-fsa/sherpa-onnx` releases | MIT | ~6 MB | ✅ ya |
| sherpa embedding (3D-Speaker CAM++) | Diarization Cepat | GitHub `k2-fsa/sherpa-onnx` releases | Apache 2.0 | ~28 MB | ✅ ya |
| whisper.cpp GGML large-v3 q5_0 | ASR Vulkan (AMD) | HF `ggerganov/whisper.cpp` | MIT | ~1.1 GB | ⚠️ AMD only |
| pyannote community-1 | Diarization Akurat | HF `pyannote/speaker-diarization-community-1` | MIT (code) + Community license (weights) | ~33 MB | ⚠️ Mode Akurat |

**Total minimum plan A** (transkripsi + Cepat): ~3.2 GB.
**Total lengkap** (dengan Akurat + Vulkan AMD): ~4.3 GB.
**Untuk NVIDIA saja** (tanpa Vulkan): ~3.2 GB + pyannote 33 MB = ~3.3 GB.

---

## Cara unduh

### Semua model plan A (default)

```powershell
$py = ".\.venv\Scripts\python.exe"
& $py scripts\download_models.py
```

Default mengunduh: faster-whisper + sherpa diarization + whisper.cpp GGML
(Vulkan). Kalau di NVIDIA (tidak perlu Vulkan), pakai selektif:

```powershell
& $py scripts\download_models.py --only faster-whisper
& $py scripts\download_models.py --only diarization
```

### Pyannote (Mode Akurat, opsional)

Butuh **dua langkah manual sekali**:

1. Buat HF token: <https://huggingface.co/settings/tokens>
2. Terima lisensi: <https://huggingface.co/pyannote/speaker-diarization-community-1>
   → klik **"Agree and access repository"**

Lalu:
```powershell
& $py scripts\download_models.py --only pyannote --hf-token hf_xxxxxxxxxxxx
```

Panduan lengkap dengan screenshot: [CARA_UNDUH_PYANNOTE.md](../CARA_UNDUH_PYANNOTE.md).

**Token hanya dipakai sekali saat build.** Runtime pyannote menggunakan
`HF_HUB_OFFLINE=1` — tidak menyentuh jaringan / token.

---

## Lokasi di disk

Semua di bawah `models/` (relatif ke root repo):

```
models/
├── faster-whisper-large-v3/
│   ├── model.bin              (~3.1 GB)
│   ├── config.json
│   ├── preprocessor_config.json
│   ├── tokenizer.json
│   └── vocabulary.json
├── diarization/
│   ├── sherpa-onnx-pyannote-segmentation-3-0.onnx    (~6 MB)
│   ├── 3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx  (~28 MB)
│   └── pyannote/                                     (opsional)
│       ├── config.yaml
│       ├── segmentation/
│       ├── embedding/
│       └── plda/
└── whisper/                                          (opsional, AMD)
    └── ggml-large-v3-q5_0.bin                        (~1.1 GB)
```

---

## Runtime: offline penuh

Setelah download selesai, runtime **tidak menyentuh jaringan**:

- `faster-whisper` di-load dengan `local_files_only=True` — tidak akan coba
  tarik update dari HF.
- `pyannote` di-load dengan `HF_HUB_OFFLINE=1` di environment — tidak butuh
  token, tidak butuh internet.
- `sherpa-onnx` selalu offline (model diakses via path file).

Bukti privasi ini adalah salah satu janji produk (lihat
[PRODUCT_SPEC.md §5 NFR-1](PRODUCT_SPEC.md#52-non-functional-requirements)).

---

## Lisensi & compliance

Untuk pemakaian **internal / pribadi**, semua lisensi di atas mengizinkan
tanpa batasan. Untuk **redistribusi** (mis. bundel model ke installer):

- **Whisper (MIT)** — bebas.
- **sherpa segmentation** — turunan dari pyannote/segmentation-3.0
  (MIT). Bebas dengan attribution.
- **sherpa embedding (CAM++)** — Apache 2.0. Bebas dengan attribution & NOTICE
  file bila diubah.
- **whisper.cpp GGML** — MIT (dari ggerganov). Bebas dengan attribution.
- **pyannote community-1** — modelnya di bawah "Community license" HF (bukan
  MIT). Perlu review sendiri untuk distribusi ulang. Untuk pemakaian internal
  di rekaman kamu sendiri, tidak masalah.

Kalau kamu berencana redistribute PolyScribe **dengan model dibundel**, cek
ulang lisensi masing-masing model di halaman sumbernya. PolyScribe (kode)
sendiri di bawah Apache 2.0 (lihat [LICENSE](../LICENSE)).

---

## Alternatif model (di luar default)

Infrastruktur `polyscribe` mendukung mengganti model tanpa mengubah kode:

**Whisper varian lain** (mis. `medium`, `small`, `turbo`) — ubah
`config.whisper_model` di `polyscribe/config.py`. Folder subdirektori di
`models/` harus di-rename sesuai (`faster-whisper-medium`, dst) atau download
manual dari `Systran/faster-whisper-<size>`.

**Embedding diarization lain** — set `config.diar_embedding` ke substring nama
file yang diinginkan. Default kosong = auto (WeSpeaker/ResNet diutamakan).

Kalau hardware kamu terbatas VRAM (< 6 GB), pertimbangkan varian `medium` +
`compute_type=int8_float16`. **Bukan default v1** — perlu tuning manual.

---

## Kalau download gagal

- **Menggantung di 0 byte:** backend Xet HuggingFace kadang bermasalah tanpa
  token. Skrip sudah set `HF_HUB_DISABLE_XET=1` secara default; kalau masih,
  paksa manual:
  ```powershell
  $env:HF_HUB_DISABLE_XET = "1"
  & $py scripts\download_models.py
  ```
- **401 Unauthorized** untuk pyannote — token / lisensi. Lihat
  [TROUBLESHOOTING.md](../TROUBLESHOOTING.md#download_modelspy---only-pyannote-gagal-401-unauthorized).
- **Jaringan lambat** — model whisper 3 GB butuh waktu. Bandwidth realistis
  ~5-10 MB/s ke HF di Indonesia. Kalau terputus, jalankan ulang skrip; ia
  skip file yang sudah ada.

---

## Referensi

- Whisper: <https://github.com/openai/whisper> · <https://huggingface.co/openai/whisper-large-v3>
- faster-whisper: <https://github.com/SYSTRAN/faster-whisper>
- whisper.cpp: <https://github.com/ggerganov/whisper.cpp>
- sherpa-onnx: <https://github.com/k2-fsa/sherpa-onnx>
- pyannote.audio: <https://github.com/pyannote/pyannote-audio>
- pyannote community-1: <https://huggingface.co/pyannote/speaker-diarization-community-1>
- 3D-Speaker: <https://github.com/modelscope/3D-Speaker>

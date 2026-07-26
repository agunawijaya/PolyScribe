"""PolyScribe — transkripsi + diarization audio rapat, offline.

Paket ini menyusun pipeline: audio -> 16k mono -> (ASR || diarization) ->
merge by overlap -> tulis .txt di sebelah file audio. Titik yang bisa ditukar
(ASR dan diarization) ada di sub-paket masing-masing.
"""

__version__ = "0.1.0"


def _bootstrap_windows_cuda_dlls() -> None:
    # Di Windows, ctranslate2 memuat cublas64_*.dll lewat LoadLibraryW default
    # (yang hanya lihat PATH, BUKAN os.add_dll_directory). Paket pip
    # nvidia-cublas-cu12 / nvidia-cudnn-cu12 menaruh DLL-nya di site-packages
    # yang tak masuk PATH — tanpa bantuan ini encoder crash saat encode()
    # dengan "cublas64_12.dll is not found or cannot be loaded".
    #
    # No-op di non-Windows dan di mesin tanpa paket nvidia-* (mis. laptop AMD),
    # jadi perbaikan ini aman ikut satu basis kode.
    import os
    if os.name != "nt":
        return
    import site
    from pathlib import Path
    dirs = [
        Path(sp) / sub
        for sp in site.getsitepackages() + [site.getusersitepackages()]
        for sub in ("nvidia/cublas/bin", "nvidia/cudnn/bin")
        if (Path(sp) / sub).is_dir()
    ]
    if not dirs:
        return
    os.environ["PATH"] = os.pathsep.join(
        [str(d) for d in dirs] + [os.environ.get("PATH", "")]
    )
    for d in dirs:
        os.add_dll_directory(str(d))


_bootstrap_windows_cuda_dlls()

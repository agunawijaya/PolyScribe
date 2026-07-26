"""PolyScribe — transkripsi + diarization audio rapat, offline.

Paket ini menyusun pipeline: audio -> 16k mono -> (ASR || diarization) ->
merge by overlap -> tulis .txt di sebelah file audio. Titik yang bisa ditukar
(ASR dan diarization) ada di sub-paket masing-masing.
"""

__version__ = "0.1.0"

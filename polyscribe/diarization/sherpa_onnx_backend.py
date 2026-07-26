"""Diarization plan A — sherpa-onnx (CPU).

Segmentation = pyannote-segmentation-3.0 (ONNX), embedding = model 3D-Speaker.
Jumlah pembicara auto: num_clusters=-1 + cluster_threshold. Threshold inilah
satu-satunya knob yang menentukan kecenderungan memecah/menggabung pembicara —
dituning di file rapat asli, bukan ditebak.
"""

from pathlib import Path

from .base import Diarizer, SpeakerTurn
from ..progress import ProgressEvent


class SherpaOnnxDiarizer(Diarizer):
    name = "sherpa"

    def __init__(self, config):
        self.config = config
        self._sd = None
        self._sample_rate = 16000
        self._emb_model = None       # path model embedding (untuk fitur spasial)
        self._embedder = None        # SpeakerEmbeddingExtractor lazy (spasial saja)

    def _find_model(self, folder: Path, *needles) -> str:
        """Cari satu file .onnx yang namanya memuat semua `needles`.

        Nama rilis model kadang berubah versi, jadi kita cocokkan pola daripada
        mengunci nama persis — lebih tahan banting saat model di-update.
        """
        needles = [n.lower() for n in needles]
        for p in sorted(folder.rglob("*.onnx")):
            name = p.name.lower()
            if all(n in name for n in needles):
                return str(p)
        raise FileNotFoundError(
            f"Model diarization tidak ditemukan (butuh {needles}) di {folder}. "
            f"Jalankan scripts/download_models.py dulu."
        )

    def _find_embedding(self, folder: Path) -> str:
        """Cari model embedding speaker (bukan segmentation).

        Agnostik terhadap model: terima drop-in apa pun (WeSpeaker, 3D-Speaker,
        CAMPPlus, ERes2Net). Bila config.diar_embedding diisi, cocokkan substring
        itu; jika tidak, pilih dengan urutan preferensi (WeSpeaker/ResNet dulu —
        pemisahan English rapat lebih baik dari CAMPPlus zh+en).
        """
        onnx = [p for p in sorted(folder.rglob("*.onnx"))
                if "segmentation" not in p.name.lower()]
        if not onnx:
            raise FileNotFoundError(
                f"Model embedding diarization tidak ditemukan di {folder}. "
                f"Jalankan scripts/download_models.py dulu."
            )
        hint = getattr(self.config, "diar_embedding", "") or ""
        if hint:
            for p in onnx:
                if hint.lower() in p.name.lower():
                    return str(p)
        for kw in ("wespeaker", "resnet", "eres2net", "campplus", "3dspeaker"):
            for p in onnx:
                if kw in p.name.lower():
                    return str(p)
        return str(onnx[0])

    def load(self) -> None:
        import sherpa_onnx

        diar_dir = Path(self.config.diarization_dir)
        seg_model = self._find_model(diar_dir, "segmentation")
        emb_model = self._find_embedding(diar_dir)
        self._emb_model = emb_model      # dipakai ulang untuk fitur spasial

        cfg = sherpa_onnx.OfflineSpeakerDiarizationConfig(
            segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                    model=seg_model,
                ),
            ),
            embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=emb_model),
            clustering=sherpa_onnx.FastClusteringConfig(
                num_clusters=-1,                       # auto: JANGAN minta jumlah manual
                threshold=float(self.config.cluster_threshold),
            ),
            # min_duration_on dinaikkan (M1c) untuk membuang blip aktif ultra-pendek
            # yang jadi biang over-split di file panjang; min_duration_off
            # menjembatani jeda pendek. Keduanya dari config supaya bisa dituning.
            min_duration_on=float(getattr(self.config, "diar_min_duration_on", 1.0)),
            min_duration_off=float(getattr(self.config, "diar_min_duration_off", 0.5)),
        )
        if not cfg.validate():
            raise RuntimeError(
                "Konfigurasi diarization sherpa-onnx tidak valid — cek path model."
            )

        self._sd = sherpa_onnx.OfflineSpeakerDiarization(cfg)
        self._sample_rate = self._sd.sample_rate

    def diarize(self, wav_16k_mono_path: str, progress,
                stereo_path: str | None = None) -> list[SpeakerTurn]:
        import soundfile as sf

        if self._sd is None:
            self.load()

        # Baca WAV 16k mono jadi float32 mono. always_2d=False -> array 1D.
        samples, sr = sf.read(wav_16k_mono_path, dtype="float32", always_2d=False)
        if samples.ndim > 1:            # jaga-jaga kalau stereo lolos
            samples = samples[:, 0]
        if sr != self._sample_rate:
            raise ValueError(
                f"WAV harus {self._sample_rate} Hz, tapi {sr} Hz. "
                f"Decode lewat audio.decode_to_16k_mono dulu."
            )

        progress.emit(ProgressEvent(
            stage="diarize", fraction=0.0, message="diarization",
        ))

        # Callback progress dipanggil sherpa selama proses. Ia mengembalikan int
        # (0 = lanjut). Kita pakai untuk menggerakkan indikator.
        def on_progress(num_done, num_total):
            frac = (num_done / num_total) if num_total else 0.0
            progress.emit(ProgressEvent(
                stage="diarize",
                fraction=min(max(frac, 0.0), 1.0),
                message="diarization",
            ))
            return 0

        result = self._sd.process(samples, callback=on_progress)
        segments = result.sort_by_start_time()

        # sherpa memberi ID cluster mentah (bisa meloncat: 0, 6, 43, ...).
        # Kita nomori ulang berurutan sesuai urutan kemunculan supaya labelnya
        # rapi & intuitif: SPEAKER_00, SPEAKER_01, ... Pemetaan stabil dalam
        # satu file — cukup untuk janji "label stabil".
        label_of = {}
        turns = []
        for s in segments:
            raw = int(s.speaker)
            if raw not in label_of:
                label_of[raw] = f"SPEAKER_{len(label_of):02d}"
            turns.append(SpeakerTurn(
                start=float(s.start),
                end=float(s.end),
                speaker=label_of[raw],
            ))

        # --- Lebur speaker over-split (brief 29): setelah clustering native,
        # gabungkan cluster yang centroid embedding-nya mirip. Menutup over-split
        # file panjang (Std-12 15->~6-7) tanpa merusak file pendek. HANYA menggabung.
        # Butuh mono (ada); dilewati bila mati / turn nihil. ---
        if getattr(self.config, "use_speaker_merge", False) and turns:
            try:
                turns = self._merge_similar_speakers(turns, samples)
            except Exception as e:
                progress.emit(ProgressEvent(
                    stage="diarize", fraction=1.0,
                    message=f"lebur speaker dilewati ({type(e).__name__})"))

        # --- Pemecah-turn ITD (brief 26): pecah turn di lompatan arah yang
        # bertahan, lalu sub-turn dikenali embedding & dipetakan ke speaker yang
        # SUDAH ada. Menyerang #2 tanpa menyentuh segmenter/clustering/ASR.
        # Otomatis dilewati bila mati / stereo tak ada / turn nihil. ---
        if getattr(self.config, "use_itd_split", False) and stereo_path and turns:
            try:
                turns = self._split_turns_by_itd(turns, samples, stereo_path)
            except Exception as e:
                progress.emit(ProgressEvent(
                    stage="diarize", fraction=1.0,
                    message=f"pemecah ITD dilewati ({type(e).__name__})"))

        # --- Isyarat spasial (brief 25): campurkan arah suara ke embedding lalu
        # kelompokkan ulang. Otomatis dilewati bila mati/stereo tak ada/turn nihil. ---
        if getattr(self.config, "use_spatial_cues", False) and stereo_path and turns:
            try:
                turns = self._augment_with_spatial(turns, samples, stereo_path)
            except Exception as e:
                # Fitur tambahan tak boleh menjatuhkan diarization inti — kalau ada
                # yang salah, kembali ke hasil native dengan jujur di log.
                progress.emit(ProgressEvent(
                    stage="diarize", fraction=1.0,
                    message=f"isyarat spasial dilewati ({type(e).__name__})",
                ))

        progress.emit(ProgressEvent(
            stage="diarize", fraction=1.0, message="diarization selesai",
        ))
        return turns

    # ---------------------------------------------------------------------------
    # Isyarat spasial: embedding suara + arah (ILD/ITD) -> clustering ulang.
    # ---------------------------------------------------------------------------

    def _embed_turn(self, mono_samples, start_s: float, end_s: float):
        """Vektor embedding speaker (192-d) untuk satu window mono. None bila
        window terlalu pendek untuk andal."""
        import numpy as np

        if self._embedder is None:
            import sherpa_onnx
            self._embedder = sherpa_onnx.SpeakerEmbeddingExtractor(
                sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=self._emb_model)
            )
        sr = self._sample_rate
        i0 = max(0, int(start_s * sr))
        i1 = min(len(mono_samples), int(end_s * sr))
        if i1 - i0 < int(0.5 * sr):     # < 0.5 dtk: embedding tak reliabel
            return None
        stream = self._embedder.create_stream()
        stream.accept_waveform(sr, mono_samples[i0:i1])
        stream.input_finished()
        if not self._embedder.is_ready(stream):
            return None
        return np.asarray(self._embedder.compute(stream), dtype=np.float64)

    def _augment_with_spatial(self, turns, mono_samples, stereo_path):
        """Gabungkan embedding suara tiap turn dengan fitur arah (ILD/ITD) lalu
        kelompokkan ulang. Turn yang embedding/spasialnya tak bisa dihitung tetap
        memakai label native-nya (tak dibuang)."""
        import numpy as np
        import wave as _wave

        from .. import spatial

        # Baca kanal L/R dari WAV stereo 16k.
        with _wave.open(str(stereo_path), "rb") as w:
            if w.getnchannels() < 2 or w.getframerate() != self._sample_rate:
                return turns
            raw = w.readframes(w.getnframes())
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
        left, right = data[0::2], data[1::2]

        embs, ilds, itds, idx = [], [], [], []
        for i, t in enumerate(turns):
            e = self._embed_turn(mono_samples, t.start, t.end)
            sp = spatial.turn_features(left, right, self._sample_rate, t.start, t.end)
            if e is None or sp is None:
                continue
            # L2-normalisasi embedding: jarak Euclidean antar-unit setara cosine,
            # jadi bobot spasial punya arti yang konsisten lintas file.
            norm = np.linalg.norm(e)
            if norm < 1e-9:
                continue
            embs.append(e / norm)
            ilds.append(sp[0])
            itds.append(sp[1])
            idx.append(i)

        # Terlalu sedikit turn yang bisa diukur -> biarkan native.
        if len(idx) < 2:
            return turns

        w_spatial = float(getattr(self.config, "spatial_weight", 0.3))
        thr = float(getattr(self.config, "spatial_cluster_threshold", 0.72))

        emb_mat = np.vstack(embs)                                   # (m, 192) unit
        spatial_z = np.stack([spatial.zscore(np.array(ilds)),
                              spatial.zscore(np.array(itds))], axis=1)  # (m, 2)
        augmented = np.hstack([emb_mat, w_spatial * spatial_z])     # (m, 194)

        labels = spatial.agglomerative(augmented, threshold=thr)

        # Terapkan label baru ke turn yang terukur; turn yang dilewati (embedding
        # gagal) diberi speaker dari label baru turn terukur TERDEKAT supaya konsisten.
        new_label_str = {}
        measured_new = {}
        for pos, i in enumerate(idx):
            measured_new[i] = labels[pos]
        for i, t in enumerate(turns):
            if i in measured_new:
                lab = measured_new[i]
            else:
                lab = self._nearest_measured_label(i, idx, measured_new)
            if lab is None:
                continue     # tak ada acuan: pertahankan label native
            t.speaker = new_label_str.setdefault(lab, f"SPEAKER_{lab:02d}")
        return turns

    @staticmethod
    def _nearest_measured_label(i, measured_indices, measured_new):
        """Label turn terukur terdekat (indeks) untuk mengisi turn yang dilewati."""
        best = None
        for j in measured_indices:
            d = abs(j - i)
            if best is None or d < best[0]:
                best = (d, measured_new[j])
        return best[1] if best else None

    # ---------------------------------------------------------------------------
    # Lebur speaker over-split file panjang (brief 29): gabung centroid mirip.
    # ---------------------------------------------------------------------------

    def _merge_similar_speakers(self, turns, mono_samples):
        """Lebur speaker native yang centroid embedding-nya mirip — TAPI lindungi
        peserta nyata (brief 35 §3).

        Menutup over-split file panjang (satu orang terpecah jadi beberapa cluster
        karena variasi suara). Tapi ambang tunggal 0.55 (brief 29) terbukti melebur
        peserta NYATA yang berbeda (OPPO 25:04) karena mereka bisa terdengar mirip.
        Obat: ambang BERGANTUNG PORSI (dua tingkat), keduanya lebih ketat dari 0.55:
          - dua speaker substantial (porsi >= merge_protect_frac): hanya bila centroid
            SANGAT mirip (< merge_major_threshold) — jangan lebur dua peserta nyata;
          - selain itu (ada fragmen kecil): serap bila < merge_fragment_threshold.
        HANYA menggabung -> tak menambah over-split; tak menghapus peserta minor."""
        import numpy as np

        # Centroid HANYA dari speaker MAYOR (yang cleanup pertahankan). Krusial
        # (brief 29): centroid dari SEMUA label mentah (~120 minor spurious di Std-12)
        # berisik. Turn minor dibiarkan; cleanup yang melebur mereka.
        major = self._major_speakers(turns)

        # Porsi tiap speaker mayor (fraksi dari total bicara) — penentu "substantial".
        dur = {}
        for t in turns:
            dur[t.speaker] = dur.get(t.speaker, 0.0) + (t.end - t.start)
        total = sum(dur.values()) or 1.0

        # Centroid unit per label mayor (embed turn >= 0.5 dtk; rata-rata; L2-normal).
        acc = {}
        for t in turns:
            if t.speaker not in major:
                continue
            e = self._embed_turn(mono_samples, t.start, t.end)
            if e is None:
                continue
            n = np.linalg.norm(e)
            if n < 1e-9:
                continue
            acc.setdefault(t.speaker, []).append(e / n)

        labels = list(acc.keys())
        if len(labels) < 2:
            return turns          # tak ada yang bisa dilebur

        cents = np.vstack([np.mean(np.vstack(acc[spk]), axis=0) for spk in labels])
        cents = cents / (np.linalg.norm(cents, axis=1, keepdims=True) + 1e-9)
        shares = [dur.get(spk, 0.0) / total for spk in labels]

        frag_thr = float(getattr(self.config, "merge_fragment_threshold", 0.45))
        major_thr = float(getattr(self.config, "merge_major_threshold", 0.35))
        protect = float(getattr(self.config, "merge_protect_frac", 0.05))
        clusters = self._protected_agglomerative(cents, shares, frag_thr, major_thr,
                                                 protect)

        # Peta label native -> label gabungan. Speaker tanpa embedding (turn ultra
        # pendek saja) dibiarkan apa adanya (konservatif: jangan lebur yang tak terukur).
        merged_of = {spk: cl for spk, cl in zip(labels, clusters)}
        cl_to_str = {}
        out = []
        for t in turns:
            if t.speaker in merged_of:
                cl = merged_of[t.speaker]
                lab = cl_to_str.setdefault(cl, f"MSPK_{cl:02d}")
                out.append(SpeakerTurn(t.start, t.end, lab))
            else:
                out.append(SpeakerTurn(t.start, t.end, t.speaker))
        return out

    @staticmethod
    def _protected_agglomerative(cents, shares, frag_thr, major_thr, protect_frac):
        """UPGMA average-linkage (seperti spatial.agglomerative) TAPI dengan gerbang
        bergantung porsi per-langkah (brief 35 §3):
          - pasangan yang KEDUANYA substantial (porsi >= protect_frac) hanya dilebur
            bila jarak < major_thr (ketat) — melindungi dua peserta nyata dari lebur;
          - selain itu (ada fragmen kecil) dilebur bila jarak < frag_thr.
        Kembalikan id-cluster 0..k-1 per baris (urutan input). Ditulis di sini (bukan
        di spatial.py yang generik) karena logikanya spesifik speaker-share."""
        import numpy as np

        X = np.asarray(cents, dtype=np.float64)
        n = len(X)
        if n < 2:
            return [0] * n
        D = np.sqrt(((X[:, None, :] - X[None, :, :]) ** 2).sum(-1))
        np.fill_diagonal(D, np.inf)
        outer = max(frag_thr, major_thr)     # tak ada peleburan di atas ini
        size = [1] * n
        share = list(shares)                 # porsi cluster; dijumlah saat merge
        parent = list(range(n))
        active = list(range(n))
        while len(active) > 1:
            sub = D[np.ix_(active, active)]
            flat = int(np.argmin(sub))
            ai, bi = divmod(flat, len(active))
            dmin = sub[ai, bi]
            if dmin > outer:
                break
            ia, ib = active[ai], active[bi]
            both_substantial = (share[ia] >= protect_frac and share[ib] >= protect_frac)
            eff = major_thr if both_substantial else frag_thr
            if dmin >= eff:
                D[ia, ib] = D[ib, ia] = np.inf   # pasangan ini dilindungi -> cari lain
                continue
            na, nb = size[ia], size[ib]
            for k in active:
                if k == ia or k == ib:
                    continue
                D[ia, k] = D[k, ia] = (na * D[ia, k] + nb * D[ib, k]) / (na + nb)
            size[ia] = na + nb
            share[ia] = share[ia] + share[ib]
            parent[ib] = ia
            D[ib, :] = np.inf
            D[:, ib] = np.inf
            active.remove(ib)

        def root(x):
            while parent[x] != x:
                x = parent[x]
            return x

        reps, labels = {}, []
        for i in range(n):
            r = root(i)
            if r not in reps:
                reps[r] = len(reps)
            labels.append(reps[r])
        return labels

    # ---------------------------------------------------------------------------
    # Pemecah-turn berbasis ITD (brief 26): ITD memecah, embedding mengenali.
    # ---------------------------------------------------------------------------

    def _read_stereo(self, stereo_path):
        """(L, R) float32 dari WAV 16k stereo, atau None bila bukan stereo 16k."""
        import numpy as np
        import wave

        with wave.open(str(stereo_path), "rb") as w:
            if w.getnchannels() < 2 or w.getframerate() != self._sample_rate:
                return None
            raw = w.readframes(w.getnframes())
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
        return data[0::2], data[1::2]

    def _major_speakers(self, turns):
        """Himpunan speaker 'mayor' native — yang akan DIPERTAHANKAN cleanup
        (total bicara >= min_speaker_frac dari total). PENTING: sub-turn hanya
        boleh dipetakan ke sini, BUKAN ke label mentah minor — kalau tidak,
        re-atribusi menghidupkan kembali speaker yang harusnya dilebur -> over-split
        (Std-11 7->10, ketahuan di gerbang brief 26)."""
        frac = float(getattr(self.config, "diar_min_speaker_frac", 0.010))
        floor = 3.0
        tot = {}
        for t in turns:
            tot[t.speaker] = tot.get(t.speaker, 0.0) + (t.end - t.start)
        total = sum(tot.values()) or 1.0
        thr = max(floor, frac * total)
        major = {sp for sp, d in tot.items() if d >= thr}
        return major or {max(tot, key=tot.get)}   # jaga-jaga: minimal 1

    def _speaker_centroids(self, turns, mono_samples, allowed=None):
        """Centroid embedding (unit) per label speaker native — 'siapa' acuan untuk
        mengenali sub-turn hasil pecahan. `allowed` membatasi ke speaker mayor
        supaya count tak meledak (lihat _major_speakers)."""
        import numpy as np

        acc = {}
        for t in turns:
            if allowed is not None and t.speaker not in allowed:
                continue
            e = self._embed_turn(mono_samples, t.start, t.end)
            if e is None:
                continue
            n = np.linalg.norm(e)
            if n < 1e-9:
                continue
            acc.setdefault(t.speaker, []).append(e / n)
        cents = {}
        for spk, vs in acc.items():
            m = np.mean(np.vstack(vs), axis=0)
            nm = np.linalg.norm(m)
            if nm > 1e-9:
                cents[spk] = m / nm
        return cents

    @staticmethod
    def _nearest_centroid(emb, centroids):
        """Label speaker (yang SUDAH ada) dengan centroid paling mirip (cosine).
        Tak pernah menciptakan speaker baru -> aman dari over-split."""
        import numpy as np

        n = np.linalg.norm(emb)
        if n < 1e-9 or not centroids:
            return None
        u = emb / n
        best, best_spk = -2.0, None
        for spk, c in centroids.items():
            s = float(np.dot(u, c))
            if s > best:
                best, best_spk = s, spk
        return best_spk

    def _split_turns_by_itd(self, turns, mono_samples, stereo_path):
        """Pecah turn di lompatan ITD yang bertahan; label tiap sub-turn via
        centroid speaker yang sudah ada. Sub-turn terlalu pendek untuk embedding
        andal -> pertahankan label induk (biar cleanup/merge menanganinya)."""
        from .base import SpeakerTurn
        from .. import spatial

        lr = self._read_stereo(stereo_path)
        if lr is None:
            return turns
        left, right = lr

        min_jump = float(getattr(self.config, "itd_min_jump", 6.0))
        min_run = float(getattr(self.config, "itd_min_run", 0.35))
        sr = self._sample_rate

        # Pass 1 (murah, tanpa embedding): rencanakan batas per turn. Turn terlalu
        # pendek untuk memuat >1 giliran dilewati.
        plan = {}
        for i, t in enumerate(turns):
            if (t.end - t.start) < (2 * min_run + 0.4):
                continue
            times, itds = spatial.itd_track(left, right, sr, t.start, t.end)
            bnds = spatial.find_itd_boundaries(times, itds, min_jump=min_jump,
                                               min_run_s=min_run, hop_s=0.2)
            # buang batas terlalu dekat ke tepi (sub-turn recehan)
            bnds = [b for b in bnds if t.start + 0.4 < b < t.end - 0.4]
            if bnds:
                plan[i] = bnds

        if not plan:
            return turns            # tak ada yang dipecah -> nol biaya embedding

        # Baru sekarang bayar embedding: centroid speaker MAYOR native untuk
        # pengenalan. Dibatasi ke mayor -> sub-turn tak pernah dipetakan ke label
        # minor yang harusnya dilebur -> jumlah speaker tak bisa naik di atas native.
        major = self._major_speakers(turns)
        centroids = self._speaker_centroids(turns, mono_samples, allowed=major)

        out = []
        for i, t in enumerate(turns):
            if i not in plan:
                out.append(t)
                continue
            cuts = [t.start] + plan[i] + [t.end]
            for a, b in zip(cuts, cuts[1:]):
                label = t.speaker
                if (b - a) >= 0.5:              # cukup panjang untuk embedding andal
                    e = self._embed_turn(mono_samples, a, b)
                    if e is not None:
                        spk = self._nearest_centroid(e, centroids)
                        if spk is not None:
                            label = spk
                out.append(SpeakerTurn(start=a, end=b, speaker=label))
        return out

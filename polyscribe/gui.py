"""Entry Milestone 2 — jendela GUI untuk user non-teknis.

Ini cuma BUNGKUS tipis di atas mesin yang sudah ada. GUI memanggil satu fungsi:
transcribe_file(audio_path, config, sink) dari pipeline.py. Tidak ada logika
transkripsi/diarization di sini.

Jalankan:
    python -m polyscribe.gui

Aturan aman-thread Tkinter (sumber bug klasik):
- Thread utama HANYA menyentuh widget.
- transcribe_file berjalan di thread pekerja (memblokir 5-25 menit).
- Jembatan satu-satunya = queue.Queue. Sink pekerja cuma queue.put(...).
- Thread utama menguras antrean lewat root.after(...) dan meng-update widget.

Tata letak (2026-09-21): Notebook 2 tab.
- Tab 1 "Transkripsi": alur asli (pilih file -> Mulai).
- Tab 2 "Backend & API Keys": kelola key cloud (write-once, mask setelah simpan).
"""

import multiprocessing as mp
import os
import queue
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import keystore
from .asr.cloud import list_providers, get_provider_info
from .config import Config
from .diarization import pyannote_availability
from .pipeline import run_pipeline_to_queue, log_cancel_event
from .progress import ProgressEvent


# Label mode pelabelan pembicara (brief 37) -> config.diarizer_choice.
MODE_ACCURATE = "Akurat — pisah pertukaran cepat (lebih lambat)"
MODE_FAST = "Cepat — lebih cepat (pertukaran cepat bisa terlebur)"
MODE_TO_CHOICE = {MODE_ACCURATE: "pyannote", MODE_FAST: "sherpa"}

# Label bahasa dropdown -> kode bahasa Whisper (brief 47). PENTING: ini peta EKSPLISIT,
# bukan logika biner "auto atau en". Kalau pakai biner, memilih "Bahasa Indonesia"
# akan diam-diam jatuh ke "en" (bug "pilihan jatuh ke default salah"). Setiap label di
# dropdown WAJIB punya entri di sini supaya fallback "en" di _build_config tak pernah
# kepakai. Urutan sesuai dropdown. Hanya Inggris/Indonesia yang di-lock; Arab sengaja
# TIDAK ada — Arab selalu sempilan & ditangani lewat Auto (keputusan user).
LANG_LABEL_TO_CODE = {
    "Inggris": "en",
    "Bahasa Indonesia": "id",
    "Auto (multibahasa)": "auto",
}
# Petunjuk kecil di bawah dropdown bahasa (brief 47 #3): kapan lock bahasa vs Auto.
LANG_HINT = ("Pilih satu bahasa hanya bila rekaman MURNI bahasa itu dari awal sampai "
             "akhir. Untuk rekaman campur (termasuk yang ada sempilan bahasa lain) — "
             "pakai Auto.")
# Keterangan kecil di bawah dropdown, termasuk peringatan waktu yang jujur.
MODE_HINT = {
    MODE_ACCURATE: "Akurat (pyannote): paling tepat memisahkan pembicara yang saling "
                   "menyela. Lebih lambat — untuk rekaman ~1 jam perkirakan ~1 jam "
                   "pemrosesan.",
    MODE_FAST: "Cepat (sherpa): jauh lebih cepat; pertukaran cepat kadang terlebur "
               "jadi satu pembicara.",
}

# Backend ASR — offline default (batasan keras CLAUDE.md).
BACKEND_OFFLINE = "Offline (bawaan — Whisper large-v3, tanpa internet)"
BACKEND_CLOUD = "Cloud (butuh API key & internet — kualitas lebih tinggi)"


# Nama tahap pipeline -> teks ramah untuk label status.
STAGE_LABEL = {
    "load": "Memuat model",
    # "diarize_prep" = fase BISU sebelum backend mulai melapor progres nyata:
    # sherpa jalan pass segmentasi (~140 dtk untuk file 1 jam) tanpa callback;
    # pyannote menjalankan seluruh pipeline tanpa meneruskan progres. Tanpa
    # penanda terpisah, GUI menampilkan "diarize 0%" diam & user membacanya
    # sebagai freeze — akar keluhan "Memuat model lama sekali" (2026-08).
    "diarize_prep": "Menyiapkan analisis pembicara — bisa beberapa menit di file "
                    "panjang. Jangan tutup jendela",
    # File panjang: diarization bisa beberapa menit. Beri tahu user JANGAN tutup
    # jendela (FINDING-2) — sekarang UI tak lagi beku karena diarization jalan di
    # proses terpisah, tapi label yang jujur mencegah panik/force-quit.
    "diarize": "Menganalisis pembicara — bisa beberapa menit di file panjang. "
               "Jangan tutup jendela",
    "transcribe": "Mentranskripsi",
    "merge": "Merapikan",
    "done": "Selesai",
}

# Tahap yang tak punya granularitas per-detik -> bar berdenyut (indeterminate).
# 'diarize' TIDAK di sini: sherpa mengirim fraction (num_done/num_total), jadi kita
# tampilkan bar determinate yang benar-benar bergerak (FINDING-2 fallback (a)).
# 'diarize_prep' DI sini: fase bisu tanpa progres -> bar berdenyut = "masih hidup".
PULSING_STAGES = ("load", "diarize_prep", "merge")
# Tahap dengan fraction sungguhan -> bar determinate mengikuti event.fraction.
DETERMINATE_STAGES = ("diarize", "transcribe")


class PolyScribeApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("PolyScribe — Transkripsi Rapat")
        # 720 = muat combobox provider terpanjang (60 char × ~7.5 px avg + padding).
        # 600 = muat tab Keys 7 baris tanpa scroll berlebihan.
        root.minsize(720, 600)

        # State run. Pekerja = PROSES terpisah (bukan thread) supaya GIL sherpa saat
        # diarization tak membekukan UI (FINDING-2). Jembatan = multiprocessing.Queue.
        self.audio_path: str | None = None
        self.result_path: str | None = None
        self.queue: "mp.Queue | None" = None
        self.cancel_event = None          # multiprocessing.Event saat jalan
        self.worker: "mp.Process | None" = None
        self._bar_mode = "determinate"   # lacak mode bar biar tak restart terus

        self._build_ui()

    # --- Susunan widget -----------------------------------------------------
    def _build_ui(self):
        # Notebook 2 tab: transkripsi (alur utama) + backend & keys (setup).
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=8)

        self.tab_run = ttk.Frame(self.notebook)
        self.tab_keys = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_run, text="Transkripsi")
        self.notebook.add(self.tab_keys, text="Backend & API Keys")

        self._build_run_tab(self.tab_run)
        self._build_keys_tab(self.tab_keys)

    def _build_run_tab(self, parent):
        pad = {"padx": 10, "pady": 6}
        main = ttk.Frame(parent, padding=12)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)

        # Baris file: nama file + tombol pilih.
        file_row = ttk.Frame(main)
        file_row.grid(row=0, column=0, sticky="ew", **pad)
        file_row.columnconfigure(0, weight=1)
        self.file_label = ttk.Label(file_row, text="Belum ada file dipilih",
                                    relief="groove", anchor="w", padding=6)
        self.file_label.grid(row=0, column=0, sticky="ew")
        self.pick_btn = ttk.Button(file_row, text="Pilih file…",
                                   command=self.on_pick)
        self.pick_btn.grid(row=0, column=1, padx=(8, 0))

        # Baris backend (2026-09-21): Offline default; Cloud memunculkan dropdown
        # provider di baris berikutnya.
        backend_row = ttk.Frame(main)
        backend_row.grid(row=1, column=0, sticky="ew", **pad)
        ttk.Label(backend_row, text="Backend ASR:").grid(row=0, column=0, padx=(0, 4))
        self.backend_var = tk.StringVar(value=BACKEND_OFFLINE)
        # width=58 muat BACKEND_CLOUD (53 char) + margin combobox.
        self.backend_combo = ttk.Combobox(
            backend_row, textvariable=self.backend_var, state="readonly", width=58,
            values=[BACKEND_OFFLINE, BACKEND_CLOUD])
        self.backend_combo.grid(row=0, column=1, sticky="w")
        self.backend_combo.bind("<<ComboboxSelected>>",
                                lambda _e: self._on_backend_changed())

        # Baris cloud provider — tersembunyi bila Offline.
        self.cloud_row = ttk.Frame(main)
        self.cloud_row.grid(row=2, column=0, sticky="ew", **pad)
        ttk.Label(self.cloud_row, text="Provider cloud:").grid(row=0, column=0, padx=(0, 4))
        self.cloud_var = tk.StringVar()
        self._cloud_display_to_key = {p.display_name: p.key for p in list_providers()}
        # Provider terpanjang: "Google Cloud Speech chirp_2 (BEDA dari Google Web
        # Speech)" = 56 char. Beri margin: width=60.
        self.cloud_combo = ttk.Combobox(
            self.cloud_row, textvariable=self.cloud_var, state="readonly", width=60,
            values=[p.display_name for p in list_providers()])
        self.cloud_combo.grid(row=0, column=1, sticky="w")
        self.cloud_combo.bind("<<ComboboxSelected>>",
                              lambda _e: self._update_cloud_hint())
        # Info & peringatan per provider (harga, kapabilitas, catatan).
        self.cloud_hint = ttk.Label(main, text="", anchor="w", foreground="gray30",
                                    wraplength=560, justify="left")
        self.cloud_hint.grid(row=3, column=0, sticky="ew", padx=10)

        # Baris pengaturan minimal: GPU + bahasa.
        opt_row = ttk.Frame(main)
        opt_row.grid(row=4, column=0, sticky="ew", **pad)
        self.gpu_var = tk.BooleanVar(value=True)
        self.gpu_check = ttk.Checkbutton(
            opt_row, text="Gunakan akselerasi GPU", variable=self.gpu_var)
        self.gpu_check.grid(row=0, column=0, sticky="w")

        ttk.Label(opt_row, text="Bahasa:").grid(row=0, column=1, padx=(16, 4))
        self.lang_var = tk.StringVar(value="Inggris")   # default tetap Inggris (PM #2)
        self.lang_combo = ttk.Combobox(
            opt_row, textvariable=self.lang_var, state="readonly", width=22,
            values=list(LANG_LABEL_TO_CODE.keys()))
        self.lang_combo.grid(row=0, column=2, sticky="w")
        # Petunjuk UX (brief 47 #3): lock bahasa hanya untuk rekaman murni; campur -> Auto.
        ttk.Label(opt_row, text=LANG_HINT, foreground="gray40", wraplength=520
                  ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))

        # Baris mode pelabelan pembicara (brief 37): Akurat (pyannote) vs Cepat (sherpa).
        # Dua-duanya menghasilkan teks ASR yang sama; yang beda cuma pemisahan speaker
        # & kecepatan. User memilih per rekaman.
        mode_row = ttk.Frame(main)
        mode_row.grid(row=5, column=0, sticky="ew", **pad)
        ttk.Label(mode_row, text="Mode pembicara:").grid(row=0, column=0, padx=(0, 4))
        self.mode_var = tk.StringVar(value=MODE_ACCURATE)
        # Width harus muat label terpanjang. MODE_FAST = 52 char, MODE_ACCURATE
        # = 46 char. Bug 2026-09-21: width=34 memotong keduanya di combobox +
        # dropdown -> user hanya lihat "Akurat — pisah pertukaran..." tanpa
        # petunjuk "(lebih lambat)". Ttk Combobox tak auto-fit; harus eksplisit.
        self.mode_combo = ttk.Combobox(
            mode_row, textvariable=self.mode_var, state="readonly", width=54,
            values=[MODE_ACCURATE, MODE_FAST])
        self.mode_combo.grid(row=0, column=1, sticky="w")
        self.mode_combo.bind("<<ComboboxSelected>>", lambda _e: self._update_mode_hint())
        # Catatan kecil di bawah dropdown: keterangan mode + peringatan waktu jujur.
        self.mode_hint = ttk.Label(main, text="", anchor="w", foreground="gray40",
                                   wraplength=520)
        self.mode_hint.grid(row=6, column=0, sticky="ew", padx=10)
        self._update_mode_hint()

        # Baris tombol Mulai / Stop.
        btn_row = ttk.Frame(main)
        btn_row.grid(row=7, column=0, sticky="ew", **pad)
        self.start_btn = ttk.Button(btn_row, text="Mulai", command=self.on_start)
        self.start_btn.grid(row=0, column=0)
        self.stop_btn = ttk.Button(btn_row, text="Stop", command=self.on_stop,
                                   state="disabled")
        self.stop_btn.grid(row=0, column=1, padx=(8, 0))

        # Progress bar + label tahap.
        self.bar = ttk.Progressbar(main, mode="determinate", maximum=100)
        self.bar.grid(row=8, column=0, sticky="ew", **pad)
        self.stage_label = ttk.Label(main, text="Siap.", anchor="w")
        self.stage_label.grid(row=9, column=0, sticky="ew", padx=10)

        # Area teks hidup (cuplikan terbaru saat transkripsi jalan).
        text_frame = ttk.Frame(main)
        text_frame.grid(row=10, column=0, sticky="nsew", **pad)
        main.rowconfigure(10, weight=1)
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)
        self.text = tk.Text(text_frame, height=10, wrap="word", state="disabled")
        self.text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(text_frame, command=self.text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.text.config(yscrollcommand=scroll.set)

        # Baris hasil: path + buka file/folder (muncul saat selesai).
        self.result_row = ttk.Frame(main)
        self.result_row.grid(row=11, column=0, sticky="ew", **pad)
        self.result_row.columnconfigure(0, weight=1)
        self.result_label = ttk.Label(self.result_row, text="", anchor="w",
                                      wraplength=380)
        self.result_label.grid(row=0, column=0, sticky="ew")
        self.open_file_btn = ttk.Button(self.result_row, text="Buka file",
                                        command=self.on_open_file)
        self.open_folder_btn = ttk.Button(self.result_row, text="Buka folder",
                                          command=self.on_open_folder)
        # Tombol hasil disembunyikan sampai ada output.
        self._hide_result_buttons()

        # Kondisi awal: Offline -> sembunyikan baris cloud.
        self._on_backend_changed()

    def _build_keys_tab(self, parent):
        """Tab manajemen API key. Semua provider ditampilkan sbg baris; user
        bisa set/ganti/hapus per baris. Key tak pernah ditampilkan setelah
        disimpan — hanya masked ●●●●●● + 4 karakter terakhir untuk konfirmasi
        visual bahwa slot terisi."""
        pad = {"padx": 10, "pady": 6}
        main = ttk.Frame(parent, padding=12)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)

        # Peringatan availability keystore. Sengaja pakai Text (bisa di-copy)
        # supaya user bisa paste command install-nya langsung ke terminal.
        # Sertakan `sys.executable` supaya user tahu venv MANA yang butuh dep —
        # bug klasik: pip install jalan di Python sistem, bukan di venv proyek.
        if not keystore.available():
            import sys as _sys
            warn = _make_selectable(
                main, foreground="red",
                text=("Windows Credential Manager / library `keyring` belum "
                      "tersedia. Pasang di VENV proyek (bukan Python sistem):\n\n"
                      f'    "{_sys.executable}" -m pip install -r requirements-cloud.txt\n\n'
                      "Setelah selesai, restart PolyScribe."))
            warn.grid(row=0, column=0, sticky="ew", **pad)
            return

        # Info di atas — bisa di-copy (mis. user mau menyalin instruksi ke doc).
        header = _make_selectable(
            main, foreground="gray30",
            text=("Simpan API key untuk backend cloud. Setelah disimpan, key "
                  "TIDAK bisa dilihat lagi — hanya bisa Diganti atau Dihapus. "
                  "Penyimpanan di-encrypt oleh Windows Credential Manager.\n"
                  "Backend cloud opsional; jalur default PolyScribe tetap offline."))
        header.grid(row=0, column=0, sticky="ew", **pad)

        # Tabel provider — satu baris per provider, di-scroll kalau perlu.
        table_frame = ttk.Frame(main)
        table_frame.grid(row=1, column=0, sticky="nsew", **pad)
        main.rowconfigure(1, weight=1)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        canvas = tk.Canvas(table_frame, highlightthickness=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        vs = ttk.Scrollbar(table_frame, orient="vertical", command=canvas.yview)
        vs.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=vs.set)

        rows_frame = ttk.Frame(canvas)
        rows_id = canvas.create_window((0, 0), window=rows_frame, anchor="nw")

        def _resize_rows(_e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(rows_id, width=canvas.winfo_width())
        rows_frame.bind("<Configure>", _resize_rows)
        canvas.bind("<Configure>", _resize_rows)

        # Simpan referensi ke widget status per provider supaya bisa di-refresh.
        self._key_status_widgets: dict[str, ttk.Label] = {}
        for i, info in enumerate(list_providers()):
            self._build_key_row(rows_frame, i, info)

        self._refresh_key_statuses()

    def _build_key_row(self, parent, row: int, info):
        """Satu baris provider dibangun sebagai 3 SUB-BARIS supaya tombol
        Set/Ganti selalu kelihatan tak peduli lebar text di atasnya.

        Layout:
            baris 0: judul provider (full-width, spans semua kolom aksi)
            baris 1: status masked | [Set/Ganti] [Hapus] [Region/Project…]
            baris 2: catatan tradeoff (full-width)

        Bug lama (2026-09-21): title & buttons di ROW yang sama; tk.Text default
        width=80 karakter mendorong tombol keluar viewport -> user tak lihat
        tombol & bertanya 'di mana saya set API key?'. Sekarang tombol punya
        baris sendiri di dekat kiri, tak bisa hilang.
        """
        frame = ttk.Frame(parent, padding=(0, 4), relief="solid", borderwidth=1)
        frame.grid(row=row, column=0, sticky="ew", pady=(4, 4))
        frame.columnconfigure(4, weight=1)   # kolom terakhir menyerap sisa lebar

        # === baris 0: judul provider (full width) ===
        price = f"±${info.price_hint_per_hour_usd:.2f}/jam" if info.price_hint_per_hour_usd > 0 else "gratis"
        title = _make_selectable(
            frame,
            text=f"{info.display_name}\n"
                 f"  {price} · {info.languages} · {_limit_summary(info)}",
            font=("Segoe UI", 9, "bold"),
            width=72)
        title.grid(row=0, column=0, columnspan=5, sticky="w", padx=(6, 6), pady=(4, 2))

        # === baris 1: status + tombol aksi ===
        # Provider yg TAK butuh API key (mis. Google Web Speech): jangan
        # tampilkan status "Belum diset" — user membaca kata "belum" sbg
        # "harus set nanti", padahal memang tak akan pernah perlu di-set.
        # Tampilkan satu label datar "Siap dipakai (tak perlu API key)"
        # supaya niat provider ini jelas & tak ada tombol Set yang menggoda.
        if info.needs_key:
            status_var = tk.StringVar(value="—")
            status_entry = ttk.Entry(frame, textvariable=status_var, width=26,
                                     state="readonly", foreground="gray30")
            status_entry.grid(row=1, column=0, sticky="w", padx=(12, 8), pady=(0, 4))
            self._key_status_widgets[info.key] = (status_var, status_entry)

            col = 1
            btn_set = ttk.Button(frame, text="Set / Ganti",
                                 command=lambda k=info.key, dn=info.display_name:
                                     self._prompt_set_key(k, dn))
            btn_set.grid(row=1, column=col, padx=(0, 4), pady=(0, 4))
            col += 1
            btn_del = ttk.Button(frame, text="Hapus",
                                 command=lambda k=info.key: self._delete_key(k))
            btn_del.grid(row=1, column=col, padx=(0, 4), pady=(0, 4))
            col += 1
            # Provider spesial yg butuh field ekstra (region / project).
            if info.key == "azure_speech":
                btn_region = ttk.Button(
                    frame, text="Region…",
                    command=lambda: self._prompt_set_key(
                        "azure_speech_region",
                        "Azure region (mis. 'eastus')", is_secret=False))
                btn_region.grid(row=1, column=col, padx=(0, 4), pady=(0, 4))
                col += 1
            elif info.key == "google_cloud":
                btn_proj = ttk.Button(
                    frame, text="Project ID…",
                    command=lambda: self._prompt_set_key(
                        "google_cloud_project",
                        "Google Cloud Project ID", is_secret=False))
                btn_proj.grid(row=1, column=col, padx=(0, 4), pady=(0, 4))
                col += 1
        else:
            # Provider tanpa key — satu label ramah menyatakan siap dipakai.
            ttk.Label(frame,
                      text="Siap dipakai — tak perlu API key",
                      foreground="dark green"
                      ).grid(row=1, column=0, columnspan=5, sticky="w",
                             padx=(12, 6), pady=(0, 4))

        # === baris 2: catatan tradeoff (full width) ===
        note = _make_selectable(
            frame,
            text=info.notes + "\n> " + info.recommendation,
            font=("Segoe UI", 8), foreground="gray45",
            width=72)
        note.grid(row=2, column=0, columnspan=5, sticky="ew",
                  padx=(12, 6), pady=(0, 6))

    def _prompt_set_key(self, provider_key: str, display_name: str,
                        is_secret: bool = True):
        """Dialog modal input key. Field password (show='*') untuk yg is_secret.
        Kalau user simpan, key masuk keystore & label tabel di-refresh.
        Penting: setelah simpan, dialog ditutup — TAK ADA cara membaca kembali."""
        dlg = tk.Toplevel(self.root)
        dlg.title(f"Set: {display_name}")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.resizable(False, False)

        frm = ttk.Frame(dlg, padding=16)
        frm.pack(fill="both", expand=True)

        info_txt = ("Ketik key, lalu Simpan. Setelah tersimpan, isi TIDAK bisa "
                    "dilihat kembali — hanya Diganti atau Dihapus.") if is_secret \
                   else "Ketik nilainya, lalu Simpan."
        ttk.Label(frm, text=info_txt, wraplength=380, justify="left",
                  foreground="gray30").pack(anchor="w", pady=(0, 8))

        entry_var = tk.StringVar()
        entry = ttk.Entry(frm, textvariable=entry_var, width=48,
                          show="*" if is_secret else "")
        entry.pack(fill="x", pady=(0, 8))
        entry.focus_set()

        btn_row = ttk.Frame(frm)
        btn_row.pack(fill="x")

        def _save():
            val = entry_var.get().strip()
            if not val:
                messagebox.showwarning("Kosong", "Key tak boleh kosong.",
                                       parent=dlg)
                return
            try:
                keystore.set_key(provider_key, val)
            except Exception as e:
                messagebox.showerror("Gagal menyimpan", str(e), parent=dlg)
                return
            # Bersihkan variabel supaya tak nyangkut di memori GC nanti.
            entry_var.set("")
            dlg.destroy()
            self._refresh_key_statuses()

        ttk.Button(btn_row, text="Simpan", command=_save).pack(side="right")
        ttk.Button(btn_row, text="Batal",
                   command=dlg.destroy).pack(side="right", padx=(0, 8))

        dlg.bind("<Return>", lambda _e: _save())
        dlg.bind("<Escape>", lambda _e: dlg.destroy())

    def _delete_key(self, provider_key: str):
        if not messagebox.askyesno(
                "Hapus key?",
                f"Yakin hapus API key untuk '{provider_key}'?"):
            return
        keystore.delete_key(provider_key)
        # Untuk provider yg punya field ekstra (region/project), tinggalkan —
        # user hapus sendiri kalau perlu. Ini menghindari kejutan.
        self._refresh_key_statuses()

    def _refresh_key_statuses(self):
        """Update status masked tiap baris berdasarkan isi keystore. Tak menyentuh
        isi key — hanya menampilkan masked-string yg user boleh di-copy."""
        for provider_key, (var, entry) in self._key_status_widgets.items():
            st = keystore.status(provider_key)
            if st.has_key:
                var.set(f"Tersimpan: {st.masked}")
                # Entry readonly foreground perlu di-set via state readonly-nya.
                entry.configure(foreground="dark green")
            else:
                var.set("Belum diset")
                entry.configure(foreground="gray50")

    def _on_backend_changed(self):
        """Toggle visibility baris cloud."""
        is_cloud = self.backend_var.get() == BACKEND_CLOUD
        if is_cloud:
            self.cloud_row.grid()
            # Auto-pilih provider pertama kalau belum ada pilihan.
            if not self.cloud_var.get():
                self.cloud_var.set(list_providers()[0].display_name)
            self._update_cloud_hint()
        else:
            self.cloud_row.grid_remove()
            self.cloud_hint.config(text="")

    def _update_cloud_hint(self):
        """Info per provider: harga, kapabilitas, batas ukuran, rekomendasi.
        Termasuk peringatan eksplisit kalau provider tak lengkap kapabilitasnya
        (mis. Google Web) atau punya batas keras berat (mis. Google Cloud 60 dtk)."""
        display = self.cloud_var.get()
        key = self._cloud_display_to_key.get(display)
        if not key:
            self.cloud_hint.config(text="")
            return
        info = get_provider_info(key)
        if not info:
            self.cloud_hint.config(text="")
            return
        parts = []
        if info.price_hint_per_hour_usd > 0:
            parts.append(f"±${info.price_hint_per_hour_usd:.2f}/jam")
        else:
            parts.append("gratis")
        parts.append(info.languages)
        # Batas ukuran/durasi (2026-09-21).
        parts.append(_limit_summary(info))
        if not info.has_timestamps:
            parts.append("⚠ tanpa timestamp (akan diperkirakan linear)")
        if info.needs_key and not keystore.has_key(info.key):
            parts.append("⚠ API key BELUM di-set — buka tab 'Backend & API Keys'")
        header = " · ".join(parts)
        self.cloud_hint.config(
            text=f"{header}\n{info.notes}\n> {info.recommendation}")

    # --- Aksi tombol --------------------------------------------------------
    def on_pick(self):
        path = filedialog.askopenfilename(
            title="Pilih file audio",
            filetypes=[("Audio", "*.wav *.mp3 *.m4a *.flac *.ogg"),
                       ("Semua file", "*.*")],
        )
        if path:
            self.audio_path = path
            self.file_label.config(text=os.path.basename(path))

    def on_start(self):
        if not self.audio_path:
            messagebox.showwarning("Belum ada file",
                                   "Pilih file audio dulu sebelum mulai.")
            return

        # Validasi cloud config sebelum jalan — supaya user tak lihat error
        # baru muncul 30 detik setelah "Mulai" ditekan.
        if self.backend_var.get() == BACKEND_CLOUD:
            display = self.cloud_var.get()
            key = self._cloud_display_to_key.get(display)
            if not key:
                messagebox.showwarning("Provider belum dipilih",
                                       "Pilih provider cloud dulu.")
                return
            info = get_provider_info(key)
            if info.needs_key and not keystore.has_key(key):
                messagebox.showwarning(
                    "API key belum diset",
                    f"'{info.display_name}' butuh API key. Buka tab "
                    "'Backend & API Keys' untuk memasangnya.")
                return
            # Validasi ukuran/durasi terhadap batas provider (2026-09-21).
            # Gagal cepat sebelum decoder/pipeline mulai — kesalahan config
            # user (mis. Google Cloud dgn file 30 mnt) muncul instan, bukan
            # setelah 30 detik "Memuat model".
            from .asr.cloud import validate_audio
            verdict = validate_audio(key, self.audio_path)
            if not verdict.ok:
                messagebox.showerror("File tak sesuai batas provider",
                                     verdict.error)
                return
            if verdict.warning:
                # Peringatan boleh dilewati — user konfirmasi.
                cont = messagebox.askyesno(
                    "Peringatan",
                    verdict.warning + "\n\nLanjutkan?",
                    icon="warning")
                if not cont:
                    return

        # Kunci input selama proses; siapkan kanal pekerja.
        self._set_running(True)
        self._clear_text()
        self._hide_result_buttons()
        self.result_label.config(text="")
        self.result_path = None

        cfg = self._build_config()

        # Fallback aman (brief 37): kalau user memilih Akurat tapi model/paket
        # pyannote belum terpasang, JANGAN crash. Beri tahu ramah lalu jatuh ke
        # mode Cepat (sherpa) untuk run ini. Selector juga defensif, tapi menukar
        # di sini membuat pesan muncul di UI & bar status jujur soal mode terpakai.
        if cfg.diarizer_choice == "pyannote":
            ready, reason = pyannote_availability(cfg)
            if not ready:
                cfg.diarizer_choice = "sherpa"
                messagebox.showinfo(
                    "Beralih ke mode Cepat",
                    f"{reason}\n\nUntuk sekarang memakai mode Cepat (sherpa).")
                self.stage_label.config(text="Model Akurat tak ada — memakai mode Cepat.")

        # Antrean & event antar-PROSES (bukan thread). Proses anak menjalankan
        # pipeline penuh; GIL-nya sendiri -> diarization tak membekukan UI ini.
        self.queue = mp.Queue()
        self.cancel_event = mp.Event()

        self.worker = mp.Process(
            target=run_pipeline_to_queue,
            args=(self.audio_path, cfg, self.queue, self.cancel_event),
            daemon=True,
        )
        self.worker.start()
        self.root.after(100, self._poll_queue)

    def on_stop(self):
        # Batal kooperatif: set event, pekerja berhenti rapi sendiri (transkrip
        # parsial di-commit di dalam pipeline). Proses di-join saat selesai.
        # Instrumentasi: log ke %TEMP%\polyscribe_cancel.log SEBELUM set — bila
        # nanti Result cancelled=True tanpa entri "gui_stop" di log, kita tahu
        # cancel_event ter-set dari luar GUI Stop (bug misterius user 2026-08).
        log_cancel_event(source="gui_stop", detail="user pressed Stop button")
        if self.cancel_event is not None:
            self.cancel_event.set()
        self.stop_btn.config(state="disabled")
        self.stage_label.config(text="Menghentikan…")

    def on_open_file(self):
        self._open_path(self.result_path)

    def on_open_folder(self):
        if self.result_path:
            self._open_path(os.path.dirname(self.result_path))

    # --- Loop antrean (thread utama) ---------------------------------------
    def _poll_queue(self):
        """Kuras antrean & update widget. Dijadwalkan ulang tiap 100 ms."""
        finished = False
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "progress":
                    self._on_progress(payload)
                elif kind == "done":
                    self._on_done(payload)
                    finished = True
                elif kind == "error":
                    self._on_error(payload)
                    finished = True
        except queue.Empty:
            pass

        # Jaring pengaman: proses anak mati tanpa menaruh done/error (mis. crash
        # native). Jangan menggantung selamanya — laporkan sebagai gagal.
        if (not finished and self.worker is not None
                and not self.worker.is_alive() and self.queue.empty()):
            self._on_error(RuntimeError(
                "Proses pemrosesan berhenti tak terduga (kemungkinan crash native)."))
            finished = True

        if finished:
            if self.worker is not None:
                self.worker.join(timeout=1.0)
                self.worker = None
        else:
            self.root.after(100, self._poll_queue)

    def _on_progress(self, event: ProgressEvent):
        label = STAGE_LABEL.get(event.stage, event.stage)
        if event.stage in DETERMINATE_STAGES:
            # diarize & transcribe mengirim fraction sungguhan -> bar bergerak nyata.
            self._set_bar_determinate()
            self.bar["value"] = event.fraction * 100
            pct = int(event.fraction * 100)
            # Label diarize panjang; sisipkan persen tanpa membuangnya.
            self.stage_label.config(text=f"{label} ({pct}%)" if event.stage == "diarize"
                                    else f"{label} {pct}%")
        elif event.stage in PULSING_STAGES:
            self._set_bar_pulsing()
            # Pakai event.message sebagai sub-label bila ada (mis. "mendekode audio",
            # "memuat ASR") -> user tahu langkah mana yang berjalan, bukan cuma
            # "Memuat model" bisu. Tanpa message: fallback ke label saja.
            if event.message:
                self.stage_label.config(text=f"{label} — {event.message}…")
            else:
                self.stage_label.config(text=f"{label}…")
        # Cuplikan teks terbaru -> area hidup.
        if event.text_snippet.strip():
            self._append_text(event.text_snippet.strip())

    def _on_done(self, res):
        self._set_bar_determinate()
        self.bar["value"] = 100
        self._set_running(False)
        self.result_path = res.txt_path
        if res.cancelled:
            self.stage_label.config(text="Dihentikan — transkrip parsial disimpan.")
            self.result_label.config(text=f"Parsial: {res.txt_path}")
        elif getattr(res, "loop_detected", False):
            # User HARUS tahu hasilnya mungkin rusak — jangan gagal senyap.
            n = len(res.speakers)
            self.stage_label.config(text="Selesai DENGAN PERINGATAN loop ASR.")
            self.result_label.config(
                text=f"Selesai ({n} pembicara), TAPI ada dugaan loop: {res.txt_path}")
            stamps = ", ".join(f"{int(t)//60:02d}:{int(t)%60:02d}"
                               for t in (res.loop_times or []))
            messagebox.showwarning(
                "Kemungkinan loop ASR",
                "Terdeteksi kemungkinan loop/halusinasi pada transkripsi di sekitar: "
                f"{stamps}.\n\nBagian bertanda '=== PERINGATAN' di dalam .txt mungkin "
                "rusak/berulang. Silakan periksa bagian tersebut.")
        else:
            n = len(res.speakers)
            self.stage_label.config(text="Selesai.")
            self.result_label.config(
                text=f"Selesai ({n} pembicara): {res.txt_path}")
        self._show_result_buttons()

    def _on_error(self, exc):
        self._set_bar_determinate()
        self.bar["value"] = 0
        self._set_running(False)
        self.stage_label.config(text="Gagal.")
        messagebox.showerror("Gagal memproses", _friendly_error(exc))

    # --- Util UI ------------------------------------------------------------
    def _build_config(self) -> Config:
        cfg = Config()
        cfg.allow_vulkan = bool(self.gpu_var.get())
        # Backend cloud vs offline (2026-09-21).
        if self.backend_var.get() == BACKEND_CLOUD:
            cfg.asr_backend = "cloud"
            key = self._cloud_display_to_key.get(self.cloud_var.get(), "")
            cfg.cloud_provider = key
        # Peta eksplisit (brief 47): tiap label dropdown -> kode bahasa. Fallback "en"
        # cuma jaring; karena dropdown diisi dari LANG_LABEL_TO_CODE, tiap label pasti
        # ada entrinya -> jaring tak pernah kepakai.
        cfg.primary_language = LANG_LABEL_TO_CODE.get(self.lang_var.get(), "en")
        cfg.diarizer_choice = MODE_TO_CHOICE.get(self.mode_var.get(), "pyannote")
        return cfg

    def _update_mode_hint(self):
        self.mode_hint.config(text=MODE_HINT.get(self.mode_var.get(), ""))

    def _set_running(self, running: bool):
        state = "disabled" if running else "normal"
        self.pick_btn.config(state=state)
        self.start_btn.config(state=state)
        self.gpu_check.config(state=state)
        self.lang_combo.config(state="disabled" if running else "readonly")
        self.mode_combo.config(state="disabled" if running else "readonly")
        self.backend_combo.config(state="disabled" if running else "readonly")
        self.cloud_combo.config(state="disabled" if running else "readonly")
        self.stop_btn.config(state="normal" if running else "disabled")
        if not running:
            self._set_bar_determinate()   # hentikan denyut kalau masih jalan

    def _set_bar_pulsing(self):
        if self._bar_mode != "indeterminate":
            self.bar.config(mode="indeterminate")
            self.bar.start(12)
            self._bar_mode = "indeterminate"

    def _set_bar_determinate(self):
        if self._bar_mode != "determinate":
            self.bar.stop()
            self.bar.config(mode="determinate")
            self._bar_mode = "determinate"

    def _append_text(self, snippet: str):
        self.text.config(state="normal")
        self.text.insert("end", snippet + "\n")
        self.text.see("end")
        self.text.config(state="disabled")

    def _clear_text(self):
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.config(state="disabled")

    def _show_result_buttons(self):
        self.open_file_btn.grid(row=0, column=1, padx=(8, 0))
        self.open_folder_btn.grid(row=0, column=2, padx=(8, 0))

    def _hide_result_buttons(self):
        self.open_file_btn.grid_remove()
        self.open_folder_btn.grid_remove()

    def _open_path(self, path: str | None):
        if not path or not os.path.exists(path):
            messagebox.showwarning("Tidak ditemukan",
                                   "File/folder tidak ditemukan.")
            return
        try:
            os.startfile(path)   # Windows: buka dengan aplikasi default
        except OSError as e:
            messagebox.showerror("Gagal membuka", str(e))


def _make_selectable(parent, text: str, *, font=None, foreground=None,
                     width: int = 72) -> tk.Text:
    """Widget mirip ttk.Label TAPI isinya bisa dipilih & di-copy (Ctrl+C).

    Kenapa ada: ttk.Label sengaja tak selectable oleh Tk (dianggap read-only
    dekorasi). Untuk tab 'Backend & API Keys', user butuh menyalin catatan
    provider / masked-status / instruksi ke dokumen lain — jadi kita pakai
    tk.Text state=disabled: seleksi mouse tetap jalan, Ctrl+C jalan, tapi
    tak bisa diketik. Tampilannya di-flat + background frame supaya menyatu.

    `width` = LEBAR dalam karakter. WAJIB di-set eksplisit — default tk.Text
    adalah 80 karakter yang akan mendorong widget sebelahnya keluar layar
    (bug tab Keys 2026-09-21 di mana tombol Set/Ganti tak kelihatan karena
    title width default 80 char). Tinggi dihitung dari word-wrap pada `width`.
    """
    import textwrap
    # Ambil warna background frame supaya widget tak nampak seperti kotak input.
    try:
        style = ttk.Style()
        bg = style.lookup("TFrame", "background") or parent.cget("background")
    except tk.TclError:
        bg = "SystemButtonFace"

    # Font WAJIB proporsional — kalau tak di-set, tk.Text default ke TkFixedFont
    # (Courier-like monospace di Windows) → tampak sangat berbeda dari ttk.Label
    # yang pakai TkDefaultFont (Segoe UI). Bug pertama tab Keys 2026-09-21:
    # header teks kelihatan seperti terminal Courier di tengah GUI Segoe UI.
    if font is None:
        font = ("Segoe UI", 9)

    # Perkirakan jumlah baris display setelah word-wrap. Lebih baik overshoot
    # sedikit (baris kosong di bawah) daripada undershoot (teks terpotong).
    lines = 0
    for raw in text.split("\n"):
        lines += max(1, len(textwrap.wrap(raw, width=width)))

    kwargs = {"font": font}
    if foreground is not None:
        kwargs["foreground"] = foreground

    widget = tk.Text(parent, wrap="word", relief="flat", borderwidth=0,
                     highlightthickness=0, background=bg, height=lines,
                     width=width, cursor="arrow", **kwargs)
    widget.insert("1.0", text)
    widget.configure(state="disabled")
    return widget


def _limit_summary(info) -> str:
    """String ringkas batas ukuran/durasi untuk header hint provider. Kalau
    adapter auto-chunk, sebut "auto-chunk"; kalau tidak, sebut batas keras."""
    if info.auto_chunks:
        return "auto-chunk (tak ada batas total)"
    parts = []
    if info.max_duration_s > 0:
        if info.max_duration_s < 60:
            parts.append(f"max {info.max_duration_s:.0f} dtk")
        elif info.max_duration_s < 3600:
            parts.append(f"max {info.max_duration_s / 60:.0f} mnt")
        else:
            parts.append(f"max {info.max_duration_s / 3600:.0f} jam")
    if info.max_size_mb > 0:
        if info.max_size_mb >= 1024:
            parts.append(f"{info.max_size_mb / 1024:.1f} GB")
        else:
            parts.append(f"{info.max_size_mb:.0f} MB")
    return "batas " + " / ".join(parts) if parts else "tanpa batas ketat"


def _friendly_error(exc: Exception) -> str:
    """Ubah exception jadi pesan yang bisa dibaca user non-teknis."""
    if isinstance(exc, FileNotFoundError):
        # Backend melempar pesan yang sudah jelas (model/binary hilang, dst).
        return str(exc)
    return f"Terjadi kesalahan saat memproses:\n\n{exc}"


def main():
    root = tk.Tk()
    PolyScribeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

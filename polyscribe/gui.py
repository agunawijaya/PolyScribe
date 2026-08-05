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
"""

import multiprocessing as mp
import os
import queue
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

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


# Nama tahap pipeline -> teks ramah untuk label status.
STAGE_LABEL = {
    "load": "Memuat model…",
    # File panjang: diarization bisa beberapa menit. Beri tahu user JANGAN tutup
    # jendela (FINDING-2) — sekarang UI tak lagi beku karena diarization jalan di
    # proses terpisah, tapi label yang jujur mencegah panik/force-quit.
    "diarize": "Menganalisis pembicara — bisa beberapa menit di file panjang. "
               "Jangan tutup jendela…",
    "transcribe": "Mentranskripsi…",
    "merge": "Merapikan…",
    "done": "Selesai",
}

# Tahap yang tak punya granularitas per-detik -> bar berdenyut (indeterminate).
# 'diarize' TIDAK di sini: sherpa mengirim fraction (num_done/num_total), jadi kita
# tampilkan bar determinate yang benar-benar bergerak (FINDING-2 fallback (a)).
PULSING_STAGES = ("load", "merge")
# Tahap dengan fraction sungguhan -> bar determinate mengikuti event.fraction.
DETERMINATE_STAGES = ("diarize", "transcribe")


class PolyScribeApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("PolyScribe — Transkripsi Rapat")
        root.minsize(560, 460)

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
        pad = {"padx": 10, "pady": 6}
        main = ttk.Frame(self.root, padding=12)
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

        # Baris pengaturan minimal: GPU + bahasa.
        opt_row = ttk.Frame(main)
        opt_row.grid(row=1, column=0, sticky="ew", **pad)
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
        mode_row.grid(row=2, column=0, sticky="ew", **pad)
        ttk.Label(mode_row, text="Mode pembicara:").grid(row=0, column=0, padx=(0, 4))
        self.mode_var = tk.StringVar(value=MODE_ACCURATE)
        self.mode_combo = ttk.Combobox(
            mode_row, textvariable=self.mode_var, state="readonly", width=34,
            values=[MODE_ACCURATE, MODE_FAST])
        self.mode_combo.grid(row=0, column=1, sticky="w")
        self.mode_combo.bind("<<ComboboxSelected>>", lambda _e: self._update_mode_hint())
        # Catatan kecil di bawah dropdown: keterangan mode + peringatan waktu jujur.
        self.mode_hint = ttk.Label(main, text="", anchor="w", foreground="gray40",
                                   wraplength=520)
        self.mode_hint.grid(row=3, column=0, sticky="ew", padx=10)
        self._update_mode_hint()

        # Baris tombol Mulai / Stop.
        btn_row = ttk.Frame(main)
        btn_row.grid(row=4, column=0, sticky="ew", **pad)
        self.start_btn = ttk.Button(btn_row, text="Mulai", command=self.on_start)
        self.start_btn.grid(row=0, column=0)
        self.stop_btn = ttk.Button(btn_row, text="Stop", command=self.on_stop,
                                   state="disabled")
        self.stop_btn.grid(row=0, column=1, padx=(8, 0))

        # Progress bar + label tahap.
        self.bar = ttk.Progressbar(main, mode="determinate", maximum=100)
        self.bar.grid(row=5, column=0, sticky="ew", **pad)
        self.stage_label = ttk.Label(main, text="Siap.", anchor="w")
        self.stage_label.grid(row=6, column=0, sticky="ew", padx=10)

        # Area teks hidup (cuplikan terbaru saat transkripsi jalan).
        text_frame = ttk.Frame(main)
        text_frame.grid(row=7, column=0, sticky="nsew", **pad)
        main.rowconfigure(7, weight=1)
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)
        self.text = tk.Text(text_frame, height=10, wrap="word", state="disabled")
        self.text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(text_frame, command=self.text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.text.config(yscrollcommand=scroll.set)

        # Baris hasil: path + buka file/folder (muncul saat selesai).
        self.result_row = ttk.Frame(main)
        self.result_row.grid(row=8, column=0, sticky="ew", **pad)
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
            self.stage_label.config(text=label)
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

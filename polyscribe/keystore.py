"""Penyimpanan aman API key untuk backend cloud.

Kontrak dgn user (keputusan 2026-09-21): user mengetik key SEKALI di GUI,
setelah itu key tak pernah ditampilkan lagi — hanya bisa Ganti atau Hapus.
Penyimpanan di-encrypt oleh OS, bukan file plain di %APPDATA%.

Implementasi: library `keyring` -> Windows Credential Manager (per-user vault
yang dienkripsi dgn DPAPI di bawahnya, tapi lewat API resmi Windows yang lebih
diaudit dari sekadar CryptProtectData mentah). Portabel: sama cara jalan di
Mac (Keychain) & Linux (Secret Service) — meski PolyScribe target Windows saja,
tak ada alasan mengunci diri di API vendor.

Kalau `keyring` tak terpasang -> fitur cloud mati DIAM. `available()` mengembalikan
False, backend cloud tak muncul di UI. Ini SENGAJA: user yang tak butuh cloud
tak perlu install dep tambahan; user yang butuh cloud akan diarahkan lewat pesan
GUI ke `pip install -r requirements-cloud.txt`.
"""

from dataclasses import dataclass
from typing import Optional


# Namespace di Credential Manager. Satu "service" per PolyScribe supaya lain aplikasi
# yg juga pakai keyring tak bertabrakan dgn kita. Nama key = username field.
SERVICE_NAME = "PolyScribe-cloud"


@dataclass
class KeyStatus:
    """Status ringkas untuk ditampilkan di GUI — TAK memuat isi key.

    `has_key` True = ada key tersimpan di vault (tapi kita tak akan menunjukkannya).
    `masked` = string ●●●●●● + prefix pendek untuk konfirmasi visual bahwa key ada.
    """
    provider: str
    has_key: bool
    masked: str = ""


def available() -> bool:
    """True kalau vault OS bisa dipakai. Dipanggil GUI sebelum memasang tab cloud."""
    try:
        import keyring
        # keyring bisa "terpasang" tapi backend-nya `fail.Keyring` di lingkungan
        # tanpa Credential Manager (mis. proses non-interaktif). Cek explicit.
        backend = keyring.get_keyring()
        return "fail" not in type(backend).__name__.lower()
    except Exception:
        return False


def set_key(provider: str, key: str) -> None:
    """Simpan/timpa key untuk sebuah provider. Melempar RuntimeError kalau vault
    tak tersedia — GUI menangkap dan menampilkan pesan ramah.

    Key TAK divalidasi di sini (tak tahu formatnya per provider); adapter yg akan
    mencobanya saat run. Whitespace di ujung dipangkas — user sering paste dgn
    trailing space/newline yg lalu jadi bug 401 misterius.
    """
    key = (key or "").strip()
    if not key:
        raise ValueError("Key kosong.")
    if not available():
        raise RuntimeError(
            "Windows Credential Manager tak dapat diakses. Pastikan `keyring` "
            "terpasang: pip install -r requirements-cloud.txt"
        )
    import keyring
    keyring.set_password(SERVICE_NAME, provider, key)


def get_key(provider: str) -> Optional[str]:
    """Kembalikan key mentah untuk pemakaian internal (dipanggil adapter cloud
    saat run). JANGAN tampilkan hasilnya ke UI atau tulis ke log."""
    if not available():
        return None
    import keyring
    try:
        return keyring.get_password(SERVICE_NAME, provider)
    except Exception:
        # Vault error di runtime (mis. akun locked). Perlakukan seperti tak ada
        # key — adapter akan gagal dgn pesan "key tak ditemukan" yg jelas.
        return None


def delete_key(provider: str) -> None:
    """Hapus key. Idempotent — tak melempar kalau key memang tak ada."""
    if not available():
        return
    import keyring
    import keyring.errors
    try:
        keyring.delete_password(SERVICE_NAME, provider)
    except keyring.errors.PasswordDeleteError:
        pass


def has_key(provider: str) -> bool:
    """Cek keberadaan tanpa membaca isi. Dipanggil GUI untuk state tombol."""
    return get_key(provider) is not None


def status(provider: str) -> KeyStatus:
    """Status siap-tampil untuk GUI. `masked` menampilkan ●●●●●● + 4 karakter
    terakhir key sbg konfirmasi visual — tidak cukup untuk merekonstruksi key
    (4 char dari string 30-64 char). Kalau paranoid, ubah tail=0."""
    key = get_key(provider)
    if not key:
        return KeyStatus(provider=provider, has_key=False, masked="")
    tail = key[-4:] if len(key) >= 8 else ""
    return KeyStatus(provider=provider, has_key=True, masked=f"●●●●●●{tail}")


__all__ = [
    "SERVICE_NAME", "KeyStatus", "available",
    "set_key", "get_key", "delete_key", "has_key", "status",
]

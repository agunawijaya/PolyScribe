"""Uji polyscribe.keystore — mock modul `keyring` supaya tes tak menyentuh
Windows Credential Manager beneran (yang bisa gagal di CI / lingkungan headless).

Kontrak yang dipastikan:
- available() False bila keyring tak terpasang / backend "fail"; True lainnya.
- set_key() melempar ValueError untuk key kosong; RuntimeError bila keystore mati.
- get_key()/has_key() mengembalikan hasil sesuai vault.
- delete_key() idempotent (tak melempar bila key tak ada).
- status() mengembalikan masked-string yang TIDAK memuat isi key penuh
  (kontrak "write-once, never seen again" dari user 2026-09-21).
"""

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _install_fake_keyring():
    """Pasang modul keyring palsu di sys.modules sebelum polyscribe.keystore
    di-import. Vault = dict Python. Mengembalikan (fake_module, vault_dict)."""
    fake = types.ModuleType("keyring")
    fake_errors = types.ModuleType("keyring.errors")

    class PasswordDeleteError(Exception):
        pass
    fake_errors.PasswordDeleteError = PasswordDeleteError

    class FakeBackend:
        pass
    _backend = FakeBackend()

    vault: dict[tuple[str, str], str] = {}

    def set_password(service, user, password):
        vault[(service, user)] = password

    def get_password(service, user):
        return vault.get((service, user))

    def delete_password(service, user):
        if (service, user) not in vault:
            raise PasswordDeleteError(f"no password for {user}")
        del vault[(service, user)]

    def get_keyring():
        return _backend

    fake.set_password = set_password
    fake.get_password = get_password
    fake.delete_password = delete_password
    fake.get_keyring = get_keyring
    fake.errors = fake_errors

    sys.modules["keyring"] = fake
    sys.modules["keyring.errors"] = fake_errors
    return fake, vault


def _fresh_keystore():
    """Reload polyscribe.keystore setelah keyring palsu terpasang, supaya import
    di dalamnya menangkap yg palsu — bukan modul asli dari test sebelumnya."""
    _install_fake_keyring()
    if "polyscribe.keystore" in sys.modules:
        del sys.modules["polyscribe.keystore"]
    from polyscribe import keystore
    return keystore


def test_available_true_with_fake_backend():
    ks = _fresh_keystore()
    assert ks.available() is True


def test_set_and_get_roundtrip():
    ks = _fresh_keystore()
    ks.set_key("groq", "gsk-abcdef12345678")
    assert ks.get_key("groq") == "gsk-abcdef12345678"
    assert ks.has_key("groq") is True


def test_set_empty_key_rejected():
    ks = _fresh_keystore()
    try:
        ks.set_key("groq", "")
    except ValueError:
        return
    raise AssertionError("key kosong seharusnya ditolak")


def test_whitespace_trimmed_on_set():
    """Bug user sering: paste key dengan trailing newline -> 401 misterius."""
    ks = _fresh_keystore()
    ks.set_key("groq", "  gsk-xyz  \n")
    assert ks.get_key("groq") == "gsk-xyz"


def test_delete_is_idempotent():
    ks = _fresh_keystore()
    ks.delete_key("never_set")           # tak boleh melempar
    ks.set_key("groq", "gsk-abc123")
    ks.delete_key("groq")
    assert ks.has_key("groq") is False
    ks.delete_key("groq")                 # kedua kalinya juga aman


def test_status_masks_key():
    """Kontrak kunci: setelah simpan, key TIDAK ditampilkan penuh.
    Yang tampil hanya ●●●●●● + 4 karakter terakhir."""
    ks = _fresh_keystore()
    ks.set_key("groq", "gsk-abcdefghij1234")
    st = ks.status("groq")
    assert st.has_key is True
    assert "1234" in st.masked           # 4 char terakhir untuk konfirmasi
    assert "abcdef" not in st.masked     # bagian awal TAK boleh bocor
    assert "gsk-" not in st.masked


def test_status_when_absent():
    ks = _fresh_keystore()
    st = ks.status("never_set")
    assert st.has_key is False
    assert st.masked == ""


if __name__ == "__main__":
    import traceback
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
                passed += 1
            except Exception:
                print(f"FAIL {name}")
                traceback.print_exc()
                failed += 1
    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)

import sys
import types
import traceback

import pytest

from am3d.ai.contracts import ProviderCredentialError
from am3d.ai import credentials
from am3d.ai.credentials import SessionCredentialStore, SystemCredentialStore, _make_approved_backend


class FakeBackend:
    def __init__(self):
        self.values = {}
        self.fail = None

    def get_password(self, service, alias):
        if self.fail:
            raise RuntimeError(self.fail)
        return self.values.get((service, alias))

    def set_password(self, service, alias, secret):
        if self.fail:
            raise RuntimeError(self.fail)
        self.values[(service, alias)] = secret

    def delete_password(self, service, alias):
        if self.fail:
            raise RuntimeError(self.fail)
        key = (service, alias)
        if key not in self.values:
            raise PasswordDeleteError("missing")
        del self.values[key]


class PasswordDeleteError(Exception):
    pass


def test_system_store_saves_rotates_reads_and_deletes_only_through_backend(monkeypatch):
    backend = FakeBackend()
    monkeypatch.setattr(credentials, "_make_approved_backend", lambda _platform: backend)
    store = SystemCredentialStore(platform="win32")
    store.set("default", "old-key")
    assert store.get("default") == "old-key"
    store.set("default", "new-key")
    assert store.get("default") == "new-key"
    store.delete("default")
    assert store.get("default") is None
    store.delete("default")  # Missing item is a no-op.
    assert len(backend.values) == 0


def test_locked_backend_errors_are_fixed_and_do_not_reveal_secret_sentinel(monkeypatch):
    sentinel = "credential-sentinel-6b5e"
    backend = FakeBackend()
    monkeypatch.setattr(credentials, "_make_approved_backend", lambda _platform: backend)
    store = SystemCredentialStore(platform="win32")
    backend.fail = f"locked: {sentinel}"
    with pytest.raises(ProviderCredentialError) as caught:
        store.get("default")
    assert sentinel not in str(caught.value)
    assert sentinel not in repr(caught.value)
    assert sentinel not in "".join(traceback.format_exception(caught.value))
    assert "locked or unavailable" in str(caught.value)


def test_unavailable_os_backend_does_not_fall_back_to_keyring_autodetection():
    with pytest.raises(ProviderCredentialError, match="no approved persistent"):
        SystemCredentialStore(platform="darwin")


def test_windows_selection_constructs_the_explicit_credential_manager_backend(monkeypatch):
    import keyring
    import keyring.backends.Windows as windows

    class ExplicitWindowsBackend:
        pass

    monkeypatch.setattr(windows, "WinVaultKeyring", ExplicitWindowsBackend)
    monkeypatch.setattr(keyring, "get_keyring", lambda: pytest.fail("auto-selection must not run"))
    backend = _make_approved_backend("win32")
    assert isinstance(backend, ExplicitWindowsBackend)


def test_linux_selection_constructs_only_secret_service_backend(monkeypatch):
    import keyring

    class ExplicitSecretServiceBackend:
        pass

    fake_module = types.SimpleNamespace(Keyring=ExplicitSecretServiceBackend)
    monkeypatch.setitem(sys.modules, "keyring.backends.SecretService", fake_module)
    monkeypatch.setattr(keyring, "get_keyring", lambda: pytest.fail("auto-selection must not run"))
    backend = _make_approved_backend("linux")
    assert isinstance(backend, ExplicitSecretServiceBackend)


def test_session_store_is_explicit_memory_only_and_clears_on_request():
    store = SessionCredentialStore()
    store.set("default", "session-key")
    assert store.get("default") == "session-key"
    store.clear()
    assert store.get("default") is None


def test_invalid_secret_and_alias_are_rejected_without_echoing_values():
    store = SessionCredentialStore()
    sentinel = "bad\r\nkey-sentinel"
    with pytest.raises(ProviderCredentialError) as caught:
        store.set("default", sentinel)
    assert sentinel not in str(caught.value)
    with pytest.raises(ProviderCredentialError):
        store.set("../../path", "valid-key")

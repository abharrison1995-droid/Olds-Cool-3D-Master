"""Explicit OS credential backends with an opt-in memory-only fallback.

This module never uses keyring's auto-selected backend and never writes a key
to settings, files, or the application generation records.
"""

from __future__ import annotations

import re
import sys
from typing import Protocol
from urllib.parse import unquote

from .contracts import ProviderCredentialError


_SERVICE_NAME = "3d-master-2005/provider"
_ALIAS_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_MAX_CREDENTIAL_BYTES = 4096
_MAX_URL_PATH_CHARS = 16_384
_MAX_URL_PATH_DECODE_ROUNDS = 4
_MAX_CREDENTIAL_SCAN_BYTES = 1_048_576
_PERCENT_ESCAPE_RE = re.compile(r"%[0-9A-Fa-f]{2}")


def percent_decoded_representations(text: str) -> tuple[str, ...]:
    """Return a bounded set of standard percent-decoding layers.

    Four decoding rounds cover ordinary URL escaping, mixed literal/escaped
    text, and up to four nested encodings. Longer paths or another valid
    escape layer are rejected so callers can fail closed without unbounded
    decoding or allocation.
    """
    if not isinstance(text, str) or len(text) > _MAX_URL_PATH_CHARS:
        raise ValueError("text exceeds the percent-decoding safety bound")

    representations = [text]
    current = text
    for _ in range(_MAX_URL_PATH_DECODE_ROUNDS):
        decoded = unquote(current)
        if len(decoded) > _MAX_URL_PATH_CHARS:
            raise ValueError("text exceeds the percent-decoding safety bound")
        if decoded == current:
            return tuple(representations)
        representations.append(decoded)
        current = decoded

    if _PERCENT_ESCAPE_RE.search(current):
        raise ValueError("text has excessive nested percent encoding")
    return tuple(representations)


def contains_percent_encoded_secret(text: str, secret: str) -> bool:
    """Check literal and bounded percent-decoded text without returning it."""
    if not isinstance(secret, str) or not secret:
        return False
    return any(secret in item for item in percent_decoded_representations(text))


def contains_percent_encoded_secret_text(text: str, secret: str) -> bool:
    """Check bounded request/response text without decoding ordinary text.

    Large payloads without the literal secret or valid percent escapes take a
    fast path. Text that needs decoding is limited to 1 MiB per layer and four
    rounds; excessive or invalid input raises ValueError for the caller to
    reject with its fixed safe error.
    """
    if not isinstance(text, str) or not isinstance(secret, str) or not secret:
        return False
    if secret in text:
        return True
    if not _PERCENT_ESCAPE_RE.search(text):
        return False

    current = text
    for _ in range(_MAX_URL_PATH_DECODE_ROUNDS):
        if not _fits_credential_scan_limit(current):
            raise ValueError("text exceeds the credential scan safety bound")
        try:
            decoded = unquote(current)
        except (UnicodeError, ValueError):
            raise ValueError("text cannot be safely percent-decoded") from None
        if not _fits_credential_scan_limit(decoded):
            raise ValueError("text exceeds the credential scan safety bound")
        if secret in decoded:
            return True
        if decoded == current:
            return False
        current = decoded

    if _PERCENT_ESCAPE_RE.search(current):
        raise ValueError("text has excessive nested percent encoding")
    return False


def _fits_credential_scan_limit(text: str) -> bool:
    # Character count is a cheap lower bound; the byte count then enforces the
    # same one-MiB ceiling used by provider requests and responses.
    if len(text) > _MAX_CREDENTIAL_SCAN_BYTES:
        return False
    try:
        return len(text.encode("utf-8", errors="strict")) <= _MAX_CREDENTIAL_SCAN_BYTES
    except UnicodeEncodeError:
        return False


class CredentialStore(Protocol):
    def get(self, alias: str) -> str | None: ...
    def set(self, alias: str, secret: str) -> None: ...
    def delete(self, alias: str) -> None: ...


class SystemCredentialStore:
    """Credential Manager on Windows or Secret Service on Linux.

    The constructor always creates an explicit supported backend and does not
    call ``keyring.get_keyring()`` or consult keyring configuration.
    """

    def __init__(self, platform: str | None = None) -> None:
        self._platform = platform or sys.platform
        self._backend = _make_approved_backend(self._platform)

    def get(self, alias: str) -> str | None:
        _validate_alias(alias)
        try:
            value = self._backend.get_password(_SERVICE_NAME, alias)  # type: ignore[attr-defined]
        except Exception:
            raise ProviderCredentialError(
                "The system credential store is locked or unavailable. Unlock it or enter a session-only key."
            ) from None
        if value is None:
            return None
        if not isinstance(value, str) or not _valid_secret(value):
            raise ProviderCredentialError("The saved provider credential has an invalid format. Replace it.")
        return value

    def set(self, alias: str, secret: str) -> None:
        _validate_alias(alias)
        if not _valid_secret(secret):
            raise ProviderCredentialError("Provider key must be printable text no longer than 4096 bytes.")
        try:
            self._backend.set_password(_SERVICE_NAME, alias, secret)  # type: ignore[attr-defined]
        except Exception:
            raise ProviderCredentialError(
                "The system credential store is locked or unavailable. Unlock it or enter a session-only key."
            ) from None

    def delete(self, alias: str) -> None:
        _validate_alias(alias)
        try:
            self._backend.delete_password(_SERVICE_NAME, alias)  # type: ignore[attr-defined]
        except Exception as exc:
            # keyring uses PasswordDeleteError for a missing item. Check only
            # the exception class name; never inspect or expose its message.
            if type(exc).__name__ == "PasswordDeleteError":
                return
            raise ProviderCredentialError(
                "The system credential store is locked or unavailable. Unlock it or try again."
            ) from None


class SessionCredentialStore:
    """Explicit session-only store; values live only in this process object."""

    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}

    def get(self, alias: str) -> str | None:
        _validate_alias(alias)
        return self._secrets.get(alias)

    def set(self, alias: str, secret: str) -> None:
        _validate_alias(alias)
        if not _valid_secret(secret):
            raise ProviderCredentialError("Provider key must be printable text no longer than 4096 bytes.")
        self._secrets[alias] = secret

    def delete(self, alias: str) -> None:
        _validate_alias(alias)
        self._secrets.pop(alias, None)

    def clear(self) -> None:
        self._secrets.clear()


def _make_approved_backend(platform: str) -> object:
    try:
        if platform.startswith("win"):
            from keyring.backends.Windows import WinVaultKeyring

            return WinVaultKeyring()
        if platform.startswith("linux"):
            from keyring.backends.SecretService import Keyring

            return Keyring()
    except Exception:
        raise ProviderCredentialError(
            "The approved system credential backend is unavailable. Install or unlock the OS credential service, or use a session-only key."
        ) from None
    raise ProviderCredentialError(
        "This platform has no approved persistent credential backend. Use a session-only key."
    )


def _validate_alias(alias: str) -> None:
    if not isinstance(alias, str) or not _ALIAS_RE.fullmatch(alias):
        raise ProviderCredentialError("Credential alias must use 1 to 128 letters, digits, dots, underscores, or hyphens.")


def _valid_secret(secret: object) -> bool:
    if not isinstance(secret, str) or not secret:
        return False
    try:
        encoded = secret.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return False
    return len(encoded) <= _MAX_CREDENTIAL_BYTES and all(0x21 <= ord(char) <= 0x7E for char in secret)

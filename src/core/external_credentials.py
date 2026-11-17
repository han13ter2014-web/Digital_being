"""Секреты внешних провайдеров вне checkpoint, журналов и EventBus."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import re
from typing import Dict, Optional

_PROVIDER_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")


class CredentialError(RuntimeError):
    """Ошибка хранилища без включения секрета в сообщение."""


class CredentialNotFound(CredentialError):
    """Для провайдера не сохранён ключ."""


def _provider(value: str) -> str:
    provider = str(value or "").strip().lower()
    if _PROVIDER_RE.fullmatch(provider) is None:
        raise ValueError("provider: expected a bounded lowercase identifier")
    return provider


def credential_target(provider: str) -> str:
    return f"DigitalBeing/{_provider(provider)}"


class MemoryCredentialStore:
    """Изолированный backend для тестов и временных процессов."""

    def __init__(self) -> None:
        self._values: Dict[str, str] = {}

    def get(self, target: str) -> Optional[str]:
        return self._values.get(target)

    def set(self, target: str, value: str) -> None:
        if not isinstance(value, str) or not value.strip() or len(value) > 4096:
            raise ValueError("credential: expected a bounded nonempty string")
        self._values[target] = value.strip()

    def delete(self, target: str) -> bool:
        return self._values.pop(target, None) is not None


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", _FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class WindowsCredentialStore:
    """Generic Credentials текущего пользователя Windows через Win32 API."""

    _FILETIME = _FILETIME
    _CREDENTIALW = _CREDENTIALW

    def __init__(self) -> None:
        if os.name != "nt":
            raise CredentialError("Windows Credential Manager is unavailable")
        self._advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        self._declare()

    def _declare(self) -> None:
        credential = self._CREDENTIALW
        pointer = ctypes.POINTER(credential)
        self._advapi.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(pointer),
        ]
        self._advapi.CredReadW.restype = wintypes.BOOL
        self._advapi.CredWriteW.argtypes = [pointer, wintypes.DWORD]
        self._advapi.CredWriteW.restype = wintypes.BOOL
        self._advapi.CredDeleteW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        self._advapi.CredDeleteW.restype = wintypes.BOOL
        self._advapi.CredFree.argtypes = [ctypes.c_void_p]
        self._advapi.CredFree.restype = None

    @staticmethod
    def _error(action: str) -> CredentialError:
        code = ctypes.get_last_error()
        return CredentialError(f"{action} failed with Win32 error {code}")

    def get(self, target: str) -> Optional[str]:
        pointer = ctypes.POINTER(self._CREDENTIALW)()
        if not self._advapi.CredReadW(target, 1, 0, ctypes.byref(pointer)):
            code = ctypes.get_last_error()
            if code == 1168:  # ERROR_NOT_FOUND
                return None
            raise self._error("CredReadW")
        try:
            size = int(pointer.contents.CredentialBlobSize)
            if size <= 0 or size > 8192:
                raise CredentialError("Credential blob has an invalid size")
            raw = ctypes.string_at(pointer.contents.CredentialBlob, size)
            return raw.decode("utf-16-le")
        finally:
            self._advapi.CredFree(pointer)

    def set(self, target: str, value: str) -> None:
        if not isinstance(value, str) or not value.strip() or len(value) > 4096:
            raise ValueError("credential: expected a bounded nonempty string")
        raw = value.strip().encode("utf-16-le")
        buffer = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
        credential = self._CREDENTIALW()
        credential.Type = 1  # CRED_TYPE_GENERIC
        credential.TargetName = target
        credential.Comment = "Digital Being external provider credential"
        credential.CredentialBlobSize = len(raw)
        credential.CredentialBlob = buffer
        credential.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE
        if not self._advapi.CredWriteW(ctypes.byref(credential), 0):
            raise self._error("CredWriteW")

    def delete(self, target: str) -> bool:
        if self._advapi.CredDeleteW(target, 1, 0):
            return True
        code = ctypes.get_last_error()
        if code == 1168:
            return False
        raise self._error("CredDeleteW")


def provider_api_key(provider: str, *, store=None) -> str:
    """Получить ключ из env или Credential Manager, не раскрывая его."""
    provider = _provider(provider)
    configured = os.environ.get(f"{provider.upper()}_API_KEY", "").strip()
    if configured:
        return configured
    backend = store or WindowsCredentialStore()
    value = backend.get(credential_target(provider))
    if not value:
        raise CredentialNotFound(f"API key is not configured for {provider}")
    return value

"""Server-side tenant database secret providers."""

from __future__ import annotations

import ctypes
import os
import re
import tempfile
from pathlib import Path
from typing import Protocol
from ctypes import wintypes


CRYPTPROTECT_UI_FORBIDDEN = 0x1
CRYPTPROTECT_LOCAL_MACHINE = 0x4
_SECRET_REF_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


class SecretError(RuntimeError):
    """Base error that never includes a secret value."""


class SecretNotFoundError(SecretError):
    pass


class SecretProtectionError(SecretError):
    pass


class SecretReferenceError(SecretError):
    pass


class SecretProvider(Protocol):
    def get_database_secret(self, secret_ref: str) -> str: ...

    def put_database_secret(self, secret_ref: str, secret: str) -> None: ...

    def delete_database_secret(self, secret_ref: str) -> None: ...


def _validate_secret_ref(secret_ref: str) -> str:
    if not _SECRET_REF_PATTERN.fullmatch(secret_ref):
        raise SecretReferenceError("invalid secret reference")
    return secret_ref


def _validate_secret(secret: str) -> str:
    if not isinstance(secret, str) or not secret:
        raise SecretProtectionError("database secret must be non-empty")
    return secret


class InMemorySecretProvider:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self._values = dict(values or {})

    def get_database_secret(self, secret_ref: str) -> str:
        reference = _validate_secret_ref(secret_ref)
        try:
            return self._values[reference]
        except KeyError as error:
            raise SecretNotFoundError(f"secret reference not found: {reference}") from error

    def put_database_secret(self, secret_ref: str, secret: str) -> None:
        self._values[_validate_secret_ref(secret_ref)] = _validate_secret(secret)

    def delete_database_secret(self, secret_ref: str) -> None:
        self._values.pop(_validate_secret_ref(secret_ref), None)

    def __repr__(self) -> str:
        return f"InMemorySecretProvider(references={sorted(self._values)})"


class EnvironmentSecretProvider:
    def __init__(self, prefix: str = "SMART_CRM_TENANT_SECRET_") -> None:
        self._prefix = prefix

    def get_database_secret(self, secret_ref: str) -> str:
        reference = _validate_secret_ref(secret_ref)
        variable = self._prefix + reference.replace("-", "_").replace(".", "_").upper()
        value = os.getenv(variable)
        if not value:
            raise SecretNotFoundError(f"secret reference not found: {reference}")
        return value

    def put_database_secret(self, secret_ref: str, secret: str) -> None:
        raise TypeError("environment secret provider is read-only")

    def delete_database_secret(self, secret_ref: str) -> None:
        raise TypeError("environment secret provider is read-only")

    def __repr__(self) -> str:
        return f"EnvironmentSecretProvider(prefix={self._prefix!r})"


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


class DpapiProtector:
    """Protect bytes with Windows DPAPI bound to the current service identity."""

    flags = CRYPTPROTECT_UI_FORBIDDEN

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("Windows DPAPI is available only on Windows")
        self._crypt32 = ctypes.WinDLL("Crypt32.dll", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)

    @staticmethod
    def _input_blob(value: bytes) -> tuple[ctypes.Array, _DataBlob]:
        buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
        return buffer, _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))

    def protect(self, plaintext: bytes) -> bytes:
        _buffer, input_blob = self._input_blob(plaintext)
        output_blob = _DataBlob()
        succeeded = self._crypt32.CryptProtectData(
            ctypes.byref(input_blob),
            "Smart CRM tenant database secret",
            None,
            None,
            None,
            self.flags,
            ctypes.byref(output_blob),
        )
        return self._consume_output(succeeded, output_blob)

    def unprotect(self, ciphertext: bytes) -> bytes:
        _buffer, input_blob = self._input_blob(ciphertext)
        output_blob = _DataBlob()
        succeeded = self._crypt32.CryptUnprotectData(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            self.flags,
            ctypes.byref(output_blob),
        )
        return self._consume_output(succeeded, output_blob)

    def _consume_output(self, succeeded: int, output_blob: _DataBlob) -> bytes:
        if not succeeded:
            error = ctypes.get_last_error()
            raise SecretProtectionError(f"DPAPI operation failed with Windows error {error}")
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            self._kernel32.LocalFree(output_blob.pbData)


class DpapiFileSecretProvider:
    def __init__(self, root: Path | str, *, protector: object | None = None) -> None:
        self._root = Path(root)
        self._protector = protector or DpapiProtector()

    def _path(self, secret_ref: str) -> Path:
        return self._root / f"{_validate_secret_ref(secret_ref)}.bin"

    def get_database_secret(self, secret_ref: str) -> str:
        path = self._path(secret_ref)
        try:
            ciphertext = path.read_bytes()
        except FileNotFoundError as error:
            raise SecretNotFoundError(f"secret reference not found: {secret_ref}") from error
        try:
            return self._protector.unprotect(ciphertext).decode("utf-8")
        except (UnicodeDecodeError, ValueError) as error:
            raise SecretProtectionError("protected database secret is invalid") from error

    def put_database_secret(self, secret_ref: str, secret: str) -> None:
        path = self._path(secret_ref)
        plaintext = _validate_secret(secret).encode("utf-8")
        ciphertext = self._protector.protect(plaintext)
        self._root.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=self._root)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(ciphertext)
            os.chmod(temporary_name, 0o600)
            os.replace(temporary_name, path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def delete_database_secret(self, secret_ref: str) -> None:
        try:
            self._path(secret_ref).unlink()
        except FileNotFoundError:
            pass

    def __repr__(self) -> str:
        return f"DpapiFileSecretProvider(root={str(self._root)!r}, protector=<redacted>)"

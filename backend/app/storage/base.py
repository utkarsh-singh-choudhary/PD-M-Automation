"""
Storage abstraction so the rest of the app (attachment uploads, Excel
import uploads) never depends on filesystem paths or a specific provider.
Everything is addressed by an opaque `key` (e.g.
"attachments/2026/09/<pm_id>_<uuid>.jpg") - callers never construct or
trust a filesystem path from a client request (that was Critical #4 in the
production review, applied consistently here too).

Both PMActual.attachment_path and PendingUpload.stored_path now store a
`key` in this sense, not a raw filesystem path - the concrete meaning of
that key (a local file under LOCAL_STORAGE_DIR, or an S3 object) is
resolved by whichever backend is configured via STORAGE_BACKEND.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import BinaryIO, Optional


@dataclass
class StoredObject:
    key: str
    size: int


class ObjectStorage(ABC):
    @abstractmethod
    def put(self, key: str, data: bytes, content_type: Optional[str] = None) -> StoredObject:
        """Write `data` under `key`, overwriting if it already exists."""

    @abstractmethod
    def get(self, key: str) -> bytes:
        """Read the full contents stored under `key`. Raises FileNotFoundError-like
        errors (backend-specific) if the key doesn't exist - callers should
        catch broadly and translate to an HTTP 404."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        ...

    @abstractmethod
    def delete(self, key: str) -> None:
        """No-op if the key doesn't exist - deletion is idempotent."""

    @abstractmethod
    def url(self, key: str, expires_seconds: int = 300) -> Optional[str]:
        """A time-limited URL the client can fetch directly, if the backend
        supports it (S3 presigned URLs). Returns None for backends that
        don't (local disk) - callers should fall back to streaming the
        bytes through the API in that case."""

    @abstractmethod
    def list_with_age(self, prefix: str) -> list:
        """List every stored key under `prefix`, returning
        [{"key": str, "age_days": float}, ...]. Used by the periodic
        attachment-retention job (Medium: "Attachment lifecycle cleanup is
        missing") to find objects old enough to garbage-collect."""

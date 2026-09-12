import os
from typing import Optional

from app.storage.base import ObjectStorage, StoredObject


class LocalDiskStorage(ObjectStorage):
    """
    Dev/small-deployment fallback: writes under a configured directory that
    is expected to be a real persistent volume (LOCAL_STORAGE_DIR), NOT
    /tmp - that was Critical #5/#6 in the production review (a container
    restart or redeploy wipes /tmp, and it isn't shared across replicas).
    This still doesn't solve the multi-replica-API problem on its own
    (each replica would need the same mounted volume) - for a genuinely
    multi-instance deployment, use STORAGE_BACKEND=s3 instead.
    """

    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        os.makedirs(self.root_dir, exist_ok=True)

    def _path(self, key: str) -> str:
        # key is always generated server-side (uuid-based), never taken
        # directly from client input - but normalize defensively anyway so
        # a key can never escape root_dir via "../".
        safe_key = os.path.normpath(key).lstrip("/")
        if ".." in safe_key.split(os.sep):
            raise ValueError(f"Invalid storage key: {key!r}")
        full_path = os.path.join(self.root_dir, safe_key)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        return full_path

    def put(self, key: str, data: bytes, content_type: Optional[str] = None) -> StoredObject:
        path = self._path(key)
        with open(path, "wb") as f:
            f.write(data)
        return StoredObject(key=key, size=len(data))

    def get(self, key: str) -> bytes:
        with open(self._path(key), "rb") as f:
            return f.read()

    def exists(self, key: str) -> bool:
        try:
            return os.path.exists(self._path(key))
        except ValueError:
            return False

    def delete(self, key: str) -> None:
        try:
            os.remove(self._path(key))
        except (FileNotFoundError, ValueError):
            pass

    def url(self, key: str, expires_seconds: int = 300) -> Optional[str]:
        return None  # no presigned URLs for local disk - caller streams via the API

    def list_with_age(self, prefix: str) -> list:
        import time
        base = self._path(prefix) if prefix else self.root_dir
        results = []
        if not os.path.isdir(base):
            # prefix might itself be a partial filename prefix, not a dir -
            # walk root_dir and filter, which also covers that case safely.
            base = self.root_dir
        now = time.time()
        for dirpath, _dirs, files in os.walk(base):
            for name in files:
                full = os.path.join(dirpath, name)
                key = os.path.relpath(full, self.root_dir).replace(os.sep, "/")
                if prefix and not key.startswith(prefix):
                    continue
                age_days = (now - os.path.getmtime(full)) / 86400
                results.append({"key": key, "age_days": age_days})
        return results

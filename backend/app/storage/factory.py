from functools import lru_cache

from app.core.config import settings
from app.storage.base import ObjectStorage


@lru_cache
def get_storage() -> ObjectStorage:
    """Singleton storage client, chosen by STORAGE_BACKEND. lru_cache means
    the S3 client (or local dir setup) is only built once per process."""
    if settings.STORAGE_BACKEND == "s3":
        from app.storage.s3_storage import S3CompatibleStorage
        if not settings.S3_BUCKET:
            raise RuntimeError("STORAGE_BACKEND=s3 requires S3_BUCKET to be set")
        return S3CompatibleStorage(
            bucket=settings.S3_BUCKET,
            region=settings.S3_REGION,
            endpoint_url=settings.S3_ENDPOINT_URL,
            access_key_id=settings.S3_ACCESS_KEY_ID,
            secret_access_key=settings.S3_SECRET_ACCESS_KEY,
        )

    from app.storage.local_storage import LocalDiskStorage
    return LocalDiskStorage(root_dir=settings.LOCAL_STORAGE_DIR)

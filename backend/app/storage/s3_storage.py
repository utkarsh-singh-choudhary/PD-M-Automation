from typing import Optional

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from app.storage.base import ObjectStorage, StoredObject


class S3CompatibleStorage(ObjectStorage):
    """
    Works against AWS S3, Cloudflare R2, or MinIO - they all speak the same
    S3 API, and boto3's `endpoint_url` override is all that changes between
    them. This is the recommended production backend: it survives
    redeploys and container restarts, and works correctly with multiple
    API replicas since there's no shared-filesystem assumption.

    Setup differences (all handled the same way through the same class):
    - AWS S3: leave S3_ENDPOINT_URL blank, set S3_REGION to the bucket's region.
    - Cloudflare R2: S3_ENDPOINT_URL=https://<account_id>.r2.cloudflarestorage.com,
      S3_REGION="auto".
    - MinIO (self-hosted): S3_ENDPOINT_URL=http://minio:9000 (or your host),
      S3_REGION can be any placeholder value MinIO doesn't check.
    """

    def __init__(self, bucket: str, region: str, endpoint_url: str,
                 access_key_id: str, secret_access_key: str):
        self.bucket = bucket
        session = boto3.session.Session()
        self.client = session.client(
            "s3",
            region_name=region or None,
            endpoint_url=endpoint_url or None,
            aws_access_key_id=access_key_id or None,
            aws_secret_access_key=secret_access_key or None,
            config=BotoConfig(signature_version="s3v4"),
        )

    def put(self, key: str, data: bytes, content_type: Optional[str] = None) -> StoredObject:
        extra = {"ContentType": content_type} if content_type else {}
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, **extra)
        return StoredObject(key=key, size=len(data))

    def get(self, key: str) -> bytes:
        obj = self.client.get_object(Bucket=self.bucket, Key=key)
        return obj["Body"].read()

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def delete(self, key: str) -> None:
        # S3 delete_object is idempotent - no error if the key is already gone.
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def url(self, key: str, expires_seconds: int = 300) -> Optional[str]:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_seconds,
        )

    def list_with_age(self, prefix: str) -> list:
        from datetime import datetime, timezone
        results = []
        paginator = self.client.get_paginator("list_objects_v2")
        now = datetime.now(timezone.utc)
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                last_modified = obj["LastModified"]
                age_days = (now - last_modified).total_seconds() / 86400
                results.append({"key": obj["Key"], "age_days": age_days})
        return results

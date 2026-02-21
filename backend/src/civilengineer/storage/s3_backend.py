"""
S3/MinIO storage backend.

Uses boto3 with path-style addressing for MinIO compatibility.
Presigned URLs are generated for direct client → storage uploads (no proxy through API).
"""

from __future__ import annotations

import io

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from civilengineer.core.config import get_settings


def _get_client():
    settings = get_settings()
    config = Config(
        signature_version="s3v4",
        s3={"addressing_style": "path"},  # Required for MinIO
    )
    return boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT_URL,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        region_name=settings.S3_REGION,
        config=config,
    )


def ensure_bucket_exists(bucket: str) -> None:
    """Create bucket if it does not exist. Idempotent."""
    client = _get_client()
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        if error_code in ("404", "NoSuchBucket"):
            client.create_bucket(Bucket=bucket)
        else:
            raise


def generate_presigned_upload_url(
    bucket: str,
    key: str,
    content_type: str = "application/octet-stream",
    expiry: int = 3600,
) -> str:
    """Return a presigned PUT URL — client uploads directly to S3/MinIO."""
    client = _get_client()
    return client.generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket, "Key": key, "ContentType": content_type},
        ExpiresIn=expiry,
        HttpMethod="PUT",
    )


def generate_presigned_download_url(
    bucket: str,
    key: str,
    expiry: int = 3600,
) -> str:
    """Return a presigned GET URL — client downloads directly from S3/MinIO."""
    client = _get_client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expiry,
    )


def download_bytes(bucket: str, key: str) -> bytes:
    """Download an S3 object and return its raw bytes."""
    client = _get_client()
    buf = io.BytesIO()
    client.download_fileobj(bucket, key, buf)
    return buf.getvalue()


def upload_bytes(
    bucket: str,
    key: str,
    data: bytes,
    content_type: str = "application/octet-stream",
) -> None:
    """Upload raw bytes to S3/MinIO."""
    client = _get_client()
    client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)

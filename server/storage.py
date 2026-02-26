"""Railway Bucket (S3-compatible) storage for replay files."""

import logging
import os

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Lazy-initialized S3 client
_s3_client = None
_bucket_name = None

REPLAY_PREFIX = "replays/"


def _get_client():
    """Lazily initialize and return the S3 client and bucket name."""
    global _s3_client, _bucket_name
    if _s3_client is None:
        endpoint = os.environ.get("AWS_ENDPOINT_URL", "")
        access_key = os.environ.get("AWS_ACCESS_KEY_ID", "")
        secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
        _bucket_name = os.environ.get("AWS_S3_BUCKET_NAME", "")

        if not all([endpoint, access_key, secret_key, _bucket_name]):
            raise RuntimeError(
                "Missing bucket configuration. Set AWS_ENDPOINT_URL, "
                "AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and AWS_S3_BUCKET_NAME."
            )

        _s3_client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
    return _s3_client, _bucket_name


def upload_replay(file_bytes: bytes, sha256: str) -> None:
    """Upload a replay file to the bucket. Idempotent (overwrites identical content)."""
    client, bucket = _get_client()
    key = f"{REPLAY_PREFIX}{sha256}.aoe2record"
    try:
        client.put_object(Bucket=bucket, Key=key, Body=file_bytes)
        logger.info(f"Uploaded replay {sha256} to bucket")
    except ClientError as e:
        logger.error(f"Failed to upload replay {sha256}: {e}")
        raise


def download_replay(sha256: str) -> bytes:
    """Download a replay file from the bucket by SHA256."""
    client, bucket = _get_client()
    key = f"{REPLAY_PREFIX}{sha256}.aoe2record"
    try:
        response = client.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()
    except ClientError as e:
        logger.error(f"Failed to download replay {sha256}: {e}")
        raise


def list_replays() -> list:
    """List all replays in the bucket. Returns list of dicts with sha256 and size."""
    client, bucket = _get_client()
    replays = []
    continuation_token = None

    while True:
        kwargs = {"Bucket": bucket, "Prefix": REPLAY_PREFIX}
        if continuation_token:
            kwargs["ContinuationToken"] = continuation_token

        response = client.list_objects_v2(**kwargs)

        for obj in response.get("Contents", []):
            key = obj["Key"]
            # Extract sha256 from key like "replays/{sha256}.aoe2record"
            filename = key[len(REPLAY_PREFIX) :]
            if filename.endswith(".aoe2record"):
                sha = filename[: -len(".aoe2record")]
                replays.append({"sha256": sha, "size": obj["Size"]})

        if response.get("IsTruncated"):
            continuation_token = response["NextContinuationToken"]
        else:
            break

    return replays

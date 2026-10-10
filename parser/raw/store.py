"""Тела сырых ответов в S3: raw/{yyyy-mm-dd}/{task_id}/{page}.json.gz (техспека §7)."""

import gzip
from datetime import datetime
from typing import Any

import aioboto3
from botocore.exceptions import ClientError

from core.config import Settings


def raw_key(received_at: datetime, task_id: int | str, page: int, kind: str) -> str:
    return f"raw/{received_at:%Y-%m-%d}/{task_id}/{page:04d}-{kind}.json.gz"


class RawStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._session = aioboto3.Session()

    def _client(self) -> Any:
        s = self._settings
        return self._session.client(
            "s3",
            endpoint_url=s.s3_endpoint,
            aws_access_key_id=s.s3_access_key,
            aws_secret_access_key=s.s3_secret_key,
            region_name="us-east-1",
        )

    async def ensure_bucket(self) -> None:
        async with self._client() as s3:
            try:
                await s3.head_bucket(Bucket=self._settings.s3_bucket)
            except ClientError:
                await s3.create_bucket(Bucket=self._settings.s3_bucket)

    async def put(self, key: str, body: bytes) -> None:
        async with self._client() as s3:
            await s3.put_object(
                Bucket=self._settings.s3_bucket,
                Key=key,
                Body=gzip.compress(body),
                ContentType="application/json",
                ContentEncoding="gzip",
            )

    async def get(self, key: str) -> bytes:
        async with self._client() as s3:
            obj = await s3.get_object(Bucket=self._settings.s3_bucket, Key=key)
            data: bytes = await obj["Body"].read()
            return gzip.decompress(data)

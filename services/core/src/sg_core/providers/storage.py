"""S3-compatible object storage (`ObjectStore`): MinIO locally, Cloudflare R2 now, AWS S3 later.

Switching providers is a settings change (`S3_ENDPOINT_URL`, keys). boto3 is synchronous, so calls
run in a worker thread. Keys are namespaced by the caller; this adapter has no policy.
"""

import asyncio
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from sg_core.economics.usage import NullUsageRecorder, UsageContext, UsageMeasure, UsageRecorder
from sg_core.providers.base import ProviderError, ProviderNotConfiguredError

PROVIDER = "object_store"


class ObjectNotFoundError(KeyError):
    pass


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    data: bytes
    content_type: str | None = None


class ObjectStore(Protocol):
    async def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
        usage: UsageContext | None = None,
    ) -> None: ...
    async def get(self, key: str) -> StoredObject: ...
    async def exists(self, key: str) -> bool: ...
    async def delete(self, key: str) -> None: ...
    async def list_keys(self, prefix: str = "", *, limit: int = 1000) -> list[str]: ...
    async def presigned_get_url(self, key: str, *, expires_seconds: int = 900) -> str: ...
    async def presigned_put_url(
        self, key: str, *, content_type: str | None = None, expires_seconds: int = 900
    ) -> str: ...


class S3ObjectStore:
    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None,
        access_key_id: str,
        secret_access_key: str,
        region: str = "auto",
        recorder: UsageRecorder | None = None,
        client: Any | None = None,
    ) -> None:
        self._bucket = bucket
        self._recorder: UsageRecorder = recorder or NullUsageRecorder()
        self._s3 = client or boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
            # Path-style works on MinIO, R2 and S3; v4 signatures are required by R2.
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    async def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
        usage: UsageContext | None = None,
    ) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        await self._call(self._s3.put_object, Bucket=self._bucket, Key=key, Body=data, **extra)
        if usage is not None:
            await self._recorder.record(
                usage,
                UsageMeasure(
                    provider=PROVIDER,
                    external_ref=key,
                    storage_bytes=len(data),
                    billable_units=Decimal(len(data)),
                    billable_unit="byte",
                ),
            )

    async def get(self, key: str) -> StoredObject:
        try:
            response = await self._call(self._s3.get_object, Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if _code(exc) in {"NoSuchKey", "404", "NotFound"}:
                raise ObjectNotFoundError(key) from exc
            raise ProviderError(PROVIDER, None, str(exc)) from exc
        body = await asyncio.to_thread(response["Body"].read)
        return StoredObject(key=key, data=body, content_type=response.get("ContentType"))

    async def exists(self, key: str) -> bool:
        try:
            await self._call(self._s3.head_object, Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if _code(exc) in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise ProviderError(PROVIDER, None, str(exc)) from exc
        return True

    async def delete(self, key: str) -> None:
        await self._call(self._s3.delete_object, Bucket=self._bucket, Key=key)

    async def list_keys(self, prefix: str = "", *, limit: int = 1000) -> list[str]:
        response = await self._call(
            self._s3.list_objects_v2, Bucket=self._bucket, Prefix=prefix, MaxKeys=limit
        )
        return [item["Key"] for item in response.get("Contents", [])]

    async def presigned_get_url(self, key: str, *, expires_seconds: int = 900) -> str:
        return str(
            self._s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires_seconds,
            )
        )

    async def presigned_put_url(
        self, key: str, *, content_type: str | None = None, expires_seconds: int = 900
    ) -> str:
        params: dict[str, Any] = {"Bucket": self._bucket, "Key": key}
        if content_type:
            params["ContentType"] = content_type
        return str(
            self._s3.generate_presigned_url("put_object", Params=params, ExpiresIn=expires_seconds)
        )

    async def _call(self, fn: Any, **kwargs: Any) -> Any:
        try:
            return await asyncio.to_thread(fn, **kwargs)
        except ClientError:
            raise
        except Exception as exc:  # botocore connection errors etc.
            raise ProviderError(PROVIDER, None, f"{type(exc).__name__}: {exc}") from exc


def _code(exc: ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Code", ""))


class InMemoryObjectStore:
    """Test double with the same contract; URLs are fake `memory://` links."""

    def __init__(self, recorder: UsageRecorder | None = None) -> None:
        self._objects: dict[str, StoredObject] = {}
        self._recorder: UsageRecorder = recorder or NullUsageRecorder()

    async def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
        usage: UsageContext | None = None,
    ) -> None:
        self._objects[key] = StoredObject(key, data, content_type)
        if usage is not None:
            await self._recorder.record(
                usage,
                UsageMeasure(provider=PROVIDER, external_ref=key, storage_bytes=len(data)),
            )

    async def get(self, key: str) -> StoredObject:
        try:
            return self._objects[key]
        except KeyError:
            raise ObjectNotFoundError(key) from None

    async def exists(self, key: str) -> bool:
        return key in self._objects

    async def delete(self, key: str) -> None:
        self._objects.pop(key, None)

    async def list_keys(self, prefix: str = "", *, limit: int = 1000) -> list[str]:
        return sorted(k for k in self._objects if k.startswith(prefix))[:limit]

    async def presigned_get_url(self, key: str, *, expires_seconds: int = 900) -> str:
        return f"memory://{key}?expires={expires_seconds}"

    async def presigned_put_url(
        self, key: str, *, content_type: str | None = None, expires_seconds: int = 900
    ) -> str:
        return f"memory://{key}?put=1&expires={expires_seconds}"


class LocalFileObjectStore:
    """Development stand-in for S3 on a machine without MinIO: one file per key under `root`.

    Same contract as the other stores; presigned URLs are `file://` links, so they are not
    shareable. Use only locally.
    """

    def __init__(self, root: Path, recorder: UsageRecorder | None = None) -> None:
        self._root = root.resolve()
        self._recorder: UsageRecorder = recorder or NullUsageRecorder()

    def _path(self, key: str) -> Path:
        path = (self._root / key).resolve()
        if self._root not in path.parents:
            raise ValueError(f"object key escapes the storage root: {key!r}")
        return path

    async def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
        usage: UsageContext | None = None,
    ) -> None:
        path = self._path(key)
        try:
            await asyncio.to_thread(self._write, path, data, content_type)
        except OSError as exc:
            raise ProviderError(PROVIDER, None, f"{type(exc).__name__}: {exc}") from exc
        if usage is not None:
            await self._recorder.record(
                usage,
                UsageMeasure(provider=PROVIDER, external_ref=key, storage_bytes=len(data)),
            )

    @staticmethod
    def _write(path: Path, data: bytes, content_type: str | None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.with_name(path.name + ".meta").write_text(json.dumps({"content_type": content_type}))

    async def get(self, key: str) -> StoredObject:
        path = self._path(key)
        try:
            data = await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError:
            raise ObjectNotFoundError(key) from None
        meta = path.with_name(path.name + ".meta")
        content_type = json.loads(meta.read_text()).get("content_type") if meta.exists() else None
        return StoredObject(key, data, content_type)

    async def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    async def delete(self, key: str) -> None:
        path = self._path(key)
        path.unlink(missing_ok=True)
        path.with_name(path.name + ".meta").unlink(missing_ok=True)

    async def list_keys(self, prefix: str = "", *, limit: int = 1000) -> list[str]:
        keys = (
            p.relative_to(self._root).as_posix()
            for p in self._root.rglob("*")
            if p.is_file() and p.suffix != ".meta"
        )
        return sorted(k for k in keys if k.startswith(prefix))[:limit]

    async def presigned_get_url(self, key: str, *, expires_seconds: int = 900) -> str:
        return self._path(key).as_uri()

    async def presigned_put_url(
        self, key: str, *, content_type: str | None = None, expires_seconds: int = 900
    ) -> str:
        return self._path(key).as_uri()


def object_store_from_settings(recorder: UsageRecorder | None = None) -> ObjectStore:
    from sg_core.economics.ledger import DbUsageRecorder
    from sg_core.settings import Environment, get_settings

    s = get_settings()
    if s.object_store == "local":
        if s.environment not in (Environment.LOCAL, Environment.TEST):
            raise ProviderNotConfiguredError("OBJECT_STORE=local is only allowed locally")
        return LocalFileObjectStore(s.local_storage_dir, recorder or DbUsageRecorder())
    if s.s3_access_key_id is None or s.s3_secret_access_key is None:
        raise ProviderNotConfiguredError(
            "S3_ACCESS_KEY_ID / S3_SECRET_ACCESS_KEY are not configured"
        )
    return S3ObjectStore(
        bucket=s.s3_bucket,
        endpoint_url=s.s3_endpoint_url,
        access_key_id=s.s3_access_key_id.get_secret_value(),
        secret_access_key=s.s3_secret_access_key.get_secret_value(),
        region=s.s3_region,
        recorder=recorder or DbUsageRecorder(),
    )

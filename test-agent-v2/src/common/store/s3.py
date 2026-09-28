"""S3ObjectStore — an S3-compatible (MinIO / AWS S3) adapter for the ObjectStore port.

The memory bank's generation-CAS (`get_blob(p).generation` -> `blob(p).upload_from_string(if_generation_match=g)`)
is mapped onto S3 **conditional writes**: the object's generation is kept in user metadata, and each CAS
write is closed with `If-None-Match: *` (create) or `If-Match: <etag>` (replace) so a racing writer 412s
-> CASConflict. `boto3`/`botocore` are imported lazily (base offline runs never need them).

ponytail: generation lives in metadata + is re-read live at write time; the conditional PUT closes the
TOCTOU window. Ceiling: needs an S3 server that honours If-Match on PUT (recent MinIO / AWS do). Env:
S3_ENDPOINT_URL, S3_BUCKET (required), S3_REGION (us-east-1), S3_ACCESS_KEY/S3_SECRET_KEY (else AWS_*).
"""

from __future__ import annotations

import os

from common.store.object_store import Blob, CASConflict

_GEN = "generation"  # user-metadata key holding the monotonic generation


def _is_precondition(exc) -> bool:
    from botocore.exceptions import ClientError

    if not isinstance(exc, ClientError):
        return False
    err = exc.response.get("Error", {})
    return err.get("Code") in ("PreconditionFailed", "412") or \
        exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 412


class _S3Blob:
    """A handle for one key. `etag`/`generation` are a snapshot when built by `get_blob`, else lazy."""

    def __init__(self, store: S3ObjectStore, name: str, etag=None, generation=None) -> None:
        self._store, self.name = store, name
        self._etag, self._gen = etag, generation

    def _head(self):
        """(etag, generation) live from S3, or (None, 0) if the key is absent."""
        from botocore.exceptions import ClientError

        try:
            r = self._store._client.head_object(Bucket=self._store._bucket, Key=self.name)
        except ClientError as exc:
            if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") in (404, 403):
                return None, 0
            raise
        return r["ETag"], int(r.get("Metadata", {}).get(_GEN, "0"))

    @property
    def generation(self) -> int:
        if self._gen is None:
            self._etag, self._gen = self._head()
        return self._gen

    def download_as_text(self) -> str:
        r = self._store._client.get_object(Bucket=self._store._bucket, Key=self.name)
        return r["Body"].read().decode("utf-8")

    def upload_from_string(self, data, content_type=None, if_generation_match=None) -> None:
        body = data.encode("utf-8") if isinstance(data, str) else data
        etag, cur = self._head()  # live state, closing the read->write window
        if if_generation_match is not None and if_generation_match != cur:
            raise CASConflict(f"generation mismatch: have {cur}, expected {if_generation_match}")
        kw = {"Bucket": self._store._bucket, "Key": self.name, "Body": body,
              "Metadata": {_GEN: str(cur + 1)}}
        if content_type:
            kw["ContentType"] = content_type
        if if_generation_match == 0:
            kw["IfNoneMatch"] = "*"           # create-only
        elif if_generation_match is not None:
            kw["IfMatch"] = etag              # replace-only-if-unchanged
        from botocore.exceptions import ClientError

        try:
            self._store._client.put_object(**kw)
        except ClientError as exc:
            if _is_precondition(exc):
                raise CASConflict(str(exc)) from exc
            raise


class S3ObjectStore:
    def __init__(self, client, bucket: str) -> None:
        self._client, self._bucket = client, bucket

    @classmethod
    def from_env(cls) -> S3ObjectStore:
        import boto3
        from botocore.config import Config

        client = boto3.client(
            "s3",
            endpoint_url=os.environ.get("S3_ENDPOINT_URL") or None,
            region_name=os.environ.get("S3_REGION", "us-east-1"),
            aws_access_key_id=os.environ.get("S3_ACCESS_KEY") or os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("S3_SECRET_KEY") or os.environ.get("AWS_SECRET_ACCESS_KEY"),
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),  # path-style = MinIO
        )
        return cls(client, os.environ["S3_BUCKET"])

    def blob(self, path: str) -> Blob:
        return _S3Blob(self, path)

    def get_blob(self, path: str) -> Blob | None:
        b = _S3Blob(self, path)
        etag, gen = b._head()
        if etag is None:
            return None
        b._etag, b._gen = etag, gen  # freeze the snapshot for the caller's CAS read
        return b

    def iter_blobs(self, prefix: str) -> list[Blob]:
        out, token = [], None
        while True:
            kw = {"Bucket": self._bucket, "Prefix": prefix}
            if token:
                kw["ContinuationToken"] = token
            r = self._client.list_objects_v2(**kw)
            out.extend(_S3Blob(self, o["Key"]) for o in r.get("Contents", []))
            if not r.get("IsTruncated"):
                return out
            token = r.get("NextContinuationToken")

    def delete(self, path: str) -> bool:
        existed = self.get_blob(path) is not None
        self._client.delete_object(Bucket=self._bucket, Key=path)
        return existed

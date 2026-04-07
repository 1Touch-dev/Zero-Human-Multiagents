#!/usr/bin/env python3
from __future__ import annotations

import os
from datetime import datetime, timezone

try:
    import boto3
except Exception:  # noqa: BLE001 - module remains optional
    boto3 = None


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def is_enabled(env: dict[str, str] | None = None) -> bool:
    source = env or os.environ
    return _truthy(source.get("ZERO_HUMAN_S3_ENABLED", "0"))


def _bucket_name(env: dict[str, str] | None = None) -> str | None:
    source = env or os.environ
    return (source.get("ZERO_HUMAN_S3_BUCKET") or source.get("AWS_S3_BUCKET") or "").strip() or None


def _region_name(env: dict[str, str] | None = None) -> str:
    source = env or os.environ
    return (source.get("ZERO_HUMAN_S3_REGION") or source.get("AWS_REGION") or "us-east-1").strip()


def _prefix(env: dict[str, str] | None = None) -> str:
    source = env or os.environ
    return (source.get("ZERO_HUMAN_S3_PREFIX") or "zero-human/runs").strip().strip("/")


def build_log_key(*, identifier: str, role_key: str, run_id: str | None = None, suffix: str = "run.log") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rid = (run_id or "no-run-id").strip() or "no-run-id"
    return f"{_prefix()}/{identifier}/{rid}/{role_key}/{stamp}-{suffix}"


def upload_text(text: str, *, key: str, content_type: str = "text/plain; charset=utf-8") -> str | None:
    if boto3 is None:
        return None
    bucket = _bucket_name()
    if not bucket:
        return None

    client = boto3.client("s3", region_name=_region_name())
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=text.encode("utf-8"),
        ContentType=content_type,
    )
    return f"s3://{bucket}/{key}"

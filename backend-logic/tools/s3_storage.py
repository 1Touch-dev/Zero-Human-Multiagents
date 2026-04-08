#!/usr/bin/env python3
"""
S3 Storage Layer — enforced artifact offloading.

RULES enforced by this module:
- Any file > 1MB is automatically uploaded to S3 and deleted locally.
- Sandbox output directories are swept after each run.
- Functions return S3 URI on success, None if S3 is disabled/unavailable.
- Never raises — EC2 disk usage must not block agent execution.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

try:
    import boto3
except Exception:  # noqa: BLE001 - module remains optional
    boto3 = None

# Files larger than this threshold are automatically offloaded to S3.
LARGE_FILE_THRESHOLD_BYTES = 1 * 1024 * 1024  # 1 MB


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

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


def _client():
    if boto3 is None:
        return None
    bucket = _bucket_name()
    if not bucket:
        return None
    return boto3.client("s3", region_name=_region_name()), bucket


# ---------------------------------------------------------------------------
# Key builders
# ---------------------------------------------------------------------------

def build_log_key(*, identifier: str, role_key: str, run_id: str | None = None, suffix: str = "run.log") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rid = (run_id or "no-run-id").strip() or "no-run-id"
    return f"{_prefix()}/{identifier}/{rid}/{role_key}/{stamp}-{suffix}"


def build_file_key(*, identifier: str, run_id: str | None = None, filename: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rid = (run_id or "no-run-id").strip() or "no-run-id"
    return f"{_prefix()}/{identifier}/{rid}/artifacts/{stamp}-{filename}"


# ---------------------------------------------------------------------------
# Upload functions
# ---------------------------------------------------------------------------

def upload_text(text: str, *, key: str, content_type: str = "text/plain; charset=utf-8") -> str | None:
    """Upload a text string to S3. Returns s3:// URI or None."""
    pair = _client()
    if pair is None:
        return None
    client, bucket = pair
    try:
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=text.encode("utf-8"),
            ContentType=content_type,
        )
        return f"s3://{bucket}/{key}"
    except Exception:  # noqa: BLE001 - never fail run on storage issues
        return None


def upload_file(local_path: str, *, key: str) -> str | None:
    """Upload a local file binary to S3. Returns s3:// URI or None."""
    pair = _client()
    if pair is None:
        return None
    client, bucket = pair
    try:
        client.upload_file(local_path, bucket, key)
        return f"s3://{bucket}/{key}"
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Enforcement: auto-offload large files
# ---------------------------------------------------------------------------

def offload_if_large(
    local_path: str,
    *,
    identifier: str,
    run_id: str | None = None,
    delete_after_upload: bool = True,
) -> str | None:
    """
    If the file at local_path is >= 1MB AND S3 is enabled:
      - Upload it to S3.
      - Delete the local file (if delete_after_upload=True).
      - Return the S3 URI.

    If file is small or S3 is disabled, returns None (no action taken).
    Never raises.
    """
    try:
        p = Path(local_path)
        if not p.exists():
            return None
        size = p.stat().st_size
        if size < LARGE_FILE_THRESHOLD_BYTES:
            return None
        if not is_enabled():
            print(
                f"[S3] File {local_path} is {size // 1024}KB (>= 1MB limit) "
                "but S3 is disabled (set ZERO_HUMAN_S3_ENABLED=1 to enable offloading)."
            )
            return None

        key = build_file_key(identifier=identifier, run_id=run_id, filename=p.name)
        s3_uri = upload_file(local_path, key=key)
        if s3_uri and delete_after_upload:
            try:
                p.unlink()
                print(f"[S3] Offloaded {local_path} ({size // 1024}KB) -> {s3_uri} and deleted local copy.")
            except Exception:  # noqa: BLE001
                print(f"[S3] Uploaded {local_path} -> {s3_uri} but could not delete local copy.")
        elif s3_uri:
            print(f"[S3] Uploaded {local_path} ({size // 1024}KB) -> {s3_uri} (local copy kept).")
        return s3_uri
    except Exception:  # noqa: BLE001
        return None


def sweep_sandbox_output(
    sandbox_dir: str,
    *,
    identifier: str,
    run_id: str | None = None,
    delete_after_upload: bool = True,
) -> list[str]:
    """
    Walk sandbox_dir and offload any file >= 1MB to S3.
    Returns list of S3 URIs for successfully uploaded files.
    Never raises.
    """
    uploaded: list[str] = []
    try:
        base = Path(sandbox_dir)
        if not base.is_dir():
            return uploaded
        for p in base.rglob("*"):
            if p.is_file():
                uri = offload_if_large(
                    str(p),
                    identifier=identifier,
                    run_id=run_id,
                    delete_after_upload=delete_after_upload,
                )
                if uri:
                    uploaded.append(uri)
    except Exception:  # noqa: BLE001
        pass
    return uploaded

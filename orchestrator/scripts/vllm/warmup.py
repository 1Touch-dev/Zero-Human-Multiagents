#!/usr/bin/env python3
import json
import os
import sys
import urllib.error
import urllib.request


def main() -> int:
    base_url = os.environ.get("VLLM_BASE_URL", "http://127.0.0.1:8000/v1").rstrip("/")
    model = os.environ.get("VLLM_WARMUP_MODEL", "").strip()
    if not model:
        model = os.environ.get("VLLM_MODEL", "").strip()
    if not model:
        print("VLLM_WARMUP_MODEL or VLLM_MODEL must be set", file=sys.stderr)
        return 2

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "temperature": 0,
        "stream": False,
    }
    req = urllib.request.Request(
        url=f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as res:
            body = res.read().decode("utf-8", errors="replace")
            print(f"vLLM warmup OK: status={res.status}, bytes={len(body)}")
            return 0
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        print(f"vLLM warmup failed: status={err.code} body={body}", file=sys.stderr)
        return 1
    except Exception as err:  # noqa: BLE001 - CLI utility
        print(f"vLLM warmup failed: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


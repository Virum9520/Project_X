#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.27", "boto3>=1.35"]
# ///
"""Smoke-test a deployed Skill Garden environment (Vercel + Railway + R2).

    uv run scripts/smoke.py --api https://api.example.com \\
        --web https://skill-garden-web.vercel.app --admin https://skill-garden-admin.vercel.app

Each URL is optional (also read from SMOKE_API_URL / SMOKE_WEB_URL / SMOKE_ADMIN_URL), so you can
check one tier at a time. `--r2` round-trips an object through the bucket using the S3_* variables
from the environment. `--commit SHA` asserts every tier is serving that commit. Exits non-zero if
any check fails.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from collections.abc import Callable
from typing import Any

import httpx

TIMEOUT = httpx.Timeout(15.0)
failures: list[str] = []


def check(name: str, fn: Callable[[], str | None]) -> None:
    started = time.perf_counter()
    try:
        detail = fn() or ""
    except Exception as exc:
        failures.append(name)
        print(f"FAIL {name}: {exc}")
        return
    print(f"OK   {name} ({(time.perf_counter() - started) * 1000:.0f} ms) {detail}".rstrip())


def get_json(client: httpx.Client, url: str, expect: int = 200) -> dict[str, Any]:
    response = client.get(url)
    if response.status_code != expect:
        raise AssertionError(f"GET {url} -> {response.status_code}: {response.text[:300]}")
    data: dict[str, Any] = response.json()
    return data


def assert_commit(body: dict[str, Any], commit: str | None) -> None:
    served = body.get("commit")
    if commit and served and not str(served).startswith(commit):
        raise AssertionError(f"serving commit {served}, expected {commit}")


def smoke_api(client: httpx.Client, api: str, web: str | None, commit: str | None) -> None:
    def healthz() -> str:
        body = get_json(client, f"{api}/healthz")
        assert body["status"] == "ok", body
        assert_commit(body, commit)
        return f"env={body['environment']} commit={(body.get('commit') or '?')[:8]}"

    def readyz() -> str:
        body = get_json(client, f"{api}/readyz")
        assert body["status"] == "ready", body
        return " ".join(f"{k}={'up' if v else 'DOWN'}" for k, v in body["checks"].items())

    def request_id() -> str:
        response = client.get(f"{api}/healthz")
        assert "x-request-id" in response.headers, "missing X-Request-ID"
        return ""

    check("api /healthz", healthz)
    check("api /readyz", readyz)
    check("api X-Request-ID header", request_id)

    if web:

        def cors() -> str:
            response = client.options(
                f"{api}/healthz",
                headers={"Origin": web, "Access-Control-Request-Method": "GET"},
            )
            allowed = response.headers.get("access-control-allow-origin")
            assert allowed == web, f"preflight from {web} not allowed (got {allowed!r})"
            return ""

        check("api CORS allows web origin", cors)


def smoke_next(
    client: httpx.Client, name: str, base: str, api: str | None, commit: str | None
) -> None:
    def healthz() -> str:
        body = get_json(client, f"{base}/healthz")
        assert body["status"] == "ok", body
        assert_commit(body, commit)
        if api and body.get("apiUrl") and body["apiUrl"].rstrip("/") != api:
            raise AssertionError(f"API_URL is {body['apiUrl']}, expected {api}")
        return f"env={body['environment']} apiUrl={body.get('apiUrl')}"

    def home() -> str:
        response = client.get(base)
        # A redirect to sign-in (admin, protected pages) is healthy too.
        assert response.status_code in (200, 307, 308), f"GET / -> {response.status_code}"
        return f"status={response.status_code}"

    check(f"{name} /healthz", healthz)
    check(f"{name} /", home)


def smoke_r2() -> None:
    import boto3
    from botocore.config import Config

    def roundtrip() -> str:
        bucket = os.environ["S3_BUCKET"]
        s3 = boto3.client(
            "s3",
            endpoint_url=os.environ["S3_ENDPOINT_URL"],
            aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
            region_name=os.environ.get("S3_REGION", "auto"),
            config=Config(signature_version="s3v4"),
        )
        key = f"_smoke/{uuid.uuid4().hex}.txt"
        payload = b"skill-garden smoke"
        s3.put_object(Bucket=bucket, Key=key, Body=payload)
        try:
            assert s3.get_object(Bucket=bucket, Key=key)["Body"].read() == payload
            url = s3.generate_presigned_url(
                "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=60
            )
            assert httpx.get(url, timeout=TIMEOUT).content == payload, "presigned GET mismatch"
        finally:
            s3.delete_object(Bucket=bucket, Key=key)
        return f"bucket={bucket}"

    check("r2 put/get/presign/delete", roundtrip)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--api", default=os.environ.get("SMOKE_API_URL"))
    parser.add_argument("--web", default=os.environ.get("SMOKE_WEB_URL"))
    parser.add_argument("--admin", default=os.environ.get("SMOKE_ADMIN_URL"))
    parser.add_argument("--commit", help="expected git SHA (prefix ok) on every tier")
    parser.add_argument("--r2", action="store_true", help="round-trip an object through R2")
    args = parser.parse_args()

    api, web, admin = (u.rstrip("/") if u else None for u in (args.api, args.web, args.admin))
    if not (api or web or admin or args.r2):
        parser.error("nothing to check: pass --api, --web, --admin and/or --r2")

    with httpx.Client(timeout=TIMEOUT, follow_redirects=False) as client:
        if api:
            smoke_api(client, api, web, args.commit)
        if web:
            smoke_next(client, "web", web, api, args.commit)
        if admin:
            smoke_next(client, "admin", admin, api, args.commit)
    if args.r2:
        smoke_r2()

    if failures:
        print(f"\n{len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""AWS STS / credential helpers (`aws.ts`)."""

from __future__ import annotations

from typing import Any, TypedDict, cast


class AwsCredentials(TypedDict, total=False):
    AccessKeyId: str
    SecretAccessKey: str
    SessionToken: str
    Expiration: str


class AwsStsOutput(TypedDict):
    Credentials: AwsCredentials


def is_aws_credentials_provider_error(err: BaseException | None) -> bool:
    return getattr(err, "name", None) == "CredentialsProviderError"


def is_valid_aws_sts_output(obj: object) -> bool:
    if not isinstance(obj, dict):
        return False
    creds = obj.get("Credentials")
    if not isinstance(creds, dict):
        return False
    ak = creds.get("AccessKeyId")
    sk = creds.get("SecretAccessKey")
    st = creds.get("SessionToken")
    return (
        isinstance(ak, str)
        and isinstance(sk, str)
        and isinstance(st, str)
        and len(ak) > 0
        and len(sk) > 0
        and len(st) > 0
    )


async def check_sts_caller_identity() -> None:
    """Verify AWS identity via STS (stub: import boto3 in production)."""
    try:
        from boto3 import client  # type: ignore[import-not-found]

        client("sts").get_caller_identity()
    except ImportError as e:
        raise RuntimeError("boto3 required for STS") from e


async def clear_aws_ini_cache() -> None:
    from hare.utils.debug import log_for_debugging

    try:
        log_for_debugging("Clearing AWS credential provider cache")
        from botocore.credentials import create_credential_resolver  # type: ignore[import-not-found]
    except Exception:
        log_for_debugging(
            "Failed to clear AWS credential cache (expected if boto not configured)",
        )

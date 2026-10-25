"""Bound SQL API shapes, key-pair JWT, async polling; no caller SQL interface."""

import asyncio
import base64
import hashlib
import json
import re
import time
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx

SQL = Path(__file__).parent / "sql"


class VendorUnavailable(Exception):
    def __init__(self, reason="unavailable"):
        self.reason = reason
        super().__init__(reason)


def _b64(value):
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def keypair_jwt(config):
    # cryptography is already pinned in requirements.lock through google-auth.
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    password = Path(config.passphrase_file).read_bytes().strip() if config.passphrase_file else None
    key = serialization.load_pem_private_key(Path(config.private_key_file).read_bytes(), password=password)
    public = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(public).digest()).decode()
    account = config.account.split(".")[0].upper()
    subject = account + "." + config.user.upper()
    stamp = int(time.time())
    header = _b64(b'{"alg":"RS256","typ":"JWT"}')
    payload = _b64(
        json.dumps(
            {"iss": subject + "." + fingerprint, "sub": subject, "iat": stamp, "exp": stamp + 300}
        ).encode()
    )
    message = (header + "." + payload).encode()
    signature = key.sign(message, padding.PKCS1v15(), hashes.SHA256())
    return message.decode() + "." + _b64(signature)


class SnowflakeTransport:
    def __init__(self, config, client=None, token_factory=keypair_jwt):
        self.config = config
        self.client = client or httpx.AsyncClient(timeout=4, follow_redirects=False)
        self.token_factory = token_factory

    async def close(self):
        await self.client.aclose()

    async def _request(self, method, url, **kwargs):
        # Bound bytes while reading, rather than buffering arbitrary vendor output
        # before checking its size. Redirects remain disabled on the client.
        async with self.client.stream(method, url, **kwargs) as response:
            content = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=65536):
                if len(content) + len(chunk) > 2_000_000:
                    raise VendorUnavailable("response_too_large")
                content.extend(chunk)
            return httpx.Response(response.status_code, content=bytes(content))

    async def execute(self, shape, values=()):
        if shape not in {"ingest", "query", "explain", "001_setup", "smoke_schema"}:
            raise ValueError("Unapproved SQL shape")
        config = self.config
        body = dict(
            statement=(SQL / (shape + ".sql")).read_text(),
            timeout=8,
            database=config.database,
            schema=config.schema,
            warehouse=config.warehouse,
            role=config.role,
            bindings={str(i): {"type": "TEXT", "value": str(value)} for i, value in enumerate(values, 1)},
        )
        url = f"https://{config.account}.snowflakecomputing.com/api/v2/statements"
        try:
            async with asyncio.timeout(config.deadline):
                headers = {
                    "Authorization": "Bearer " + self.token_factory(config),
                    "X-Snowflake-Authorization-Token-Type": "KEYPAIR_JWT",
                    "User-Agent": "AgentCity/1.0",
                    "Accept": "application/json",
                }
                # Stable ingestion identity also covers a prior SQL statement
                # still completing after an ambiguous HTTP timeout. Cortex is
                # submitted only once per durable operation, with no resubmission.
                params = {"requestId": str(uuid4())}
                if shape == "ingest":
                    identity = json.dumps([config.account, config.database, config.schema, *values[:4]])
                    params = {"requestId": str(uuid5(NAMESPACE_URL, identity)), "retry": "true"}
                response = await self._request("POST", url, params=params, json=body, headers=headers)
                for _ in range(20):
                    if len(response.content) > 2_000_000:
                        raise VendorUnavailable()
                    if response.status_code == 200:
                        result = response.json()
                        if int(result.get("resultSetMetaData", {}).get("numRows", 0)) > 2:
                            raise VendorUnavailable()
                        return result.get("data", [])
                    if response.status_code not in {202, 408}:
                        message = response.json().get("message", "").lower()
                        category = next(
                            (
                                label
                                for term, label in (
                                    ("insufficient privileges", "insufficient_privileges"),
                                    ("does not exist", "object_missing_or_unauthorized"),
                                    ("syntax error", "sql_syntax"),
                                    ("bind", "sql_bind"),
                                    ("jwt", "jwt_auth"),
                                )
                                if term in message
                            ),
                            "vendor_rejected",
                        )
                        raise VendorUnavailable("sql_api_http_" + str(response.status_code) + ":" + category)
                    handle = response.json().get("statementHandle", "")
                    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", handle):
                        raise VendorUnavailable()
                    await asyncio.sleep(0.2)
                    response = await self._request("GET", url + "/" + handle, headers=headers)
                raise VendorUnavailable()
        except (httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError, OSError) as error:
            raise VendorUnavailable() from error

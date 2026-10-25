import hashlib
import hmac
import ipaddress
import secrets
import time

from app.infrastructure.errors import require

COOKIE = "agentcity_session"


def local_peer(host):
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class Security:
    def __init__(self, service):
        self.service = service
        self.config = service.config
        self.login_attempts = {}

    def session_key(self, raw):
        return hmac.new(self.config.session_secret.encode(), raw.encode(), hashlib.sha256).hexdigest()

    def check_origin(self, origin, required=False):
        require(not required or bool(origin), "FORBIDDEN", "Origin header required", 403)
        require(
            not origin or origin in self.config.allowed_origins, "FORBIDDEN", "Origin is not allowed", 403
        )

    def identity(self, connection, unsafe=False, login=False):
        origin = connection.headers.get("origin")
        self.check_origin(
            origin,
            required=self.config.auth_mode == "session"
            and (unsafe or connection.scope["type"] == "websocket"),
        )
        if self.config.auth_mode == "local":
            require(
                local_peer(connection.client.host if connection.client else ""),
                "FORBIDDEN",
                "Local auth accepts loopback connections only",
                403,
            )
            # DNS rebinding cannot supply an arbitrary Host to the local mutation API.
            host = connection.url.hostname
            require(
                host in {"127.0.0.1", "localhost", "::1"},
                "FORBIDDEN",
                "Local auth requires a loopback Host",
                403,
            )
            token = hmac.new(
                bytes.fromhex(self.service.repo.meta["cursor_secret"]), b"local-csrf", hashlib.sha256
            ).hexdigest()
            if unsafe and not login:
                require(
                    hmac.compare_digest(connection.headers.get("x-csrf-token", ""), token),
                    "FORBIDDEN",
                    "CSRF token required",
                    403,
                )
            return "demo_owner", token
        if login:
            return None, None
        raw = connection.cookies.get(COOKIE, "")
        key = self.session_key(raw)
        record = self.service.repo.meta["sessions"].get(key)
        require(
            record is not None and record["expires_at"] > time.time(),
            "UNAUTHENTICATED",
            "Sign in required",
            401,
        )
        if unsafe:
            require(
                hmac.compare_digest(connection.headers.get("x-csrf-token", ""), record["csrf_token"]),
                "FORBIDDEN",
                "CSRF token required",
                403,
            )
        return record["owner_id"], record["csrf_token"]

    def login(self, connection, passphrase):
        require(
            self.config.auth_mode == "session",
            "FEATURE_UNAVAILABLE",
            "Session login is disabled in local mode",
            501,
        )
        peer = connection.client.host if connection.client else "unknown"
        attempts = [stamp for stamp in self.login_attempts.get(peer, []) if stamp > time.monotonic() - 60]
        require(len(attempts) < 5, "RATE_LIMITED", "Too many login attempts", 429)
        attempts.append(time.monotonic())
        self.login_attempts[peer] = attempts
        require(
            hmac.compare_digest(passphrase.encode(), self.config.demo_passphrase.encode()),
            "UNAUTHENTICATED",
            "Incorrect passphrase",
            401,
        )
        raw = secrets.token_urlsafe(48)
        csrf = secrets.token_urlsafe(32)
        record = dict(owner_id="demo_owner", csrf_token=csrf, expires_at=time.time() + 86400)
        return raw, self.session_key(raw), record

    def authorize_stream(self, connection, owner):
        """A successful handshake is not a permanent grant after logout/expiry."""
        current, _ = self.identity(connection)
        require(current == owner, "UNAUTHENTICATED", "Stream session is no longer valid", 401)

"""Run opt-in SQL acceptance on a disposable local TLS PostgreSQL cluster.

Requires PostgreSQL binaries and the locked dev environment. Never connects to an
existing server. Creates only a temporary cluster bound to loopback on a free port.
"""

import argparse
import ipaddress
import os
import secrets
import socket
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bin", type=Path, required=True)
    args = parser.parse_args()
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from psycopg import connect, sql
    from psycopg.conninfo import make_conninfo

    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}

    def binary(name):
        return str(args.bin / (name + (".exe" if os.name == "nt" else "")))

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with TemporaryDirectory(prefix="agentcity-tiger-pg-") as temporary:
        root = Path(temporary)
        cluster = root / "cluster"
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "localhost")])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
            .not_valid_after(datetime.now(UTC) + timedelta(days=1))
            .add_extension(
                x509.SubjectAlternativeName(
                    [
                        x509.DNSName("localhost"),
                        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                    ]
                ),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )
        (root / "server.key").write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
        )
        (root / "server.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        if os.name != "nt":
            (root / "server.key").chmod(0o600)
        subprocess.run(
            [
                binary("initdb"),
                "-D",
                str(cluster),
                "-U",
                "cluster_admin",
                "--auth=trust",
                "--encoding=UTF8",
                "--no-locale",
            ],
            check=True,
            capture_output=True,
            **flags,
        )
        with (cluster / "postgresql.conf").open("a", encoding="utf-8") as output:
            output.write(f"\nlisten_addresses='127.0.0.1'\nport={port}\nssl=on\n")
            output.write(f"ssl_cert_file='{(root / 'server.crt').as_posix()}'\n")
            output.write(f"ssl_key_file='{(root / 'server.key').as_posix()}'\n")
        started = False
        try:
            subprocess.run(
                [binary("pg_ctl"), "-D", str(cluster), "-l", str(root / "postgres.log"), "-w", "start"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **flags,
            )
            started = True
            admin = make_conninfo(
                host="127.0.0.1",
                port=port,
                dbname="postgres",
                user="cluster_admin",
                sslmode="verify-full",
                sslrootcert=str(root / "server.crt"),
            )
            password = secrets.token_hex(24)
            with connect(admin, autocommit=True) as connection:
                connection.execute(
                    sql.SQL("CREATE ROLE tiger_test LOGIN PASSWORD {}").format(sql.Literal(password))
                )
                connection.execute("CREATE DATABASE tiger_acceptance")
                connection.execute("GRANT CREATE, CONNECT ON DATABASE tiger_acceptance TO tiger_test")
            url = make_conninfo(
                host="127.0.0.1",
                port=port,
                dbname="tiger_acceptance",
                user="tiger_test",
                password=password,
                sslmode="verify-full",
                sslrootcert=str(root / "server.crt"),
            )
            with connect(url) as connection:
                assert connection.execute(
                    "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
                ).fetchone() == (False,)
                assert connection.execute(
                    "SELECT pg_get_userbyid(datdba) = current_user FROM pg_database WHERE datname = current_database()"
                ).fetchone() == (False,)
            # Require password authentication after isolated setup.
            (cluster / "pg_hba.conf").write_text(
                "hostssl all tiger_test 127.0.0.1/32 scram-sha-256\n", encoding="utf-8"
            )
            subprocess.run(
                [binary("pg_ctl"), "-D", str(cluster), "reload"], check=True, capture_output=True, **flags
            )
            environment = dict(os.environ, TIGER_TEST_DATABASE_URL=url)
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "tests/test_tiger.py", "-k", "real_postgres", "-rs"],
                env=environment,
                capture_output=True,
                text=True,
                **flags,
            )
            print(result.stdout, end="")
            print(result.stderr, end="", file=sys.stderr)
            return result.returncode
        finally:
            if started:
                subprocess.run(
                    [binary("pg_ctl"), "-D", str(cluster), "-w", "-m", "immediate", "stop"],
                    check=True,
                    capture_output=True,
                    **flags,
                )


if __name__ == "__main__":
    raise SystemExit(main())

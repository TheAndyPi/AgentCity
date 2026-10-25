"""Offline backup/restore. Refuses a live writer and never restores over a store."""

import argparse
import tarfile
from pathlib import Path

from app.data.repository import Repository


def backup(source: Path, destination: Path):
    source, destination = source.resolve(), destination.resolve()
    if not (source / "manifest.json").is_file():
        raise ValueError("Backup source must be an existing DATA_DIR")
    if destination.is_relative_to(source) or destination.exists():
        raise ValueError("Backup destination must be new and outside DATA_DIR")
    repo = Repository(source)
    try:
        if repo.degraded:
            raise ValueError("Source history is degraded; operator recovery required")
        with tarfile.open(destination, "x:gz") as archive:
            for path in sorted(source.rglob("*")):
                if path.is_symlink():
                    raise ValueError("Backup source contains a symbolic link")
                if path.is_file() and path.name != "writer.lock" and not path.name.endswith(".tmp"):
                    archive.add(path, arcname=path.relative_to(source), recursive=False)
    finally:
        repo.close()


def restore(archive: Path, destination: Path):
    destination = destination.resolve()
    if destination.exists():
        raise ValueError("Restore destination must not exist; use a separate directory")
    destination.mkdir(parents=True)
    with tarfile.open(archive, "r:gz") as source:
        source.extractall(destination, filter="data")
    if not (destination / "manifest.json").is_file():
        raise ValueError("Archive has no manifest")
    repo = Repository(destination)
    try:
        if repo.degraded:
            raise ValueError("Restored history failed integrity verification")
        for sid in repo.meta["simulations"]:
            repo.read(sid)
    finally:
        repo.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("backup", "restore"))
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    (backup if args.action == "backup" else restore)(args.source, args.destination)
    print(f"{args.action} verified")


if __name__ == "__main__":
    main()

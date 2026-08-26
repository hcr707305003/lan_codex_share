from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    archives = sorted(args.directory.glob("*.zip"))
    if not archives:
        parser.error("no zip archives found")
    output = args.directory / "SHA256SUMS.txt"
    output.write_text("".join(f"{sha256(path)}  {path.name}\n" for path in archives), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

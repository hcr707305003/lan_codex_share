from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from lan_codex_share import __version__


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tag")
    args = parser.parse_args()
    tag_version = args.tag.removeprefix("v")
    if tag_version != __version__:
        parser.error(f"tag {args.tag} does not match package version {__version__}")
    print(__version__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TAG_PATTERN = re.compile(r"v\d+\.\d+\.\d+")
FUNCTION_SECTIONS = {
    "新增功能",
    "功能修复",
    "行为或兼容性变化",
    "升级提示",
}


def validate_release_notes(project_root: Path, tag: str) -> Path:
    if TAG_PATTERN.fullmatch(tag) is None:
        raise ValueError(f"tag {tag!r} must use vX.Y.Z format")

    notes_path = project_root / "docs" / "releases" / f"{tag}.md"
    if not notes_path.is_file():
        raise ValueError(f"missing release notes: {notes_path}")

    lines = notes_path.read_text(encoding="utf-8").splitlines()
    first_content = next((line.strip() for line in lines if line.strip()), "")
    expected_title = f"# {tag}"
    if first_content != expected_title:
        raise ValueError(f"release notes must start with {expected_title!r}")

    current_section: str | None = None
    has_function_change = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            current_section = stripped[3:].strip()
            continue
        if (
            current_section in FUNCTION_SECTIONS
            and stripped
            and not stripped.startswith("#")
            and not stripped.startswith("<!--")
            and stripped not in {"-", "*"}
        ):
            has_function_change = True

    if not has_function_change:
        sections = "、".join(sorted(FUNCTION_SECTIONS))
        raise ValueError(f"release notes need content under one of: {sections}")

    return notes_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tag")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()

    try:
        notes_path = validate_release_notes(args.project_root.resolve(), args.tag)
    except ValueError as exc:
        print(f"release notes validation failed: {exc}", file=sys.stderr)
        return 2

    print(notes_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

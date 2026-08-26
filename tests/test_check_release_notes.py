from pathlib import Path

import pytest

from scripts.check_release_notes import validate_release_notes


def write_notes(project_root: Path, tag: str, content: str) -> Path:
    notes_path = project_root / "docs" / "releases" / f"{tag}.md"
    notes_path.parent.mkdir(parents=True)
    notes_path.write_text(content, encoding="utf-8")
    return notes_path


def test_accepts_functional_release_notes(tmp_path: Path) -> None:
    notes_path = write_notes(
        tmp_path,
        "v1.2.3",
        "# v1.2.3\n\n## 功能修复\n\n- 修复会话切换失败。\n",
    )

    assert validate_release_notes(tmp_path, "v1.2.3") == notes_path


def test_rejects_missing_release_notes(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="missing release notes"):
        validate_release_notes(tmp_path, "v1.2.3")


def test_rejects_title_that_does_not_match_tag(tmp_path: Path) -> None:
    write_notes(
        tmp_path,
        "v1.2.3",
        "# v1.2.2\n\n## 新增功能\n\n- 新增功能。\n",
    )

    with pytest.raises(ValueError, match="must start"):
        validate_release_notes(tmp_path, "v1.2.3")


def test_rejects_notes_without_function_changes(tmp_path: Path) -> None:
    write_notes(
        tmp_path,
        "v1.2.3",
        "# v1.2.3\n\n## 内部维护\n\n- 更新测试。\n",
    )

    with pytest.raises(ValueError, match="need content"):
        validate_release_notes(tmp_path, "v1.2.3")


def test_rejects_empty_function_section(tmp_path: Path) -> None:
    write_notes(
        tmp_path,
        "v1.2.3",
        "# v1.2.3\n\n## 新增功能\n\n<!-- 在这里填写 -->\n",
    )

    with pytest.raises(ValueError, match="need content"):
        validate_release_notes(tmp_path, "v1.2.3")


def test_rejects_non_semantic_version_tag(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="vX.Y.Z"):
        validate_release_notes(tmp_path, "release-1")

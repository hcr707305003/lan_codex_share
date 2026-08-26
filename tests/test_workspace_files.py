import os

import pytest

from lan_codex_share.workspace_files import WorkspaceFileError, WorkspaceFileViewer


def test_reads_markdown_and_code_inside_workspace(tmp_path):
    markdown = tmp_path / "design.md"
    code = tmp_path / "app.php"
    markdown.write_text("# 设计", encoding="utf-8")
    code.write_text("<?php\necho 'ok';", encoding="utf-8")
    viewer = WorkspaceFileViewer(tmp_path)

    md_preview = viewer.open(str(markdown))
    code_preview = viewer.open(str(code))

    assert md_preview.kind == "markdown"
    assert md_preview.content == "# 设计"
    assert code_preview.kind == "code"
    assert code_preview.relative_path == "app.php"


def test_rejects_outside_missing_directory_and_unknown_binary(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    directory = workspace / "folder"
    directory.mkdir()
    binary = workspace / "archive.zip"
    binary.write_bytes(b"PK")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    viewer = WorkspaceFileViewer(workspace)

    for path, status in ((outside, 403), (workspace / "missing.txt", 404), (directory, 400), (binary, 415)):
        with pytest.raises(WorkspaceFileError) as caught:
            viewer.open(str(path))
        assert caught.value.status == status


def test_enforces_size_limits_and_marks_invalid_utf8(tmp_path):
    large = tmp_path / "large.txt"
    large.write_bytes(b"x" * 5)
    invalid = tmp_path / "invalid.txt"
    invalid.write_bytes(b"ok\xff")
    viewer = WorkspaceFileViewer(tmp_path, max_text_bytes=4)

    with pytest.raises(WorkspaceFileError) as caught:
        viewer.open(str(large))
    assert caught.value.status == 413

    preview = WorkspaceFileViewer(tmp_path).open(str(invalid))
    assert preview.encoding_warning
    assert "\ufffd" in preview.content


def test_recognizes_inline_image_and_pdf(tmp_path):
    image = tmp_path / "diagram.png"
    pdf = tmp_path / "spec.pdf"
    image.write_bytes(b"png")
    pdf.write_bytes(b"pdf")
    viewer = WorkspaceFileViewer(tmp_path)

    assert viewer.open(str(image)).mime == "image/png"
    assert viewer.open(str(pdf)).kind == "pdf"


def test_link_target_requires_explicit_preview_root(tmp_path):
    workspace = tmp_path / "workspace"
    target = tmp_path / "mounted-project"
    workspace.mkdir()
    target.mkdir()
    document = target / "design.md"
    document.write_text("# Mounted", encoding="utf-8")
    mounted = workspace / "project"
    try:
        os.symlink(target, mounted, target_is_directory=True)
    except OSError:
        pytest.skip("当前 Windows 环境不允许创建目录链接")

    with pytest.raises(WorkspaceFileError) as caught:
        WorkspaceFileViewer(workspace).open(str(mounted / "design.md"))
    assert caught.value.status == 403

    preview = WorkspaceFileViewer(workspace, preview_roots=[target]).open(str(document))

    assert preview.content == "# Mounted"
    assert preview.relative_path == "mounted-project/design.md"


def test_allows_explicit_preview_root_but_not_similar_prefix(tmp_path):
    workspace = tmp_path / "workspace"
    project = tmp_path / "project-a"
    lookalike = tmp_path / "project-a-private"
    workspace.mkdir()
    project.mkdir()
    lookalike.mkdir()
    allowed = project / "design.md"
    denied = lookalike / "secret.md"
    allowed.write_text("# Allowed", encoding="utf-8")
    denied.write_text("# Denied", encoding="utf-8")
    viewer = WorkspaceFileViewer(workspace, preview_roots=[project])

    assert viewer.open(str(allowed)).relative_path == "project-a/design.md"
    with pytest.raises(WorkspaceFileError) as caught:
        viewer.open(str(denied))
    assert caught.value.status == 403

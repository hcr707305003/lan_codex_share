from pathlib import Path
import shutil
import subprocess

import pytest


def test_markdown_renderer():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for browser renderer tests")
    script = Path(__file__).parent / "javascript" / "markdown.test.cjs"
    result = subprocess.run(
        [node, "--test", str(script)], capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr

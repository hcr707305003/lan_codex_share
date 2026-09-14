from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize("filename", ["markdown.test.cjs", "proxy-client.test.cjs"])
def test_markdown_renderer(filename):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for browser renderer tests")
    script = Path(__file__).parent / "javascript" / filename
    result = subprocess.run(
        [node, "--test", str(script)], capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr

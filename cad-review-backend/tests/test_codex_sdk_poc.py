from pathlib import Path


def test_codex_sdk_poc_script_exists():
    assert Path("/Users/harry/@dev/ccad/codex-bridge/src/poc.ts").exists()

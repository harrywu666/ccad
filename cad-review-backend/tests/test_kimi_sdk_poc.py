from pathlib import Path


def test_kimi_sdk_poc_script_exists():
    script = Path("/Users/harry/@dev/ccad/cad-review-backend/scripts/kimi_sdk_poc.py")
    assert script.exists()

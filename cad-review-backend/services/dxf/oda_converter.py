"""ODA File Converter 封装（DWG -> DXF）。"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


def get_oda_path() -> str:
    """获取 ODA File Converter 可执行路径。

    支持环境变量 ODA_FILE_CONVERTER_PATH 覆盖。
    """
    env_path = os.getenv("ODA_FILE_CONVERTER_PATH", "").strip()
    if env_path:
        candidate = Path(env_path).expanduser()
        if candidate.exists():
            return str(candidate)

    if platform.system() == "Darwin":
        default = Path("/Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter")
    elif platform.system() == "Windows":
        default = Path(r"C:\Program Files\ODA\ODAFileConverter\ODAFileConverter.exe")
    else:
        default = Path("/usr/bin/ODAFileConverter")

    if default.exists():
        return str(default)

    raise RuntimeError("请先安装ODA File Converter")


def dwg_batch_to_dxf(input_dir: str, output_dir: str) -> List[str]:
    """批量将 input_dir 中 DWG 转为 DXF，返回 DXF 路径列表。"""
    in_dir = Path(input_dir).expanduser().resolve()
    out_dir = Path(output_dir).expanduser().resolve()
    in_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    oda = get_oda_path()
    cmd = [oda, str(in_dir), str(out_dir), "ACAD2018", "DXF", "0", "1"]
    logger.info("执行ODA转换: %s", " ".join(cmd))

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        raise RuntimeError(f"ODA转换失败: rc={proc.returncode}, stderr={stderr[:500]}, stdout={stdout[:500]}")

    dxf_files = sorted(
        [
            str(path.resolve())
            for path in out_dir.iterdir()
            if path.is_file() and path.suffix.lower() == ".dxf"
        ]
    )
    return dxf_files


def dwg_to_dxf(dwg_path: str, output_dir: str) -> str:
    """单文件DWG转DXF。"""
    src = Path(dwg_path).expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(f"DWG文件不存在: {src}")

    out_dir = Path(output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="dwg_one_in_") as in_dir:
        copied = Path(in_dir) / src.name
        shutil.copy2(src, copied)
        dxfs = dwg_batch_to_dxf(in_dir, str(out_dir))

    stem = src.stem.lower()
    for dxf in dxfs:
        if Path(dxf).stem.lower() == stem:
            return dxf

    if not dxfs:
        raise RuntimeError("ODA转换完成但未找到DXF输出")

    return dxfs[0]

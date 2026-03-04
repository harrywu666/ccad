"""
AutoCAD COM 自动化服务（Windows）
用于后台批量打开DWG并调用LISP插件导出布局JSON。
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Iterable, List, Optional

logger = logging.getLogger(__name__)


POPUP_TITLE_KEYWORDS = [
    "missing shx",
    "missing font",
    "font",
    "字体",
    "找不到",
    "缺少",
    "未找到",
    "proxy information",
    "代理信息",
]


def _win_path(path: str) -> str:
    return str(Path(path).resolve()).replace("\\", "/")


class _PopupSuppressor:
    """关闭AutoCAD相关阻塞对话框（字体/代理提示）"""

    def __init__(self, process_id: int):
        self.process_id = process_id
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        try:
            import win32con
            import win32gui
            import win32process
        except Exception as exc:  # noqa: BLE001
            logger.warning("弹窗抑制器不可用（缺少pywin32）: %s", str(exc))
            return

        def enum_handler(hwnd, _ctx):  # noqa: ANN001
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid != self.process_id:
                    return
                if win32gui.GetClassName(hwnd) != "#32770":
                    return
                title = (win32gui.GetWindowText(hwnd) or "").strip().lower()
                if any(key in title for key in POPUP_TITLE_KEYWORDS):
                    logger.warning("检测到阻塞弹窗，自动关闭: %s", title)
                    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            except Exception:
                return

        while not self._stop.is_set():
            try:
                win32gui.EnumWindows(enum_handler, None)
            except Exception:
                pass
            self._stop.wait(0.5)


def _set_runtime_vars(doc) -> None:  # noqa: ANN001
    """
    设置运行时变量，尽量减少交互弹窗与阻塞
    """
    pairs = [
        ("FILEDIA", 0),
        ("CMDDIA", 0),
        ("PROXYNOTICE", 0),
        ("XLOADCTL", 0),
        ("FONTALT", "txt.shx"),
        ("BACKGROUNDPLOT", 0),
    ]
    for key, value in pairs:
        try:
            doc.SetVariable(key, value)
        except Exception:
            continue


def _wait_until_done(doc, done_flag: Path, timeout_sec: int = 300) -> None:  # noqa: ANN001
    import pythoncom

    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        pythoncom.PumpWaitingMessages()

        done = done_flag.exists()
        cmda = 0
        try:
            cmda = int(doc.GetVariable("CMDACTIVE"))
        except Exception:
            cmda = 0

        if done and cmda == 0:
            return
        time.sleep(0.25)

    raise TimeoutError(f"等待AutoCAD导出超时: {str(done_flag)}")


def _load_plugin_and_export(doc, lsp_path: str, output_dir: str, done_flag: str) -> None:  # noqa: ANN001
    # SendCommand是异步命令队列，命令末尾必须带换行
    doc.SendCommand(f'(load "{_win_path(lsp_path)}")\n')
    doc.SendCommand(
        f'(ccad:export-layout-json "{_win_path(output_dir)}" "{_win_path(done_flag)}")\n'
    )


def get_default_lsp_path() -> str:
    base = Path(__file__).resolve().parents[1]
    return str(base / "cad_plugins" / "extract_layout_json.lsp")


def extract_multiple_dwgs_with_com(
    dwg_paths: Iterable[str],
    output_dir: str,
    lsp_path: Optional[str] = None,
    timeout_per_file_sec: int = 360,
) -> None:
    """
    批量提取DWG布局JSON（一个AutoCAD进程处理多个DWG）
    """
    import pythoncom
    import win32com.client
    import win32process
    import win32gui

    paths = [str(Path(p).resolve()) for p in dwg_paths]
    if not paths:
        return

    lsp = lsp_path or get_default_lsp_path()
    if not Path(lsp).exists():
        raise FileNotFoundError(f"LISP插件不存在: {lsp}")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pythoncom.CoInitialize()
    app = None
    suppressor = None
    bootstrap_doc = None
    try:
        app = win32com.client.Dispatch("AutoCAD.Application")
        app.Visible = False
        app.WindowState = 1  # 最小化，减少干扰

        try:
            hwnd = int(app.HWND)
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            suppressor = _PopupSuppressor(pid)
            suppressor.start()
        except Exception as exc:  # noqa: BLE001
            logger.warning("无法启动弹窗抑制器: %s", str(exc))

        # 先建一个空文档设置全局变量，降低后续打开DWG时的弹窗概率
        bootstrap_doc = app.Documents.Add()
        _set_runtime_vars(bootstrap_doc)

        for dwg_path in paths:
            dwg = Path(dwg_path)
            done_flag = out_dir / f"{dwg.stem}.__done__.flag"
            if done_flag.exists():
                done_flag.unlink(missing_ok=True)

            logger.info("COM开始处理DWG: %s", str(dwg))
            doc = app.Documents.Open(str(dwg), True)  # ReadOnly
            try:
                _set_runtime_vars(doc)
                _load_plugin_and_export(
                    doc=doc,
                    lsp_path=lsp,
                    output_dir=str(out_dir),
                    done_flag=str(done_flag),
                )
                _wait_until_done(doc=doc, done_flag=done_flag, timeout_sec=timeout_per_file_sec)
                logger.info("COM处理完成: %s", str(dwg))
            finally:
                try:
                    doc.Close(False)
                except Exception:
                    pass

        if bootstrap_doc is not None:
            try:
                bootstrap_doc.Close(False)
            except Exception:
                pass

    finally:
        if suppressor:
            suppressor.stop()
        if app is not None:
            try:
                app.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()

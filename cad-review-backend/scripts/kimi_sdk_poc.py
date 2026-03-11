from __future__ import annotations

import asyncio
import sys
from pathlib import Path


def _print(tag: str, value: str | None = None) -> None:
    if value is None:
        print(tag, flush=True)
        return
    print(f"{tag}: {value}", flush=True)


async def main() -> int:
    # Reuse local .env loading behavior so the script matches app runtime.
    try:
        backend_root = Path(__file__).resolve().parents[1]
        if str(backend_root) not in sys.path:
            sys.path.insert(0, str(backend_root))
        import main as app_main  # noqa: F401
    except Exception as exc:  # pragma: no cover - best effort only
        _print("env_bootstrap_failed", str(exc))

    try:
        from kaos.path import KaosPath
        from kimi_agent_sdk import ApprovalRequest, Session, TextPart, ThinkPart
    except Exception as exc:
        _print("import_failed", str(exc))
        return 2

    work_dir = KaosPath.unsafe_from_local_path(Path.cwd())
    _print("work_dir", str(Path.cwd()))

    try:
        async with await Session.create(work_dir=work_dir, yolo=True) as session:
            _print("session_created", getattr(session, "id", "<unknown>"))
            got_text = False
            got_think = False
            approvals = 0
            async for msg in session.prompt("请只回复 ok", merge_wire_messages=True):
                match msg:
                    case ThinkPart(think=think):
                        got_think = True
                        _print("received_think", think[:80].replace("\n", " "))
                    case TextPart(text=text):
                        got_text = True
                        _print("received_text", text[:80].replace("\n", " "))
                    case ApprovalRequest() as req:
                        approvals += 1
                        _print("approval_requested", getattr(req, "action", "unknown"))
                        req.resolve("approve")
            _print("approval_count", str(approvals))
            _print("poc_status", "ok" if got_text or got_think else "no_output")
            return 0
    except Exception as exc:
        _print("failed_reason", f"{type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

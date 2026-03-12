"""误报反馈会话路由。"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from database import SessionLocal, get_db
from models import (
    AuditResult,
    AuditRunEvent,
    FeedbackLearningRecord,
    FeedbackMessage,
    FeedbackMessageAttachment,
    FeedbackThread,
    Project,
    generate_uuid,
)
from services.feedback_agent_service import (
    decide_feedback_thread,
    query_similar_feedback_cases,
)
from services.feedback_learning_gate import evaluate_learning_gate
from services.feedback_runtime_service import sync_feedback_sample_from_learning_record
from services.storage_path_service import resolve_project_dir
from services.audit_runtime.result_view import group_results_for_view, serialize_audit_result


router = APIRouter()
_IMAGE_ONLY_MESSAGE_FALLBACK = "（用户上传了图片，请结合图片判断）"


class FeedbackThreadCreateRequest(BaseModel):
    message: str


class FeedbackThreadMessageCreateRequest(BaseModel):
    content: str


class FeedbackThreadBatchQueryRequest(BaseModel):
    audit_result_ids: List[str]
    audit_version: Optional[int] = None


class FeedbackMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    class AttachmentResponse(BaseModel):
        model_config = ConfigDict(from_attributes=True)

        id: str
        file_name: str
        mime_type: str
        file_size: int
        file_url: str
        created_at: Optional[datetime] = None

    id: str
    thread_id: str
    role: str
    message_type: str
    content: str
    structured_json: Optional[str] = None
    created_at: Optional[datetime] = None
    attachments: List[AttachmentResponse] = []


class FeedbackThreadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    audit_result_id: str
    result_group_id: Optional[str] = None
    audit_version: int
    status: str
    learning_decision: str
    agent_decision: Optional[str] = None
    agent_confidence: Optional[float] = None
    opened_by: Optional[str] = None
    source_agent: Optional[str] = None
    rule_id: Optional[str] = None
    issue_type: Optional[str] = None
    summary: Optional[str] = None
    resolution_reason: Optional[str] = None
    escalation_reason: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    messages: List[FeedbackMessageResponse]


def _get_project(db: Session, project_id: str) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


def _get_audit_result(db: Session, project_id: str, result_id: str) -> AuditResult:
    result = (
        db.query(AuditResult)
        .filter(AuditResult.project_id == project_id, AuditResult.id == result_id)
        .first()
    )
    if not result:
        raise HTTPException(status_code=404, detail="审核结果不存在")
    return result


def _get_thread(db: Session, project_id: str, thread_id: str) -> FeedbackThread:
    thread = (
        db.query(FeedbackThread)
        .filter(FeedbackThread.project_id == project_id, FeedbackThread.id == thread_id)
        .first()
    )
    if not thread:
        raise HTTPException(status_code=404, detail="反馈会话不存在")
    return thread


def _serialize_thread(thread: FeedbackThread) -> FeedbackThreadResponse:
    messages = sorted(thread.messages, key=lambda item: (item.created_at or datetime.min, item.id))
    return FeedbackThreadResponse(
        id=thread.id,
        project_id=thread.project_id,
        audit_result_id=thread.audit_result_id,
        result_group_id=thread.result_group_id,
        audit_version=thread.audit_version,
        status=thread.status,
        learning_decision=thread.learning_decision,
        agent_decision=thread.agent_decision,
        agent_confidence=thread.agent_confidence,
        opened_by=thread.opened_by,
        source_agent=thread.source_agent,
        rule_id=thread.rule_id,
        issue_type=thread.issue_type,
        summary=thread.summary,
        resolution_reason=thread.resolution_reason,
        escalation_reason=thread.escalation_reason,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
        closed_at=thread.closed_at,
        messages=[_serialize_message(thread.project_id, message) for message in messages],
    )


def _feedback_attachment_file_url(project_id: str, attachment_id: str) -> str:
    return f"/api/projects/{project_id}/feedback-attachments/{attachment_id}/file"


def _serialize_message(project_id: str, message: FeedbackMessage) -> FeedbackMessageResponse:
    attachments = sorted(
        list(getattr(message, "attachments", []) or []),
        key=lambda item: (item.created_at or datetime.min, item.id),
    )
    return FeedbackMessageResponse(
        id=message.id,
        thread_id=message.thread_id,
        role=message.role,
        message_type=message.message_type,
        content=message.content,
        structured_json=message.structured_json,
        created_at=message.created_at,
        attachments=[
            FeedbackMessageResponse.AttachmentResponse(
                id=item.id,
                file_name=item.file_name,
                mime_type=item.mime_type,
                file_size=int(item.file_size or 0),
                file_url=_feedback_attachment_file_url(project_id, item.id),
                created_at=item.created_at,
            )
            for item in attachments
        ],
    )


def _append_thread_event(
    db: Session,
    *,
    project_id: str,
    audit_version: int,
    event_kind: str,
    message: str,
    meta: Optional[dict] = None,
) -> None:
    db.add(
        AuditRunEvent(
            project_id=project_id,
            audit_version=audit_version,
            level="info",
            step_key="feedback_thread",
            agent_key="feedback_agent",
            agent_name="误报反馈Agent",
            event_kind=event_kind,
            message=message,
            meta_json=None if meta is None else json.dumps(meta, ensure_ascii=False),
        )
    )


def _build_recent_messages(db: Session, thread_id: str) -> List[dict]:
    messages = (
        db.query(FeedbackMessage)
        .filter(FeedbackMessage.thread_id == thread_id)
        .order_by(FeedbackMessage.created_at.asc(), FeedbackMessage.id.asc())
        .all()
    )
    return [
        {
            "id": item.id,
            "role": item.role,
            "message_type": item.message_type,
            "content": item.content,
            "attachments": [
                {
                    "id": attachment.id,
                    "file_name": attachment.file_name,
                    "mime_type": attachment.mime_type,
                    "file_size": int(attachment.file_size or 0),
                }
                for attachment in sorted(
                    list(getattr(item, "attachments", []) or []),
                    key=lambda attachment: (attachment.created_at or datetime.min, attachment.id),
                )
            ],
        }
        for item in messages
    ]


def _normalize_feedback_image_bytes(content_type: str | None, data: bytes) -> tuple[str, bytes]:
    header = data[:16]
    detected = None
    if header.startswith(b"\x89PNG"):
        detected = "image/png"
    elif header[:3] == b"\xff\xd8\xff":
        detected = "image/jpeg"
    elif header.startswith(b"GIF8"):
        detected = "image/gif"
    elif header.startswith(b"RIFF") and b"WEBP" in header:
        detected = "image/webp"
    elif header.startswith(b"BM"):
        detected = "image/bmp"
    mime_type = (content_type or "").strip().lower()
    if not detected and not mime_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="只支持上传图片文件")
    return (detected or mime_type or "application/octet-stream"), data


def _sanitize_feedback_file_name(name: str) -> str:
    raw = (name or "").strip() or "image"
    raw = re.sub(r"[\\/:\*\?\"<>\|]+", "_", raw)
    raw = re.sub(r"\s+", "_", raw).strip("._")
    return raw or "image"


async def _parse_feedback_request_payload(
    request: Request,
    *,
    primary_text_key: str,
) -> tuple[str, list[UploadFile]]:
    content_type = (request.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        payload = await request.json()
        text_value = str((payload or {}).get(primary_text_key) or "").strip()
        return text_value, []

    form = await request.form()
    text_value = str(form.get(primary_text_key) or "").strip()
    images: list[UploadFile] = []
    for key, value in form.multi_items():
        if key != "images":
            continue
        if getattr(value, "filename", None) is not None and hasattr(value, "read"):
            images.append(value)
    return text_value, images


async def _store_feedback_message_attachments(
    db: Session,
    *,
    project: Project,
    thread: FeedbackThread,
    message: FeedbackMessage,
    uploads: list[UploadFile],
) -> None:
    if len(uploads) > 3:
        raise HTTPException(status_code=400, detail="最多只能上传 3 张图片")
    if not uploads:
        return

    project_dir = resolve_project_dir(project, ensure=True)
    attachment_dir = project_dir / "feedback_threads" / thread.id / "messages" / message.id
    attachment_dir.mkdir(parents=True, exist_ok=True)

    for upload in uploads:
        if not upload.filename:
            continue
        raw_bytes = await upload.read()
        mime_type, normalized_bytes = _normalize_feedback_image_bytes(upload.content_type, raw_bytes)
        file_name = _sanitize_feedback_file_name(upload.filename)
        storage_path = attachment_dir / f"{generate_uuid()}__{file_name}"
        storage_path.write_bytes(normalized_bytes)
        db.add(
            FeedbackMessageAttachment(
                project_id=thread.project_id,
                thread_id=thread.id,
                message_id=message.id,
                file_name=file_name,
                mime_type=mime_type,
                file_size=len(normalized_bytes),
                storage_path=str(storage_path),
            )
        )
    db.flush()


def _collect_feedback_image_payloads(db: Session, thread_id: str, *, limit: int = 3) -> list[bytes]:
    attachments = (
        db.query(FeedbackMessageAttachment)
        .filter(FeedbackMessageAttachment.thread_id == thread_id)
        .order_by(FeedbackMessageAttachment.created_at.desc(), FeedbackMessageAttachment.id.desc())
        .limit(limit)
        .all()
    )
    payloads: list[bytes] = []
    for attachment in attachments:
        try:
            payloads.append(Path(attachment.storage_path).expanduser().read_bytes())
        except Exception:
            continue
    payloads.reverse()
    return payloads


def _stream_env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _format_sse_event(*, event: str, data: dict, event_id: Optional[int] = None) -> str:
    lines: List[str] = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data, ensure_ascii=False)}")
    return "\n".join(lines) + "\n\n"


def _serialize_thread_fresh(db: Session, project_id: str, thread_id: str) -> FeedbackThreadResponse:
    thread = _get_thread(db, project_id, thread_id)
    db.refresh(thread)
    db.expire(thread, ["messages"])
    return _serialize_thread(thread)


def _get_grouped_row(
    db: Session,
    *,
    project_id: str,
    audit_version: int,
    group_id: str,
) -> Optional[dict]:
    raw_rows = (
        db.query(AuditResult)
        .filter(
            AuditResult.project_id == project_id,
            AuditResult.audit_version == audit_version,
        )
        .order_by(AuditResult.created_at.asc())
        .all()
    )
    grouped_rows = group_results_for_view([serialize_audit_result(item) for item in raw_rows])
    for row in grouped_rows:
        if row.get("id") == group_id:
            return row
    return None


def _resolve_result_reference(
    db: Session,
    *,
    project_id: str,
    result_ref: str,
    audit_version: Optional[int],
) -> Tuple[AuditResult, Optional[str]]:
    raw_result = (
        db.query(AuditResult)
        .filter(AuditResult.project_id == project_id, AuditResult.id == result_ref)
        .first()
    )
    if raw_result:
        return raw_result, None

    if audit_version is None:
        raise HTTPException(status_code=404, detail="审核结果不存在")

    grouped_row = _get_grouped_row(
        db,
        project_id=project_id,
        audit_version=audit_version,
        group_id=result_ref,
    )
    if not grouped_row:
        raise HTTPException(status_code=404, detail="审核结果不存在")

    issue_ids = [str(item).strip() for item in grouped_row.get("issue_ids") or [] if str(item).strip()]
    if not issue_ids:
        raise HTTPException(status_code=404, detail="审核结果不存在")

    canonical_result = (
        db.query(AuditResult)
        .filter(
            AuditResult.project_id == project_id,
            AuditResult.audit_version == audit_version,
            AuditResult.id.in_(issue_ids),
        )
        .order_by(AuditResult.created_at.asc(), AuditResult.id.asc())
        .first()
    )
    if not canonical_result:
        raise HTTPException(status_code=404, detail="审核结果不存在")
    return canonical_result, grouped_row.get("id")


def _run_feedback_agent_review(
    db: Session,
    *,
    thread: FeedbackThread,
    audit_result: AuditResult,
) -> FeedbackMessage:
    _append_thread_event(
        db,
        project_id=thread.project_id,
        audit_version=thread.audit_version,
        event_kind="feedback_agent_review_started",
        message="误报反馈Agent 开始判定这条反馈",
        meta={
            "thread_id": thread.id,
            "audit_result_id": thread.audit_result_id,
            "provider_mode": str(os.getenv("FEEDBACK_AGENT_PROVIDER", "api") or "api").strip() or "api",
            "agent_mode": str(os.getenv("FEEDBACK_AGENT_MODE", "llm") or "llm").strip() or "llm",
        },
    )
    similar_cases = query_similar_feedback_cases(
        db,
        rule_id=audit_result.rule_id,
        issue_type=audit_result.type,
    )
    _append_thread_event(
        db,
        project_id=thread.project_id,
        audit_version=thread.audit_version,
        event_kind="feedback_agent_similar_cases",
        message=f"误报反馈Agent 命中 {len(similar_cases)} 条相似案例",
        meta={
            "thread_id": thread.id,
            "audit_result_id": thread.audit_result_id,
            "similar_case_ids": [item["id"] for item in similar_cases],
        },
    )

    decision = decide_feedback_thread(
        thread=thread,
        audit_result=audit_result,
        recent_messages=_build_recent_messages(db, thread.id),
        similar_cases=similar_cases,
        image_payloads=_collect_feedback_image_payloads(db, thread.id),
    )
    thread.status = decision.status
    thread.agent_decision = decision.status
    thread.agent_confidence = decision.confidence
    thread.summary = decision.summary
    thread.learning_decision = decision.suggested_learning_decision
    thread.updated_at = datetime.now()
    if decision.status == "resolved_incorrect":
        thread.resolution_reason = decision.summary
        audit_result.feedback_status = "incorrect"
        audit_result.feedback_at = datetime.now()
        user_messages = [item for item in thread.messages if item.role == "user"]
        audit_result.feedback_note = user_messages[-1].content if user_messages else decision.summary
    elif decision.status == "resolved_not_incorrect":
        thread.resolution_reason = decision.summary
    elif decision.status == "escalated_to_human":
        thread.escalation_reason = decision.summary

    if decision.needs_learning_gate:
        similar_case_count = len(similar_cases)
        reusability_score = 0.85 if similar_case_count >= 2 else (0.72 if similar_case_count == 1 else 0.3)
        gate_input = {
            "agent_status": decision.status,
            "evidence_score": decision.confidence,
            "similar_case_count": similar_case_count,
            "reusability_score": reusability_score,
        }
        _append_thread_event(
            db,
            project_id=thread.project_id,
            audit_version=thread.audit_version,
            event_kind="feedback_learning_gate_started",
            message="误报反馈学习门禁开始评估",
            meta={"thread_id": thread.id, "gate_input": gate_input},
        )
        gate_decision = evaluate_learning_gate(**gate_input)
        thread.learning_decision = gate_decision.learning_decision
        existing_record = (
            db.query(FeedbackLearningRecord)
            .filter(FeedbackLearningRecord.thread_id == thread.id)
            .order_by(FeedbackLearningRecord.created_at.desc(), FeedbackLearningRecord.id.desc())
            .first()
        )
        user_messages = (
            db.query(FeedbackMessage)
            .filter(FeedbackMessage.thread_id == thread.id, FeedbackMessage.role == "user")
            .order_by(FeedbackMessage.created_at.asc(), FeedbackMessage.id.asc())
            .all()
        )
        latest_user_note = user_messages[-1].content if user_messages else None
        learning_record = existing_record or FeedbackLearningRecord(
            thread_id=thread.id,
            project_id=thread.project_id,
            audit_result_id=thread.audit_result_id,
        )
        learning_record.rule_id = audit_result.rule_id
        learning_record.issue_type = audit_result.type
        learning_record.decision = gate_decision.learning_decision
        learning_record.reason_code = gate_decision.reason_code
        learning_record.reason_text = gate_decision.reason_text
        learning_record.evidence_score = gate_decision.evidence_score
        learning_record.similar_case_count = gate_decision.similar_case_count
        learning_record.reusability_score = gate_decision.reusability_score
        learning_record.suggested_intervention_level = "advisory" if similar_case_count == 0 else "soft"
        learning_record.snapshot_json = json.dumps(
            {
                "thread_id": thread.id,
                "agent_status": decision.status,
                "agent_confidence": decision.confidence,
                "gate_decision": gate_decision.model_dump(),
                "similar_case_ids": [item["id"] for item in similar_cases],
            },
            ensure_ascii=False,
        )
        if existing_record is None:
            db.add(learning_record)

        _append_thread_event(
            db,
            project_id=thread.project_id,
            audit_version=thread.audit_version,
            event_kind="feedback_learning_gate_decision",
            message=f"误报反馈学习门禁给出结论：{gate_decision.learning_decision}",
            meta={"thread_id": thread.id, "gate_decision": gate_decision.model_dump()},
        )
        synced_sample = sync_feedback_sample_from_learning_record(
            db,
            learning_record=learning_record,
            audit_result=audit_result,
            user_note=latest_user_note,
        )
        _append_thread_event(
            db,
            project_id=thread.project_id,
            audit_version=thread.audit_version,
            event_kind="feedback_learning_sample_sync",
            message="误报反馈学习样本同步已执行",
            meta={
                "thread_id": thread.id,
                "learning_decision": gate_decision.learning_decision,
                "sample_synced": synced_sample is not None,
            },
        )

    _append_thread_event(
        db,
        project_id=thread.project_id,
        audit_version=thread.audit_version,
        event_kind="feedback_agent_decision",
        message=f"误报反馈Agent 给出结论：{decision.status}",
        meta={
            "thread_id": thread.id,
            "audit_result_id": thread.audit_result_id,
            "decision": decision.model_dump(),
        },
    )

    agent_message = FeedbackMessage(
        thread_id=thread.id,
        role="agent",
        message_type="question" if decision.status == "agent_needs_user_input" else "decision",
        content=decision.follow_up_question or decision.user_reply,
        structured_json=json.dumps(decision.model_dump(), ensure_ascii=False),
    )
    db.add(agent_message)
    db.flush()
    _append_thread_event(
        db,
        project_id=thread.project_id,
        audit_version=thread.audit_version,
        event_kind="feedback_agent_reply",
        message="误报反馈Agent 已生成回复",
        meta={"thread_id": thread.id, "status": decision.status},
    )
    return agent_message


def _mark_thread_reviewing(
    db: Session,
    *,
    thread: FeedbackThread,
    summary: Optional[str] = None,
) -> None:
    thread.status = "agent_reviewing"
    thread.agent_decision = None
    thread.agent_confidence = None
    thread.learning_decision = "pending"
    thread.summary = summary
    thread.resolution_reason = None
    thread.escalation_reason = None
    thread.updated_at = datetime.now()


def _process_feedback_thread_review_async(project_id: str, thread_id: str) -> None:
    db = SessionLocal()
    try:
        thread = _get_thread(db, project_id, thread_id)
        audit_result = _get_audit_result(db, project_id, thread.audit_result_id)
        agent_message = _run_feedback_agent_review(db, thread=thread, audit_result=audit_result)
        thread_payload = _serialize_thread_fresh(db, project_id, thread.id)
        for message in thread_payload.messages:
            if message.id == agent_message.id:
                _append_feedback_message_created_event(db, thread=thread_payload, message=message)
                break
        _append_feedback_thread_upsert_event(db, thread=thread_payload)
        db.commit()
    except Exception as exc:
        db.rollback()
        try:
            thread = _get_thread(db, project_id, thread_id)
            thread.status = "agent_unavailable"
            thread.agent_decision = "agent_unavailable"
            thread.learning_decision = "pending"
            thread.summary = "误报反馈Agent（OpenRouter）当前未联通，请稍后再试。"
            thread.escalation_reason = str(exc)
            thread.updated_at = datetime.now()
            system_message = FeedbackMessage(
                thread_id=thread.id,
                role="system",
                message_type="note",
                content="误报反馈Agent（OpenRouter）当前未联通，请稍后再试。",
                structured_json=json.dumps(
                    {
                        "status": "agent_unavailable",
                        "provider_mode": str(os.getenv("FEEDBACK_AGENT_PROVIDER", "api") or "api").strip() or "api",
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                ),
            )
            db.add(system_message)
            db.flush()
            _append_thread_event(
                db,
                project_id=project_id,
                audit_version=thread.audit_version,
                event_kind="feedback_agent_review_failed",
                message="误报反馈Agent（OpenRouter）未联通",
                meta={
                    "thread_id": thread.id,
                    "error": str(exc),
                    "provider_mode": str(os.getenv("FEEDBACK_AGENT_PROVIDER", "api") or "api").strip() or "api",
                    "agent_mode": str(os.getenv("FEEDBACK_AGENT_MODE", "llm") or "llm").strip() or "llm",
                },
            )
            thread_payload = _serialize_thread_fresh(db, project_id, thread.id)
            for message in thread_payload.messages:
                if message.id == system_message.id:
                    _append_feedback_message_created_event(db, thread=thread_payload, message=message)
                    break
            _append_feedback_thread_upsert_event(db, thread=thread_payload)
            db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()


def _append_feedback_thread_upsert_event(
    db: Session,
    *,
    thread: FeedbackThreadResponse,
) -> None:
    _append_thread_event(
        db,
        project_id=thread.project_id,
        audit_version=thread.audit_version,
        event_kind="feedback_thread_upsert",
        message="误报反馈线程已更新",
        meta={
            "thread_id": thread.id,
            "audit_result_id": thread.audit_result_id,
            "result_group_id": thread.result_group_id,
            "thread": thread.model_dump(mode="json"),
        },
    )


def _append_feedback_message_created_event(
    db: Session,
    *,
    thread: FeedbackThreadResponse,
    message: FeedbackMessageResponse,
) -> None:
    _append_thread_event(
        db,
        project_id=thread.project_id,
        audit_version=thread.audit_version,
        event_kind="feedback_message_created",
        message="误报反馈消息已创建",
        meta={
            "thread_id": thread.id,
            "audit_result_id": thread.audit_result_id,
            "result_group_id": thread.result_group_id,
            "message_item": message.model_dump(mode="json"),
        },
    )


def _query_feedback_threads_by_result_refs(
    db: Session,
    *,
    project_id: str,
    result_refs: List[str],
    audit_version: Optional[int],
) -> List[FeedbackThreadResponse]:
    if not result_refs:
        raise HTTPException(status_code=400, detail="audit_result_ids 不能为空")

    threads = (
        db.query(FeedbackThread)
        .filter(FeedbackThread.project_id == project_id)
        .order_by(
            FeedbackThread.result_group_id.asc(),
            FeedbackThread.audit_result_id.asc(),
            FeedbackThread.updated_at.desc(),
            FeedbackThread.created_at.desc(),
        )
        .all()
    )

    latest_by_result_ref: dict[str, FeedbackThread] = {}
    for thread in threads:
        if thread.result_group_id:
            latest_by_result_ref.setdefault(thread.result_group_id, thread)
        latest_by_result_ref.setdefault(thread.audit_result_id, thread)

    serialized: List[FeedbackThreadResponse] = []
    for result_ref in result_refs:
        if result_ref in latest_by_result_ref:
            serialized.append(_serialize_thread(latest_by_result_ref[result_ref]))
            continue
        if audit_version is None:
            continue
        grouped_row = _get_grouped_row(
            db,
            project_id=project_id,
            audit_version=audit_version,
            group_id=result_ref,
        )
        if not grouped_row:
            continue
        issue_ids = [str(item).strip() for item in grouped_row.get("issue_ids") or [] if str(item).strip()]
        fallback = next((latest_by_result_ref.get(issue_id) for issue_id in issue_ids if latest_by_result_ref.get(issue_id)), None)
        if fallback:
            payload = _serialize_thread(fallback)
            if not payload.result_group_id:
                payload.result_group_id = result_ref
            serialized.append(payload)
    return serialized


def _iter_feedback_threads_stream(
    project_id: str,
    audit_version: int,
    since_id: Optional[int],
    thread_id: Optional[str],
):
    last_id = int(since_id or 0)
    heartbeat_seconds = _stream_env_float("AUDIT_STREAM_HEARTBEAT_SECONDS", 25.0)
    poll_seconds = _stream_env_float("AUDIT_STREAM_POLL_SECONDS", 1.0)
    test_once = str(os.getenv("AUDIT_STREAM_TEST_ONCE", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    last_emit_at = time.monotonic()
    sent_any = False
    sent_heartbeat = False

    while True:
        db = SessionLocal()
        try:
            event_kinds = ["feedback_thread_upsert"]
            if thread_id:
                event_kinds.append("feedback_message_created")
            rows = (
                db.query(AuditRunEvent)
                .filter(
                    AuditRunEvent.project_id == project_id,
                    AuditRunEvent.audit_version == audit_version,
                    AuditRunEvent.id > last_id,
                    AuditRunEvent.event_kind.in_(event_kinds),
                )
                .order_by(AuditRunEvent.id.asc())
                .limit(200)
                .all()
            )
        finally:
            db.close()

        if rows:
            for row in rows:
                meta = {}
                if row.meta_json:
                    try:
                        parsed = json.loads(row.meta_json)
                        if isinstance(parsed, dict):
                            meta = parsed
                    except Exception:
                        meta = {}
                if thread_id and str(meta.get("thread_id") or "").strip() != thread_id:
                    last_id = row.id
                    continue
                payload = {
                    "id": row.id,
                    "audit_version": row.audit_version,
                    "event_kind": row.event_kind,
                    "message": row.message,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "meta": meta,
                }
                last_id = row.id
                last_emit_at = time.monotonic()
                sent_any = True
                yield _format_sse_event(event=row.event_kind, data=payload, event_id=row.id)
            if test_once and since_id is not None:
                break
            continue

        if time.monotonic() - last_emit_at >= heartbeat_seconds:
            last_emit_at = time.monotonic()
            sent_any = True
            sent_heartbeat = True
            yield _format_sse_event(
                event="heartbeat",
                data={
                    "id": last_id,
                    "audit_version": audit_version,
                    "event_kind": "heartbeat",
                    "message": "反馈流连接正常，系统仍在等待新反馈变化",
                    "meta": {"stream_kind": "feedback_threads"},
                },
                event_id=last_id if last_id > 0 else None,
            )
            if test_once:
                break

        if test_once and sent_any and sent_heartbeat:
            break
        time.sleep(poll_seconds)


@router.post(
    "/projects/{project_id}/audit/results/{result_id}/feedback-thread",
    response_model=FeedbackThreadResponse,
)
async def create_feedback_thread(
    project_id: str,
    result_id: str,
    request: Request,
    audit_version: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    project = _get_project(db, project_id)
    result, result_group_id = _resolve_result_reference(
        db,
        project_id=project_id,
        result_ref=result_id,
        audit_version=audit_version,
    )
    content, image_uploads = await _parse_feedback_request_payload(request, primary_text_key="message")
    if not content and not image_uploads:
        raise HTTPException(status_code=400, detail="message 不能为空")
    content = content or _IMAGE_ONLY_MESSAGE_FALLBACK

    thread = FeedbackThread(
        project_id=project_id,
        audit_result_id=result.id,
        result_group_id=result_group_id,
        audit_version=result.audit_version,
        status="open",
        learning_decision="pending",
        opened_by="user",
        source_agent=result.source_agent,
        rule_id=result.rule_id,
        issue_type=result.type,
        summary="Agent 正在判断这条反馈。",
    )
    db.add(thread)
    db.flush()
    user_message = FeedbackMessage(
        thread_id=thread.id,
        role="user",
        message_type="claim",
        content=content,
    )
    db.add(user_message)
    db.flush()
    await _store_feedback_message_attachments(
        db,
        project=project,
        thread=thread,
        message=user_message,
        uploads=image_uploads,
    )
    _append_thread_event(
        db,
        project_id=project_id,
        audit_version=result.audit_version,
        event_kind="feedback_thread_opened",
        message="用户发起了一条误报反馈会话",
        meta={"thread_id": thread.id, "audit_result_id": result.id},
    )
    _mark_thread_reviewing(
        db,
        thread=thread,
        summary="Agent 正在判断这条反馈。",
    )
    db.flush()
    _append_thread_event(
        db,
        project_id=project_id,
        audit_version=result.audit_version,
        event_kind="feedback_agent_review_enqueued",
        message="误报反馈Agent 已进入后台判断",
        meta={"thread_id": thread.id, "audit_result_id": result.id},
    )
    thread_payload = _serialize_thread_fresh(db, project_id, thread.id)
    for message in thread_payload.messages:
        if message.id == user_message.id:
            _append_feedback_message_created_event(db, thread=thread_payload, message=message)
    _append_feedback_thread_upsert_event(db, thread=thread_payload)
    db.commit()
    db.refresh(thread)
    return _serialize_thread(thread)


@router.get(
    "/projects/{project_id}/audit/results/{result_id}/feedback-thread",
    response_model=FeedbackThreadResponse,
)
def get_feedback_thread_by_result(
    project_id: str,
    result_id: str,
    audit_version: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    _get_project(db, project_id)
    _, result_group_id = _resolve_result_reference(
        db,
        project_id=project_id,
        result_ref=result_id,
        audit_version=audit_version,
    )
    thread = (
        db.query(FeedbackThread)
        .filter(
            FeedbackThread.project_id == project_id,
            (
                FeedbackThread.audit_result_id == result_id
                if result_group_id is None
                else FeedbackThread.result_group_id == result_group_id
            ),
        )
        .order_by(FeedbackThread.updated_at.desc(), FeedbackThread.created_at.desc())
        .first()
    )
    if not thread and result_group_id is not None:
        grouped_row = _get_grouped_row(
            db,
            project_id=project_id,
            audit_version=audit_version or 1,
            group_id=result_group_id,
        )
        issue_ids = grouped_row.get("issue_ids") if grouped_row else []
        if issue_ids:
            thread = (
                db.query(FeedbackThread)
                .filter(
                    FeedbackThread.project_id == project_id,
                    FeedbackThread.audit_result_id.in_(issue_ids),
                )
                .order_by(FeedbackThread.updated_at.desc(), FeedbackThread.created_at.desc())
                .first()
            )
    if not thread:
        raise HTTPException(status_code=404, detail="反馈会话不存在")
    payload = _serialize_thread(thread)
    if result_group_id and not payload.result_group_id:
        payload.result_group_id = result_group_id
    return payload


@router.get(
    "/projects/{project_id}/feedback-threads",
    response_model=List[FeedbackThreadResponse],
)
def list_feedback_threads_by_results(
    project_id: str,
    audit_result_ids: str = Query(..., description="逗号分隔的审核结果 ID 列表"),
    audit_version: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    _get_project(db, project_id)
    result_refs = [item.strip() for item in audit_result_ids.split(",") if item.strip()]
    return _query_feedback_threads_by_result_refs(
        db,
        project_id=project_id,
        result_refs=result_refs,
        audit_version=audit_version,
    )


@router.get("/projects/{project_id}/feedback-threads/stream")
def stream_feedback_threads(
    project_id: str,
    audit_version: int = Query(..., description="审核版本号"),
    since_id: Optional[int] = Query(None, description="从指定事件 ID 之后继续"),
    thread_id: Optional[str] = Query(None, description="仅订阅指定线程"),
    db: Session = Depends(get_db),
):
    _get_project(db, project_id)
    return StreamingResponse(
        _iter_feedback_threads_stream(project_id, audit_version, since_id, thread_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/projects/{project_id}/feedback-threads/query",
    response_model=List[FeedbackThreadResponse],
)
def query_feedback_threads_by_results(
    project_id: str,
    payload: FeedbackThreadBatchQueryRequest,
    db: Session = Depends(get_db),
):
    _get_project(db, project_id)
    result_refs = [item.strip() for item in payload.audit_result_ids if item and item.strip()]
    return _query_feedback_threads_by_result_refs(
        db,
        project_id=project_id,
        result_refs=result_refs,
        audit_version=payload.audit_version,
    )


@router.get(
    "/projects/{project_id}/feedback-threads/{thread_id}",
    response_model=FeedbackThreadResponse,
)
def get_feedback_thread(
    project_id: str,
    thread_id: str,
    db: Session = Depends(get_db),
):
    _get_project(db, project_id)
    thread = _get_thread(db, project_id, thread_id)
    return _serialize_thread(thread)


@router.get("/projects/{project_id}/feedback-attachments/{attachment_id}/file")
def get_feedback_attachment_file(
    project_id: str,
    attachment_id: str,
    db: Session = Depends(get_db),
):
    project = _get_project(db, project_id)
    attachment = (
        db.query(FeedbackMessageAttachment)
        .filter(
            FeedbackMessageAttachment.id == attachment_id,
            FeedbackMessageAttachment.project_id == project_id,
        )
        .first()
    )
    if not attachment:
        raise HTTPException(status_code=404, detail="反馈附件不存在")

    file_path = Path(attachment.storage_path).expanduser()
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="反馈附件文件不存在")

    project_root = resolve_project_dir(project, ensure=False).resolve()
    resolved = file_path.resolve()
    try:
        resolved.relative_to(project_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="非法文件访问")
    return FileResponse(str(resolved), media_type=attachment.mime_type, filename=attachment.file_name)


@router.get(
    "/projects/{project_id}/feedback-threads/{thread_id}/messages",
    response_model=List[FeedbackMessageResponse],
)
def list_feedback_thread_messages(
    project_id: str,
    thread_id: str,
    db: Session = Depends(get_db),
):
    _get_project(db, project_id)
    thread = _get_thread(db, project_id, thread_id)
    messages = sorted(thread.messages, key=lambda item: (item.created_at or datetime.min, item.id))
    return [_serialize_message(project_id, message) for message in messages]


@router.post(
    "/projects/{project_id}/feedback-threads/{thread_id}/messages",
    response_model=FeedbackThreadResponse,
)
async def append_feedback_thread_message(
    project_id: str,
    thread_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    project = _get_project(db, project_id)
    thread = _get_thread(db, project_id, thread_id)
    if thread.status == "agent_reviewing":
        raise HTTPException(status_code=409, detail="上一轮反馈还在处理中，请等 Agent 返回后再补充。")
    content, image_uploads = await _parse_feedback_request_payload(request, primary_text_key="content")
    if not content and not image_uploads:
        raise HTTPException(status_code=400, detail="content 不能为空")
    content = content or _IMAGE_ONLY_MESSAGE_FALLBACK

    message_type = "answer" if thread.messages else "claim"
    user_message = FeedbackMessage(
        thread_id=thread.id,
        role="user",
        message_type=message_type,
        content=content,
    )
    db.add(user_message)
    db.flush()
    await _store_feedback_message_attachments(
        db,
        project=project,
        thread=thread,
        message=user_message,
        uploads=image_uploads,
    )
    _mark_thread_reviewing(
        db,
        thread=thread,
        summary="Agent 正在重新判断这条反馈。",
    )
    db.flush()
    _append_thread_event(
        db,
        project_id=project_id,
        audit_version=thread.audit_version,
        event_kind="feedback_user_message",
        message="用户补充了一条误报反馈信息",
        meta={"thread_id": thread.id},
    )
    _append_thread_event(
        db,
        project_id=project_id,
        audit_version=thread.audit_version,
        event_kind="feedback_agent_review_enqueued",
        message="误报反馈Agent 已进入后台重新判断",
        meta={"thread_id": thread.id, "audit_result_id": thread.audit_result_id},
    )
    thread_payload = _serialize_thread_fresh(db, project_id, thread.id)
    for message in thread_payload.messages:
        if message.id == user_message.id:
            _append_feedback_message_created_event(db, thread=thread_payload, message=message)
    _append_feedback_thread_upsert_event(db, thread=thread_payload)
    db.commit()
    db.refresh(thread)
    return _serialize_thread(thread)

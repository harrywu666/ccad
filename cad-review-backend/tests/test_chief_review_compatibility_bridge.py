from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_dimension_worker_wrapper_returns_worker_card(monkeypatch):
    dimension_audit = importlib.import_module("services.audit.dimension_audit")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    captured: dict[str, object] = {}

    def fake_dimension_audit(project_id, audit_version, db, pair_filters=None, hot_sheet_registry=None):  # noqa: ANN001
        captured["pair_filters"] = pair_filters
        return [
            dimension_audit.AuditResult(
                project_id=project_id,
                audit_version=audit_version,
                type="dimension",
                severity="warning",
                sheet_no_a="A1.01",
                sheet_no_b="A4.01",
                location="1/A1.01",
                description="尺寸不一致",
            )
        ]

    monkeypatch.setattr(dimension_audit, "audit_dimensions", fake_dimension_audit)

    result = dimension_audit.run_dimension_worker_wrapper(
        "proj-bridge",
        7,
        "db-session",
        review_task_schema.WorkerTaskCard(
            id="task-dim",
            hypothesis_id="hyp-1",
            worker_kind="spatial_consistency",
            objective="核对 A1.01 与 A4.01",
            source_sheet_no="A1.01",
            target_sheet_nos=["A4.01"],
            context={"project_id": "proj-bridge", "audit_version": 7},
        ),
    )

    assert captured["pair_filters"] == [("A1.01", "A4.01")]
    assert result.status == "confirmed"
    assert result.meta["compat_mode"] == "worker_wrapper"


def test_material_worker_wrapper_limits_to_source_sheet(monkeypatch):
    material_audit = importlib.import_module("services.audit.material_audit")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    captured: dict[str, object] = {}

    def fake_material_audit(project_id, audit_version, db, sheet_filters=None, hot_sheet_registry=None):  # noqa: ANN001
        captured["sheet_filters"] = sheet_filters
        return []

    monkeypatch.setattr(material_audit, "audit_materials", fake_material_audit)

    result = material_audit.run_material_worker_wrapper(
        "proj-bridge",
        8,
        "db-session",
        review_task_schema.WorkerTaskCard(
            id="task-mat",
            hypothesis_id="hyp-2",
            worker_kind="material_semantic_consistency",
            objective="核对 A1.01 材料",
            source_sheet_no="A1.01",
            context={"project_id": "proj-bridge", "audit_version": 8},
        ),
    )

    assert captured["sheet_filters"] == ["A1.01"]
    assert result.status == "rejected"
    assert result.meta["compat_mode"] == "worker_wrapper"


def test_index_worker_wrapper_limits_to_source_sheet(monkeypatch):
    index_audit = importlib.import_module("services.audit.index_audit")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    captured: dict[str, object] = {}

    def fake_index_audit(project_id, audit_version, db, source_sheet_filters=None, hot_sheet_registry=None):  # noqa: ANN001
        captured["source_sheet_filters"] = source_sheet_filters
        return []

    monkeypatch.setattr(index_audit, "audit_indexes", fake_index_audit)

    result = index_audit.run_index_worker_wrapper(
        "proj-bridge",
        9,
        "db-session",
        review_task_schema.WorkerTaskCard(
            id="task-idx",
            hypothesis_id="hyp-3",
            worker_kind="index_reference",
            objective="核对 A1.01 索引",
            source_sheet_no="A1.01",
            target_sheet_nos=["A4.01"],
            context={"project_id": "proj-bridge", "audit_version": 9},
        ),
    )

    assert captured["source_sheet_filters"] == ["A1.01"]
    assert result.status == "rejected"
    assert result.meta["compat_mode"] == "worker_wrapper"


def test_relationship_worker_wrapper_limits_sheet_scope(monkeypatch):
    relationship_discovery = importlib.import_module("services.audit.relationship_discovery")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    captured: dict[str, object] = {}

    def fake_discover_relationships_v2(project_id, db, *, audit_version=None, hot_sheet_registry=None, sheet_filters=None):  # noqa: ANN001
        captured["sheet_filters"] = sheet_filters
        return [
            {
                "source": "A1.01",
                "target": "A4.01",
                "confidence": 0.91,
                "finding": {
                    "sheet_no": "A1.01",
                    "location": "A1.01 -> A4.01",
                    "rule_id": "relationship_visual_review",
                    "evidence_pack_id": "paired_overview_pack",
                    "description": "源图里有明确节点索引指向目标图",
                    "severity": "warning",
                },
            }
        ]

    monkeypatch.setattr(relationship_discovery, "discover_relationships_v2", fake_discover_relationships_v2)

    result = relationship_discovery.run_relationship_worker_wrapper(
        "proj-bridge",
        10,
        "db-session",
        review_task_schema.WorkerTaskCard(
            id="task-rel",
            hypothesis_id="hyp-4",
            worker_kind="node_host_binding",
            objective="核对 A1.01 节点归属",
            source_sheet_no="A1.01",
            target_sheet_nos=["A4.01"],
            context={"project_id": "proj-bridge", "audit_version": 10},
        ),
    )

    assert captured["sheet_filters"] == ["A1.01", "A4.01"]
    assert result.status == "confirmed"
    assert result.meta["compat_mode"] == "worker_wrapper"


def test_default_chief_worker_runner_dispatches_to_dimension_wrapper(monkeypatch):
    orchestrator = importlib.import_module("services.audit_runtime.orchestrator")
    dimension_audit = importlib.import_module("services.audit.dimension_audit")
    review_worker_runtime = importlib.import_module("services.audit_runtime.review_worker_runtime")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    called = {"value": False}

    class _FakeSession:
        def close(self):
            return None

    def fake_wrapper(project_id, audit_version, db, task):  # noqa: ANN001
        called["value"] = True
        return review_task_schema.WorkerResultCard(
            task_id=task.id,
            hypothesis_id=task.hypothesis_id,
            worker_kind=task.worker_kind,
            status="confirmed",
            confidence=0.88,
            summary="legacy wrapper ok",
            meta={"compat_mode": "worker_wrapper"},
        )

    async def fake_native_runner(*args, **kwargs):  # noqa: ANN001
        return None

    monkeypatch.setattr(orchestrator, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(review_worker_runtime, "run_native_review_worker", fake_native_runner)
    monkeypatch.setattr(dimension_audit, "run_dimension_worker_wrapper", fake_wrapper)

    result = asyncio.run(
        orchestrator._default_chief_worker_runner(
            review_task_schema.WorkerTaskCard(
                id="task-chief",
                hypothesis_id="hyp-chief",
                worker_kind="spatial_consistency",
                objective="核对 A1.01 与 A4.01",
                source_sheet_no="A1.01",
                target_sheet_nos=["A4.01"],
                context={"project_id": "proj-bridge", "audit_version": 11},
            )
        )
    )

    assert called["value"] is True
    assert result.meta["compat_mode"] == "worker_wrapper"


def test_native_review_worker_returns_native_card_for_node_host_binding(monkeypatch):
    review_worker_runtime = importlib.import_module("services.audit_runtime.review_worker_runtime")
    relationship_discovery = importlib.import_module("services.audit.relationship_discovery")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    captured: dict[str, object] = {}

    async def fake_discover_relationship_task_v2(**kwargs):  # noqa: ANN001
        captured["source_sheet_no"] = kwargs["source_sheet"]["sheet_no"]
        captured["target_sheet_no"] = kwargs["target_sheet"]["sheet_no"]
        return [
            {
                "source": "A1.01",
                "target": "A4.01",
                "confidence": 0.93,
                "finding": {
                    "sheet_no": "A1.01",
                    "location": "A1.01 -> A4.01",
                    "rule_id": "relationship_visual_review",
                    "evidence_pack_id": "paired_overview_pack",
                    "description": "节点索引明确指向 A4.01",
                    "severity": "warning",
                },
            }
        ]

    monkeypatch.setattr(
        relationship_discovery,
        "_load_ready_sheets",
        lambda project_id, db, sheet_filters=None: [
            {"sheet_no": "A1-01", "sheet_name": "首层平面图", "pdf_path": "/tmp/a.pdf", "page_index": 0},
            {"sheet_no": "A4-01", "sheet_name": "节点详图", "pdf_path": "/tmp/b.pdf", "page_index": 0},
        ],
    )
    monkeypatch.setattr(relationship_discovery, "_discover_relationship_task_v2", fake_discover_relationship_task_v2)
    monkeypatch.setattr(relationship_discovery, "_validate_and_normalize", lambda rels, valid_sheet_nos: rels)
    monkeypatch.setattr(review_worker_runtime, "load_runtime_skill_profile", lambda *args, **kwargs: {})
    monkeypatch.setattr(review_worker_runtime, "load_feedback_runtime_profile", lambda *args, **kwargs: {})

    result = asyncio.run(
        review_worker_runtime.run_native_review_worker(
            task=review_task_schema.WorkerTaskCard(
                id="task-native",
                hypothesis_id="hyp-native",
                worker_kind="node_host_binding",
                objective="确认节点归属",
                source_sheet_no="A1.01",
                target_sheet_nos=["A4.01"],
                context={"project_id": "proj-native", "audit_version": 3},
            ),
            db="db-session",
        )
    )

    assert captured["source_sheet_no"] == "A1-01"
    assert captured["target_sheet_no"] == "A4-01"
    assert result is not None
    assert result.status == "confirmed"
    assert result.meta["compat_mode"] == "native_worker"
    assert result.meta["skill_mode"] == "worker_skill"
    assert result.meta["skill_id"] == "node_host_binding"
    assert result.meta["skill_path"].endswith("agents/review_worker/skills/node_host_binding/SKILL.md")


def test_default_chief_worker_runner_prefers_native_worker(monkeypatch):
    orchestrator = importlib.import_module("services.audit_runtime.orchestrator")
    review_worker_runtime = importlib.import_module("services.audit_runtime.review_worker_runtime")
    relationship_discovery = importlib.import_module("services.audit.relationship_discovery")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    class _FakeSession:
        def close(self):
            return None

    called = {"wrapper": False}

    async def fake_native_runner(*, task, db):  # noqa: ANN001
        return review_task_schema.WorkerResultCard(
            task_id=task.id,
            hypothesis_id=task.hypothesis_id,
            worker_kind=task.worker_kind,
            status="confirmed",
            confidence=0.9,
            summary="native ok",
            meta={"compat_mode": "native_worker"},
        )

    def fake_wrapper(*args, **kwargs):  # noqa: ANN001
        called["wrapper"] = True
        raise AssertionError("wrapper should not be called when native worker returns a result")

    monkeypatch.setattr(orchestrator, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(review_worker_runtime, "run_native_review_worker", fake_native_runner)
    monkeypatch.setattr(relationship_discovery, "run_relationship_worker_wrapper", fake_wrapper)

    result = asyncio.run(
        orchestrator._default_chief_worker_runner(
            review_task_schema.WorkerTaskCard(
                id="task-chief-native",
                hypothesis_id="hyp-chief-native",
                worker_kind="node_host_binding",
                objective="确认节点归属",
                source_sheet_no="A1.01",
                target_sheet_nos=["A4.01"],
                context={"project_id": "proj-bridge", "audit_version": 12},
            )
        )
    )

    assert called["wrapper"] is False
    assert result.meta["compat_mode"] == "native_worker"


def test_native_review_worker_returns_native_card_for_index_reference(monkeypatch):
    review_worker_runtime = importlib.import_module("services.audit_runtime.review_worker_runtime")
    index_skill = importlib.import_module("services.audit_runtime.worker_skills.index_reference_skill")
    index_audit = importlib.import_module("services.audit.index_audit")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    class _Issue:
        def __init__(self):
            self.project_id = "proj-native-index"
            self.audit_version = 5
            self.type = "index"
            self.severity = "warning"
            self.sheet_no_a = "A1.01"
            self.sheet_no_b = "A4.01"
            self.location = "索引D1"
            self.description = "目标图里未找到同编号索引"
            self.evidence_json = "{}"
            self.confidence = 0.87
            self.finding_status = "confirmed"
            self.review_round = 2
            self.rule_id = "missing_target_index_no"
            self.finding_type = "missing_ref"
            self.source_agent = "index_review_agent"
            self.evidence_pack_id = "overview_pack"

    monkeypatch.setattr(index_audit, "load_active_skill_rules", lambda *args, **kwargs: [])
    monkeypatch.setattr(index_audit, "build_index_alias_map", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        index_audit,
        "_collect_index_issue_candidates",
        lambda *args, **kwargs: [{"issue": _Issue(), "review_kind": "missing_target_index_no"}],
    )
    monkeypatch.setattr(index_audit, "_index_ai_review_enabled", lambda: False)
    monkeypatch.setattr(index_audit, "_review_index_issue_candidates_async", lambda *args, **kwargs: [])
    monkeypatch.setattr(index_audit, "_reviewable_index_issue", lambda kind: True)
    monkeypatch.setattr(index_audit, "_apply_index_finding", lambda issue, candidate: issue)
    monkeypatch.setattr(index_skill, "load_runtime_skill_profile", lambda *args, **kwargs: {})
    monkeypatch.setattr(index_skill, "load_feedback_runtime_profile", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        index_audit,
        "_index_issue_evidence",
        lambda issue: {
            "sheet_no": issue.sheet_no_a,
            "location": issue.location,
            "rule_id": "index_visual_review",
            "evidence_pack_id": "overview_pack",
            "description": issue.description,
            "severity": issue.severity,
        },
    )

    result = asyncio.run(
        review_worker_runtime.run_native_review_worker(
            task=review_task_schema.WorkerTaskCard(
                id="task-native-index",
                hypothesis_id="hyp-native-index",
                worker_kind="index_reference",
                objective="确认索引引用",
                source_sheet_no="A1.01",
                target_sheet_nos=["A4.01"],
                context={"project_id": "proj-native-index", "audit_version": 5},
            ),
            db="db-session",
        )
    )

    assert result is not None
    assert result.status == "confirmed"
    assert result.meta["compat_mode"] == "native_worker"
    assert result.meta["skill_mode"] == "worker_skill"
    assert result.meta["skill_id"] == "index_reference"
    assert result.meta["issue_count"] == 1


def test_default_chief_worker_runner_prefers_native_index_worker(monkeypatch):
    orchestrator = importlib.import_module("services.audit_runtime.orchestrator")
    review_worker_runtime = importlib.import_module("services.audit_runtime.review_worker_runtime")
    index_audit = importlib.import_module("services.audit.index_audit")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    class _FakeSession:
        def close(self):
            return None

    called = {"wrapper": False}

    async def fake_native_runner(*, task, db):  # noqa: ANN001
        if task.worker_kind != "index_reference":
            return None
        return review_task_schema.WorkerResultCard(
            task_id=task.id,
            hypothesis_id=task.hypothesis_id,
            worker_kind=task.worker_kind,
            status="confirmed",
            confidence=0.92,
            summary="native index ok",
            meta={"compat_mode": "native_worker"},
        )

    def fake_wrapper(*args, **kwargs):  # noqa: ANN001
        called["wrapper"] = True
        raise AssertionError("wrapper should not be called when native index worker returns a result")

    monkeypatch.setattr(orchestrator, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(review_worker_runtime, "run_native_review_worker", fake_native_runner)
    monkeypatch.setattr(index_audit, "run_index_worker_wrapper", fake_wrapper)

    result = asyncio.run(
        orchestrator._default_chief_worker_runner(
            review_task_schema.WorkerTaskCard(
                id="task-chief-index",
                hypothesis_id="hyp-chief-index",
                worker_kind="index_reference",
                objective="确认索引引用",
                source_sheet_no="A1.01",
                target_sheet_nos=["A4.01"],
                context={"project_id": "proj-bridge", "audit_version": 13},
            )
        )
    )

    assert called["wrapper"] is False
    assert result.meta["compat_mode"] == "native_worker"


def test_native_review_worker_returns_native_card_for_material_semantic_consistency(monkeypatch):
    review_worker_runtime = importlib.import_module("services.audit_runtime.review_worker_runtime")
    material_skill = importlib.import_module("services.audit_runtime.worker_skills.material_semantic_skill")
    material_audit = importlib.import_module("services.audit.material_audit")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    class _Issue:
        def __init__(self):
            self.project_id = "proj-native-material"
            self.audit_version = 6
            self.type = "material"
            self.severity = "warning"
            self.sheet_no_a = "A1.01"
            self.sheet_no_b = None
            self.location = "材料编号M01"
            self.description = "材料名称命名不一致"
            self.evidence_json = "{}"
            self.confidence = 0.83
            self.finding_status = "confirmed"
            self.review_round = 1
            self.rule_id = "material_name_conflict"
            self.finding_type = "material_conflict"
            self.source_agent = "material_review_agent"
            self.evidence_pack_id = "focus_pack"

    monkeypatch.setattr(
        material_audit,
        "_collect_material_rule_issues_and_ai_jobs",
        lambda *args, **kwargs: ([_Issue()], []),
    )
    monkeypatch.setattr(material_audit, "_apply_material_finding", lambda issue: issue)
    monkeypatch.setattr(material_audit, "_run_material_ai_reviews_bounded", lambda *args, **kwargs: [])
    monkeypatch.setattr(material_skill, "load_runtime_skill_profile", lambda *args, **kwargs: {})
    monkeypatch.setattr(material_skill, "load_feedback_runtime_profile", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        material_audit,
        "_material_issue_evidence",
        lambda issue: {
            "sheet_no": issue.sheet_no_a,
            "location": issue.location,
            "rule_id": "material_consistency_review",
            "evidence_pack_id": "focus_pack",
            "description": issue.description,
            "severity": issue.severity,
        },
    )

    result = asyncio.run(
        review_worker_runtime.run_native_review_worker(
            task=review_task_schema.WorkerTaskCard(
                id="task-native-material",
                hypothesis_id="hyp-native-material",
                worker_kind="material_semantic_consistency",
                objective="确认材料一致性",
                source_sheet_no="A1.01",
                target_sheet_nos=[],
                context={"project_id": "proj-native-material", "audit_version": 6},
            ),
            db="db-session",
        )
    )

    assert result is not None
    assert result.status == "confirmed"
    assert result.meta["compat_mode"] == "native_worker"
    assert result.meta["skill_mode"] == "worker_skill"
    assert result.meta["skill_id"] == "material_semantic_consistency"
    assert result.meta["issue_count"] == 1


def test_default_chief_worker_runner_prefers_native_material_worker(monkeypatch):
    orchestrator = importlib.import_module("services.audit_runtime.orchestrator")
    review_worker_runtime = importlib.import_module("services.audit_runtime.review_worker_runtime")
    material_audit = importlib.import_module("services.audit.material_audit")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    class _FakeSession:
        def close(self):
            return None

    called = {"wrapper": False}

    async def fake_native_runner(*, task, db):  # noqa: ANN001
        if task.worker_kind != "material_semantic_consistency":
            return None
        return review_task_schema.WorkerResultCard(
            task_id=task.id,
            hypothesis_id=task.hypothesis_id,
            worker_kind=task.worker_kind,
            status="confirmed",
            confidence=0.9,
            summary="native material ok",
            meta={"compat_mode": "native_worker"},
        )

    def fake_wrapper(*args, **kwargs):  # noqa: ANN001
        called["wrapper"] = True
        raise AssertionError("wrapper should not be called when native material worker returns a result")

    monkeypatch.setattr(orchestrator, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(review_worker_runtime, "run_native_review_worker", fake_native_runner)
    monkeypatch.setattr(material_audit, "run_material_worker_wrapper", fake_wrapper)

    result = asyncio.run(
        orchestrator._default_chief_worker_runner(
            review_task_schema.WorkerTaskCard(
                id="task-chief-material",
                hypothesis_id="hyp-chief-material",
                worker_kind="material_semantic_consistency",
                objective="确认材料一致性",
                source_sheet_no="A1.01",
                target_sheet_nos=[],
                context={"project_id": "proj-bridge", "audit_version": 14},
            )
        )
    )

    assert called["wrapper"] is False
    assert result.meta["compat_mode"] == "native_worker"


def test_native_review_worker_returns_native_card_for_dimension_consistency(monkeypatch):
    review_worker_runtime = importlib.import_module("services.audit_runtime.review_worker_runtime")
    dimension_audit = importlib.import_module("services.audit.dimension_audit")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    class _Issue:
        def __init__(self):
            self.project_id = "proj-native-dimension"
            self.audit_version = 7
            self.type = "dimension"
            self.severity = "warning"
            self.sheet_no_a = "A1.01"
            self.sheet_no_b = "A4.01"
            self.location = "轴网1/轴网A"
            self.description = "两图尺寸标注不一致"
            self.evidence_json = "{}"
            self.confidence = 0.86
            self.finding_status = "confirmed"
            self.review_round = 1
            self.rule_id = "dimension_pair_compare"
            self.finding_type = "dim_mismatch"
            self.source_agent = "dimension_review_agent"
            self.evidence_pack_id = "paired_overview_pack"

    async def fake_collect_async(*args, **kwargs):  # noqa: ANN001
        return [_Issue()]

    monkeypatch.setattr(
        dimension_audit,
        "_collect_dimension_pair_issues_async",
        fake_collect_async,
    )
    monkeypatch.setattr(
        dimension_audit,
        "_collect_dimension_pair_issues",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("native dimension worker should await async collector")
        ),
    )
    monkeypatch.setattr(
        dimension_audit,
        "_dimension_issue_evidence",
        lambda issue: {
            "sheet_no": issue.sheet_no_a,
            "location": issue.location,
            "rule_id": "dimension_pair_compare",
            "evidence_pack_id": "paired_overview_pack",
            "description": issue.description,
            "severity": issue.severity,
        },
    )

    result = asyncio.run(
        review_worker_runtime.run_native_review_worker(
            task=review_task_schema.WorkerTaskCard(
                id="task-native-dimension",
                hypothesis_id="hyp-native-dimension",
                worker_kind="spatial_consistency",
                objective="确认尺寸一致性",
                source_sheet_no="A1.01",
                target_sheet_nos=["A4.01"],
                context={"project_id": "proj-native-dimension", "audit_version": 7},
            ),
            db="db-session",
        )
    )

    assert result is not None
    assert result.status == "confirmed"
    assert result.meta["compat_mode"] == "native_worker"
    assert result.meta["skill_mode"] == "worker_skill"
    assert result.meta["skill_id"] == "spatial_consistency"
    assert result.meta["skill_path"].endswith("agents/review_worker/skills/spatial_consistency/SKILL.md")
    assert result.meta["issue_count"] == 1


def test_default_chief_worker_runner_prefers_native_dimension_worker(monkeypatch):
    orchestrator = importlib.import_module("services.audit_runtime.orchestrator")
    review_worker_runtime = importlib.import_module("services.audit_runtime.review_worker_runtime")
    dimension_audit = importlib.import_module("services.audit.dimension_audit")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    class _FakeSession:
        def close(self):
            return None

    called = {"wrapper": False}

    async def fake_native_runner(*, task, db):  # noqa: ANN001
        if task.worker_kind not in {"spatial_consistency", "elevation_consistency"}:
            return None
        return review_task_schema.WorkerResultCard(
            task_id=task.id,
            hypothesis_id=task.hypothesis_id,
            worker_kind=task.worker_kind,
            status="confirmed",
            confidence=0.91,
            summary="native dimension ok",
            meta={"compat_mode": "native_worker"},
        )

    def fake_wrapper(*args, **kwargs):  # noqa: ANN001
        called["wrapper"] = True
        raise AssertionError("wrapper should not be called when native dimension worker returns a result")

    monkeypatch.setattr(orchestrator, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(review_worker_runtime, "run_native_review_worker", fake_native_runner)
    monkeypatch.setattr(dimension_audit, "run_dimension_worker_wrapper", fake_wrapper)

    result = asyncio.run(
        orchestrator._default_chief_worker_runner(
            review_task_schema.WorkerTaskCard(
                id="task-chief-dimension",
                hypothesis_id="hyp-chief-dimension",
                worker_kind="spatial_consistency",
                objective="确认尺寸一致性",
                source_sheet_no="A1.01",
                target_sheet_nos=["A4.01"],
                context={"project_id": "proj-bridge", "audit_version": 15},
            )
        )
    )

    assert called["wrapper"] is False
    assert result.meta["compat_mode"] == "native_worker"

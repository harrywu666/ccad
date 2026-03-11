"""审查 Agent 向 Runner 汇报的共享结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(slots=True)
class AgentStatusReport:
    """审查 Agent 的一份内部工作汇报。"""

    batch_summary: str
    confirmed_findings: List[Dict[str, Any]] = field(default_factory=list)
    suspected_findings: List[Dict[str, Any]] = field(default_factory=list)
    blocking_issues: List[Dict[str, Any]] = field(default_factory=list)
    runner_help_request: str = ""
    agent_confidence: float = 0.0
    next_recommended_action: str = "continue"


DimensionAgentReport = AgentStatusReport
RelationshipAgentReport = AgentStatusReport
MaterialAgentReport = AgentStatusReport
IndexAgentReport = AgentStatusReport


__all__ = [
    "AgentStatusReport",
    "DimensionAgentReport",
    "RelationshipAgentReport",
    "MaterialAgentReport",
    "IndexAgentReport",
]

"""A2A 相关能力导出。"""

from core.tools.a2a.contracts import (
    AgentCardRef,
    DelegationTarget,
    ResultContract,
    StatusContract,
    TaskEnvelope,
)
from core.tools.a2a.gateway import A2AGateway

__all__ = [
    "AgentCardRef",
    "DelegationTarget",
    "ResultContract",
    "StatusContract",
    "TaskEnvelope",
    "A2AGateway",
]

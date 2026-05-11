"""合同审查 Agent 模块包。

提供合同审查的 LangGraph 工作流，基于 ReAct 模式。

核心模块：
1. state.py - 状态定义
2. graph.py - LangGraph 工作流图
3. nodes.py - 工作流节点实现
4. tools.py - LangChain 工具定义
5. react_agent.py - LangChain ReAct Agent 封装
6. reflection.py - 反思引擎
7. langchain_adapter.py - LangChain LLM 适配器
8. human_review_service.py - Human Review 服务

使用方式：
```python
from core.agent.workflows.contract import ContractWorkflowNodes

nodes = ContractWorkflowNodes(parser=parser)
graph = create_contract_graph(nodes)
result = graph.invoke(initial_state)
```
"""

from core.agent.workflows.contract.state import (
    AgentThought,
    AgentAction,
    ContractWorkflowStage,
    ContractWorkflowOutcome,
    ReviewContext,
    ThoughtRecord,
    ContractWorkflowState,
    create_initial_contract_state,
)
from core.agent.workflows.contract.graph import create_contract_graph, run_contract_workflow
from core.agent.workflows.contract.nodes import ContractWorkflowNodes
from core.agent.workflows.contract.tools import (
    get_contract_tools,
    get_tool_by_name,
    # 工具函数
    parse_contract,
    search_laws,
    search_templates,
    search_history,
    extract_clauses,
    analyze_risk,
    generate_report,
    request_human_review,
)
from core.agent.workflows.contract.react_agent import (
    ContractReActAgent,
    SimpleReActAgent,
    ToolExecutor,
)
from core.agent.workflows.contract.reflection import (
    ReflectionEngine,
    ReflectionResult,
    SimpleReflection,
)
from core.agent.workflows.contract.langchain_adapter import (
    LangChainLLMAdapter,
    create_langchain_llm,
    get_contract_agent_llm,
)
from core.agent.workflows.contract.human_review_service import (
    HumanReviewService,
    HumanReviewTask,
    ReviewPriority,
    ReviewDecision,
    RiskItem,
    get_human_review_service,
    create_review_from_contract_result,
)

__all__ = [
    # 状态定义
    "AgentThought",
    "AgentAction",
    "ContractWorkflowStage",
    "ContractWorkflowOutcome",
    "ReviewContext",
    "ThoughtRecord",
    "ContractWorkflowState",
    "create_initial_contract_state",
    # 图和工作流
    "create_contract_graph",
    "run_contract_workflow",
    # 节点
    "ContractWorkflowNodes",
    # 工具
    "get_contract_tools",
    "get_tool_by_name",
    "parse_contract",
    "search_laws",
    "search_templates",
    "search_history",
    "extract_clauses",
    "analyze_risk",
    "generate_report",
    "request_human_review",
    # ReAct Agent
    "ContractReActAgent",
    "SimpleReActAgent",
    "ToolExecutor",
    # 反思引擎
    "ReflectionEngine",
    "ReflectionResult",
    "SimpleReflection",
    # LangChain 适配器
    "LangChainLLMAdapter",
    "create_langchain_llm",
    "get_contract_agent_llm",
    # Human Review 服务
    "HumanReviewService",
    "HumanReviewTask",
    "ReviewPriority",
    "ReviewDecision",
    "RiskItem",
    "get_human_review_service",
    "create_review_from_contract_result",
]

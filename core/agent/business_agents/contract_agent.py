"""合同审查 Agent 服务。

提供合同审查的完整工作流封装。
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING

from core.agent.workflows.contract.state import (
    ContractWorkflowState,
    ContractWorkflowOutcome,
    create_initial_contract_state,
)
from core.agent.workflows.contract.nodes import ContractWorkflowNodes
from core.agent.workflows.contract.graph import create_contract_graph, run_contract_workflow
from core.contracts.extractor import ClauseExtractor
from core.contracts.models import ContractType
from core.contracts.report_generator import ReportGenerator
from core.contracts.risk_identifier import RiskIdentifier
from core.tools.local.parser import LocalDocumentParser

if TYPE_CHECKING:
    from core.llm.gateway import LLMGateway
    from core.security.auth import UserContext

logger = logging.getLogger(__name__)


class ContractAgent:
    """合同审查 Agent 服务。

    职责：
    - 持有合同审查工作流组件
    - 提供统一的合同审查接口
    - 管理审查状态

    使用方式：
    ```python
    agent = ContractAgent(llm_gateway=llm_gateway)
    result = await agent.review(
        contract_file_id="file_xxx",
        contract_name="采购合同",
        user_context=user_context,
    )
    ```
    """

    def __init__(
        self,
        llm_gateway: "LLMGateway | None" = None,
        use_llm_extraction: bool = True,
    ) -> None:
        """初始化合同审查 Agent。

        Args:
            llm_gateway: LLM 网关
            use_llm_extraction: 是否使用 LLM 抽取条款
        """

        self.llm_gateway = llm_gateway

        # 创建组件
        parser = LocalDocumentParser()
        clause_extractor = ClauseExtractor(
            llm_gateway=llm_gateway,
            use_llm=use_llm_extraction,
        )
        risk_identifier = RiskIdentifier()
        report_generator = ReportGenerator()

        # 创建工作流节点
        self._nodes = ContractWorkflowNodes(
            parser=parser,
            clause_extractor=clause_extractor,
            risk_identifier=risk_identifier,
            report_generator=report_generator,
        )

        # 创建工作流图
        self._graph = create_contract_graph(self._nodes)

    async def review(
        self,
        contract_file_id: str,
        user_context: "UserContext",
        contract_name: str | None = None,
        contract_type: ContractType | str | None = None,
        business_domain: str | None = None,
        run_id: str | None = None,
    ) -> dict:
        """审查合同。

        Args:
            contract_file_id: 合同文件 ID
            user_context: 用户上下文
            contract_name: 合同名称
            contract_type: 合同类型
            business_domain: 业务域
            run_id: 运行 ID

        Returns:
            审查结果
        """

        start_time = time.time()

        # 生成 run_id
        if not run_id:
            run_id = f"contract_{uuid.uuid4().hex[:12]}"

        logger.info(
            f"[{run_id}] 合同审查请求 | "
            f"contract_file_id={contract_file_id} | "
            f"user={user_context.user_id}"
        )

        try:
            # 创建初始状态
            state = create_initial_contract_state(
                run_id=run_id,
                contract_file_id=contract_file_id,
                user_id=user_context.user_id,
                user_role=user_context.user_role or "user",
                contract_name=contract_name,
                contract_type=contract_type.value if isinstance(contract_type, ContractType) else contract_type,
                business_domain=business_domain,
            )

            # 运行工作流
            result = await self._run_workflow(state)

            # 计算处理时间
            processing_time_ms = int((time.time() - start_time) * 1000)

            # 构建返回结果
            return self._build_response(result, processing_time_ms)

        except Exception as e:
            logger.error(f"[{run_id}] 合同审查异常: {e}", exc_info=True)
            processing_time_ms = int((time.time() - start_time) * 1000)

            return {
                "run_id": run_id,
                "contract_id": contract_file_id,
                "contract_name": contract_name or "未命名合同",
                "contract_type": str(contract_type) if contract_type else "其他",
                "overall_risk_level": "unknown",
                "status": "failed",
                "need_human_review": False,
                "report": None,
                "processing_time_ms": processing_time_ms,
                "error": str(e),
            }

    async def _run_workflow(
        self,
        state: ContractWorkflowState,
    ) -> ContractWorkflowState:
        """运行工作流。

        Args:
            state: 初始状态

        Returns:
            最终状态
        """

        run_id = state.get("run_id", "unknown")

        logger.info(f"[{run_id}] 开始合同审查工作流")

        try:
            import asyncio

            result = await asyncio.to_thread(
                run_contract_workflow,
                self._graph,
                state,
            )

            return result

        except Exception as e:
            logger.error(f"[{run_id}] 工作流执行失败: {e}", exc_info=True)
            return {
                **state,
                "outcome": ContractWorkflowOutcome.FAIL.value,
                "error": str(e),
            }

    def _build_response(
        self,
        result: ContractWorkflowState,
        processing_time_ms: int,
    ) -> dict:
        """构建返回结果。

        Args:
            result: 工作流结果
            processing_time_ms: 处理时间

        Returns:
            标准化的响应
        """

        outcome = result.get("outcome", ContractWorkflowOutcome.FAIL.value)

        response = {
            "run_id": result.get("run_id"),
            "contract_id": result.get("contract_file_id"),
            "contract_name": result.get("contract_name", "未命名合同"),
            "contract_type": result.get("contract_type", "其他"),
            "overall_risk_level": result.get("overall_risk_level", "unknown"),
            "status": outcome,
            "need_human_review": result.get("need_human_review", False),
            "report": result.get("review_report"),
            "processing_time_ms": processing_time_ms,
        }

        if result.get("error"):
            response["error"] = result.get("error")

        return response

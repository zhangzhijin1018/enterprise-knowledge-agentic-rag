"""Contract Agent Server - 基于 ReAct 模式的智能合同审查 Agent。

使用 LangGraph + ReAct 模式实现智能合同审查。

核心特性：
1. ReAct 模式：react_loop → reflect → report
2. RAG 增强：检索相关法规和标准模板
3. 反思机制：对审查结果进行自我校验
4. Human Review：支持高风险项人工复核
5. 多轮对话：支持追问和澄清

启动方式：
```bash
uvicorn apps.agents.contract_agent_server:app --host 0.0.0.0 --port 6003
```

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any, Optional

from python_a2a import A2AServer, AgentCard, AgentSkill, TaskStatus, TaskState

from core.agent.workflows.contract.state import (
    ContractWorkflowState,
    create_initial_contract_state,
    ContractWorkflowOutcome,
)
from core.agent.workflows.contract.graph import create_contract_graph
from core.agent.workflows.contract.nodes import ContractWorkflowNodes
from core.agent.workflows.contract.human_review_service import (
    get_human_review_service,
    create_review_from_contract_result,
)
from core.tools.local.parser import LocalDocumentParser

logger = logging.getLogger(__name__)


class ContractAgentServer(A2AServer):
    """Contract Agent A2A 服务器。

    基于 LangGraph ReAct 模式的智能合同审查 Agent。

    核心功能：
    - 合同解析
    - 法规检索
    - 条款抽取
    - 风险分析
    - 审查报告生成
    - Human Review 触发
    """

    name = "contract-agent"
    version = "2.0.0"
    description = "合同审查 Agent - 基于 LangGraph ReAct 模式的智能合同审查"

    def __init__(self, **kwargs):
        host = os.environ.get("CONTRACT_AGENT_HOST", "0.0.0.0")
        port = os.environ.get("CONTRACT_AGENT_PORT", "6003")
        url = os.environ.get("A2A_AGENT_URL", f"http://{host}:{port}")

        agent_card = AgentCard(
            name=self.name,
            description=self.description,
            url=url,
            version=self.version,
            skills=[
                AgentSkill(
                    id="contract_review",
                    name="合同审查",
                    description="基于 LangGraph ReAct 模式的智能合同审查，支持法规检索、风险识别、模板对比",
                    tags=["contract", "review", "legal", "react"],
                ),
                AgentSkill(
                    id="risk_identification",
                    name="风险识别",
                    description="智能识别合同中的潜在风险，支持高风险项人工复核",
                    tags=["risk", "compliance", "human-review"],
                ),
                AgentSkill(
                    id="rag_enhancement",
                    name="RAG 增强",
                    description="检索相关法规和标准模板，增强审查准确性",
                    tags=["rag", "law", "template"],
                ),
            ],
            capabilities={"streaming": True},
        )

        super().__init__(
            agent_card=agent_card,
            **kwargs,
        )

        # 初始化工作流组件
        self._initialize_workflow()

        logger.info(f"Contract Agent Server 初始化完成，URL: {url}")

    def _initialize_workflow(self):
        """初始化工作流组件。"""
        parser = LocalDocumentParser()
        self._nodes = ContractWorkflowNodes(
            parser=parser,
            use_reflection=True,  # 启用反思机制
        )
        self._graph = create_contract_graph(self._nodes)

    async def handle_task(self, task):
        """处理 A2A 任务。

        Args:
            task: A2A Task 对象

        Returns:
            处理后的 Task 对象
        """
        logger.info(f"[Contract Agent] 收到 A2A 任务: {task.id}")

        try:
            # 1. 提取消息内容
            query = (task.message or {}).get("content", {}).get("text", "")

            if not query:
                task.artifacts = [{
                    "parts": [{"type": "text", "text": "请提供有效的问题。"}]
                }]
                task.status = TaskStatus(state=TaskState.COMPLETED)
                return task

            # 2. 提取元数据
            metadata = task.metadata or {}
            user_id = metadata.get("user_id", "anonymous")
            user_role = metadata.get("user_role", "user")
            contract_file_id = metadata.get("contract_file_id")
            storage_uri = metadata.get("storage_uri")  # MinIO 对象路径
            contract_name = metadata.get("contract_name")
            contract_type = metadata.get("contract_type")
            business_domain = metadata.get("business_domain", "能源")
            trace_id = metadata.get("trace_id") or f"tr_{uuid.uuid4().hex[:12]}"
            conversation_id = metadata.get("conversation_id")

            # 3. 执行合同审查工作流
            result = await self._execute_review_workflow(
                run_id=task.id or f"contract_{uuid.uuid4().hex[:12]}",
                trace_id=trace_id,
                conversation_id=conversation_id,
                query=query,
                user_id=user_id,
                user_role=user_role,
                contract_file_id=contract_file_id,
                storage_uri=storage_uri,
                contract_name=contract_name,
                contract_type=contract_type,
                business_domain=business_domain,
            )

            # 4. 处理 Human Review 情况
            if result.get("outcome") == ContractWorkflowOutcome.REVIEW.value:
                # 创建 Human Review 任务
                self._create_human_review_task(result)

            # 5. 处理结果
            if result.get("outcome") == ContractWorkflowOutcome.FAIL.value:
                response_text = f"合同审查失败：{result.get('error', '未知错误')}"
            elif result.get("outcome") == ContractWorkflowOutcome.REVIEW.value:
                response_text = self._format_review_response(result)
            elif result.get("outcome") == ContractWorkflowOutcome.CLARIFY.value:
                response_text = result.get("clarification_question", "请提供更多信息")
            else:
                response_text = self._format_response(result)

            # 添加处理元数据
            task.artifacts = [{
                "parts": [{"type": "text", "text": response_text}],
                "metadata": {
                    "run_id": result.get("run_id"),
                    "outcome": result.get("outcome"),
                    "risk_level": result.get("overall_risk_level"),
                    "need_human_review": result.get("need_human_review", False),
                    "human_review_id": result.get("human_review_id"),
                    "processing_time_ms": result.get("processing_time_ms", 0),
                }
            }]
            task.status = TaskStatus(state=TaskState.COMPLETED)

            logger.info(
                f"[Contract Agent] 任务处理完成 | "
                f"outcome={result.get('outcome')} | "
                f"risk_level={result.get('overall_risk_level')} | "
                f"need_review={result.get('need_human_review')}"
            )
            return task

        except Exception as e:
            logger.error(f"[Contract Agent] 处理失败: {e}", exc_info=True)
            task.artifacts = [{
                "parts": [{"type": "text", "text": f"处理失败: {str(e)}"}]
            }]
            task.status = TaskStatus(state=TaskState.COMPLETED)
            return task

    def _create_human_review_task(self, result: ContractWorkflowState) -> Optional[str]:
        """创建 Human Review 任务。

        Args:
            result: 工作流执行结果

        Returns:
            复核任务 ID
        """
        try:
            high_risks = [
                r for r in result.get("identified_risks", [])
                if r.get("risk_type") == "high"
            ]

            if not high_risks:
                return None

            # 从结果中提取合同摘要
            contract_summary = self._generate_contract_summary(result)

            task = create_review_from_contract_result(
                run_id=result.get("run_id", ""),
                contract_name=result.get("contract_name", "未知合同"),
                high_risk_items=high_risks,
                contract_type=result.get("contract_type"),
                contract_summary=contract_summary,
            )

            logger.info(
                f"[Contract Agent] 创建 Human Review 任务 | "
                f"review_id={task.review_id} | "
                f"contract={result.get('contract_name')}"
            )

            return task.review_id

        except Exception as e:
            logger.error(f"[Contract Agent] 创建复核任务失败: {e}", exc_info=True)
            return None

    def _generate_contract_summary(self, result: dict) -> str:
        """生成合同摘要。"""
        clauses = result.get("extracted_clauses", [])
        parties = result.get("parties", [])

        party_names = [p.get("name", "") for p in parties]
        clause_count = len(clauses)

        summary = f"合同条款 {clause_count} 条"
        if party_names:
            summary += f"，当事人：{'、'.join(party_names[:2])}"

        return summary

    async def _execute_review_workflow(
        self,
        run_id: str,
        trace_id: str,
        conversation_id: Optional[str],
        query: str,
        user_id: str,
        user_role: str,
        contract_file_id: Optional[str],
        storage_uri: Optional[str],
        contract_name: Optional[str],
        contract_type: Optional[str],
        business_domain: str = "能源",
    ) -> ContractWorkflowState:
        """执行合同审查工作流（ReAct 模式）。"""
        start_time = time.time()

        # 参数校验
        if not contract_file_id:
            contract_file_id = f"contract_{uuid.uuid4().hex[:8]}"

        # 创建初始状态
        initial_state = create_initial_contract_state(
            run_id=run_id,
            contract_file_id=contract_file_id,
            user_id=user_id,
            user_role=user_role,
            contract_name=contract_name or query[:50],
            contract_type=contract_type,
            business_domain=business_domain,
            query=query,
            storage_uri=storage_uri,
            trace_id=trace_id,
            conversation_id=conversation_id,
        )

        try:
            # 执行工作流
            result = self._graph.invoke(initial_state)
            result["processing_time_ms"] = int((time.time() - start_time) * 1000)

            return result

        except Exception as e:
            logger.error(f"[{run_id}] 工作流执行失败: {e}", exc_info=True)
            return {
                **initial_state,
                "outcome": ContractWorkflowOutcome.FAIL.value,
                "error": str(e),
                "processing_time_ms": int((time.time() - start_time) * 1000),
            }

    def _format_response(self, result: ContractWorkflowState) -> str:
        """格式化响应文本（正常完成）。"""
        report = result.get("review_report", {})
        if not report:
            return "合同审查完成，但未生成审查报告。"

        lines = []

        # 标题
        lines.append("=" * 60)
        lines.append("📋 合同审查报告")
        lines.append("=" * 60)
        lines.append("")

        # 基本信息
        contract_info = report.get("contract_info", {})
        lines.append(f"📌 合同名称：{contract_info.get('name', result.get('contract_name', '未知'))}")
        lines.append(f"📌 合同类型：{contract_info.get('type', result.get('contract_type', '未知'))}")
        lines.append("")

        # 审查摘要
        review_summary = report.get("review_summary", {})
        lines.append("📊 审查摘要：")
        lines.append(f"   • 条款总数：{review_summary.get('total_clauses', 0)}")
        lines.append(f"   • 高风险：{review_summary.get('high_risk_count', result.get('high_risk_count', 0))} 项")
        lines.append(f"   • 中风险：{review_summary.get('medium_risk_count', result.get('medium_risk_count', 0))} 项")
        lines.append(f"   • 低风险：{result.get('low_risk_count', 0)} 项")
        lines.append("")

        # 风险概要
        risk_summary = result.get("risk_summary", report.get("risk_summary", ""))
        if risk_summary:
            lines.append("⚠️ 风险概要：")
            lines.append(f"   {risk_summary}")
            lines.append("")

        # 重点关注项
        key_concerns = report.get("key_concerns", result.get("key_concerns", []))
        if key_concerns:
            lines.append("🔴 重点关注项：")
            for concern in key_concerns[:3]:
                lines.append(f"   • {concern}")
            lines.append("")

        # 审查结论
        conclusion = report.get("conclusion", result.get("conclusion", ""))
        if conclusion:
            lines.append("✅ 审查结论：")
            lines.append(f"   {conclusion}")
            lines.append("")

        # 修改建议
        suggestions = report.get("suggestions", result.get("suggestions", []))
        if suggestions:
            lines.append("💡 修改建议：")
            for i, suggestion in enumerate(suggestions[:5], 1):
                lines.append(f"   {i}. {suggestion}")
            lines.append("")

        # 处理信息
        lines.append(f"⏱️ 处理时间：{result.get('processing_time_ms', 0) / 1000:.2f} 秒")
        lines.append(f"🔖 Run ID：{result.get('run_id', '')}")
        lines.append("=" * 60)

        return "\n".join(lines)

    def _format_review_response(self, result: ContractWorkflowState) -> str:
        """格式化响应文本（需要人工复核）。"""
        lines = []

        lines.append("=" * 60)
        lines.append("⚠️ 合同审查需要人工复核")
        lines.append("=" * 60)
        lines.append("")

        lines.append("系统审查发现以下高风险项，需要法务人员人工复核：")
        lines.append("")

        pending_risks = result.get("pending_risks", [])
        for risk in pending_risks:
            lines.append(
                f"🔴 [{risk.get('risk_id', '')}] {risk.get('risk_description', '')}"
            )
            lines.append(f"   相关条款：{risk.get('related_clause', '未知')}")
            lines.append(f"   风险类别：{risk.get('risk_category', '')}")
            lines.append(f"   建议：{risk.get('suggestion', '')}")
            lines.append("")

        # 添加审查摘要
        high_count = result.get("high_risk_count", len(pending_risks))
        medium_count = result.get("medium_risk_count", 0)
        lines.append(f"📊 风险统计：高风险 {high_count} 项，中风险 {medium_count} 项")
        lines.append("")

        lines.append(f"📋 复核任务 ID：{result.get('human_review_id', '')}")
        lines.append("")
        lines.append("请法务人员登录系统进行复核。")
        lines.append("=" * 60)

        return "\n".join(lines)


# ==================== Agent Server 启动入口 ====================


def create_a2a_app():
    """创建 A2A 应用。"""
    a2a_server = ContractAgentServer()

    port = int(os.environ.get("CONTRACT_AGENT_PORT", "6003"))
    host = os.environ.get("CONTRACT_AGENT_HOST", "0.0.0.0")

    logger.info(f"Contract Agent Server 初始化完成")
    logger.info(f"A2A 端点: http://{host}:{port}/a2a")
    logger.info(f"Agent Card: {a2a_server.agent_card.name}")

    from python_a2a import run_server
    run_server(a2a_server, host=host, port=port)


# 主入口
if __name__ == "__main__":
    create_a2a_app()

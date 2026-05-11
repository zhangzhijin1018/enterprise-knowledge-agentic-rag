"""合同审查 Agent 单元测试。

测试内容：
1. Tools 测试
2. State 测试
3. Reflection 测试
4. Human Review Service 测试
5. Workflow 集成测试

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import pytest
from datetime import datetime
from typing import Any, Dict, List, Optional

# ==================== Tools 测试 ====================


class TestContractTools:
    """合同审核工具测试。"""

    def test_get_contract_tools(self):
        """测试获取工具列表。"""
        from core.agent.workflows.contract.tools import get_contract_tools

        tools = get_contract_tools()

        assert len(tools) == 8, "应该有8个工具"
        tool_names = [t.name for t in tools]
        expected_names = [
            "parse_contract",
            "search_laws",
            "search_templates",
            "search_history",
            "extract_clauses",
            "analyze_risk",
            "generate_report",
            "request_human_review",
        ]
        for name in expected_names:
            assert name in tool_names, f"缺少工具: {name}"

    def test_get_tool_by_name(self):
        """测试根据名称获取工具。"""
        from core.agent.workflows.contract.tools import get_tool_by_name

        # 获取存在的工具
        tool = get_tool_by_name("parse_contract")
        assert tool is not None
        assert tool.name == "parse_contract"

        # 获取不存在的工具
        tool = get_tool_by_name("non_existent_tool")
        assert tool is None

    def test_search_laws_tool(self):
        """测试法规检索工具。"""
        from core.agent.workflows.contract.tools import search_laws

        result = search_laws.invoke({
            "query": "合同违约金",
            "contract_type": "采购合同",
            "business_domain": "能源",
            "top_k": 3,
        })

        assert result["status"] == "success"
        assert result["count"] > 0
        assert "laws" in result

        # 验证返回的法规结构
        law = result["laws"][0]
        assert "law_id" in law
        assert "title" in law
        assert "relevance" in law

    def test_search_templates_tool(self):
        """测试模板检索工具。"""
        from core.agent.workflows.contract.tools import search_templates

        result = search_templates.invoke({
            "contract_type": "服务合同",
            "business_domain": "能源",
            "top_k": 2,
        })

        assert result["status"] == "success"
        assert result["count"] > 0

    def test_extract_clauses_tool(self):
        """测试条款抽取工具。"""
        from core.agent.workflows.contract.tools import extract_clauses

        contract_text = """
        甲方：新疆能源集团有限公司
        乙方：某某设备有限公司

        第一条 合同标的
        甲方向乙方采购光伏发电设备一批。

        第二条 合同价款
        合同总金额为人民币壹仟万元整。

        第三条 付款方式
        甲方应在设备验收合格后30日内支付全部款项。

        第四条 无条件解除
        甲方有权无条件解除本合同。
        """

        result = extract_clauses.invoke({
            "contract_text": contract_text,
            "contract_type": "采购合同",
        })

        assert result["status"] == "success"
        assert len(result["clauses"]) >= 3, "应该抽取到至少3个条款"
        assert len(result["parties"]) >= 2, "应该抽取到至少2个当事人"

        # 验证风险识别
        has_risk = any(
            "高风险" in r or "无条件" in r
            for clause in result["clauses"]
            for r in clause.get("risk_indicators", [])
        )
        assert has_risk, "应该识别到无条件解除风险"

    def test_analyze_risk_tool(self):
        """测试风险分析工具。"""
        from core.agent.workflows.contract.tools import analyze_risk

        clauses = [
            {
                "clause_id": "第1条",
                "clause_type": "价款条款",
                "clause_title": "合同价款",
                "clause_content": "合同总金额为人民币壹仟万元整。",
                "risk_indicators": [],
            },
            {
                "clause_id": "第2条",
                "clause_type": "其他条款",
                "clause_title": "无条件解除",
                "clause_content": "甲方有权无条件解除本合同。",
                "risk_indicators": ["[高风险] 无条件解除"],
            },
        ]

        result = analyze_risk.invoke({
            "clauses": clauses,
            "contract_type": "采购合同",
        })

        assert result["status"] == "success"
        assert result["overall_level"] == "high", "应该识别为高风险"
        assert result["need_human_review"] is True, "高风险需要人工复核"
        assert result["high_risk_count"] >= 1, "应该有高风险项"

    def test_generate_report_tool(self):
        """测试报告生成工具。"""
        from core.agent.workflows.contract.tools import generate_report

        result = generate_report.invoke({
            "contract_name": "光伏设备采购合同",
            "contract_type": "采购合同",
            "clauses": [
                {"clause_id": "第1条", "clause_title": "合同价款"},
            ],
            "parties": [
                {"name": "甲方", "role": "甲方"},
                {"name": "乙方", "role": "乙方"},
            ],
            "risks": [
                {
                    "risk_id": "R001",
                    "risk_type": "high",
                    "risk_description": "无条件解除",
                    "related_clause": "第2条",
                    "suggestion": "建议删除该条款",
                }
            ],
        })

        assert result["status"] == "success"
        assert "report" in result
        assert "conclusion" in result

        report = result["report"]
        assert "report_id" in report
        assert "review_summary" in report
        assert "high_risk_count" in report["review_summary"]

    def test_request_human_review_tool(self):
        """测试请求人工复核工具。"""
        from core.agent.workflows.contract.tools import request_human_review

        result = request_human_review.invoke({
            "high_risk_items": [
                {
                    "risk_id": "R001",
                    "risk_description": "无条件解除",
                }
            ],
            "reason": "发现高风险条款",
        })

        assert result["status"] == "success"
        assert "review_id" in result
        assert result["review_status"] == "pending"


# ==================== State 测试 ====================


class TestContractState:
    """合同审查状态测试。"""

    def test_create_initial_state(self):
        """测试创建初始状态。"""
        from core.agent.workflows.contract.state import (
            create_initial_contract_state,
            ContractWorkflowStage,
            AgentThought,
        )

        state = create_initial_contract_state(
            run_id="test_run_001",
            contract_file_id="contract_001",
            user_id="user_001",
            user_role="legal",
            contract_name="测试合同",
            contract_type="采购合同",
        )

        assert state["run_id"] == "test_run_001"
        assert state["contract_file_id"] == "contract_001"
        assert state["current_stage"] == ContractWorkflowStage.ENTRY.value
        assert state["agent_status"] == AgentThought.IDLE.value
        assert state["outcome"] == "continue"

    def test_state_enums(self):
        """测试状态枚举。"""
        from core.agent.workflows.contract.state import (
            ContractWorkflowStage,
            ContractWorkflowOutcome,
            AgentThought,
        )

        # 测试阶段枚举
        assert ContractWorkflowStage.ENTRY.value == "entry"
        assert ContractWorkflowStage.REACT_LOOP.value == "react_loop"
        assert ContractWorkflowStage.REFLECT.value == "reflect"
        assert ContractWorkflowStage.FINISH.value == "finish"

        # 测试结果枚举
        assert ContractWorkflowOutcome.CONTINUE.value == "continue"
        assert ContractWorkflowOutcome.REVIEW.value == "review"
        assert ContractWorkflowOutcome.FINISH.value == "finish"

        # 测试思考状态枚举
        assert AgentThought.IDLE.value == "idle"
        assert AgentThought.THINKING.value == "thinking"
        assert AgentThought.WAITING_REVIEW.value == "waiting_review"


# ==================== Reflection 测试 ====================


class TestReflection:
    """反思引擎测试。"""

    def test_simple_reflection(self):
        """测试简化反思器。"""
        from core.agent.workflows.contract.reflection import SimpleReflection

        # 测试正常情况
        result = SimpleReflection.reflect(
            clauses=[
                {"clause_id": "第1条", "clause_type": "价款条款"},
                {"clause_id": "第2条", "clause_type": "履行期限"},
            ],
            risks=[
                {"risk_type": "high", "related_clause": "第3条"},
            ],
            conclusion="该合同存在高风险条款",
        )

        assert result is not None
        assert result.confidence in ["高", "中", "低"]
        assert isinstance(result.issues, list)

    def test_reflection_with_empty_clauses(self):
        """测试空条款的反思。"""
        from core.agent.workflows.contract.reflection import SimpleReflection

        result = SimpleReflection.reflect(
            clauses=[],
            risks=[],
            conclusion="无风险",
        )

        # 应该发现问题
        has_issue = any(
            "条款" in i.get("description", "")
            for i in result.issues
        )
        assert has_issue, "应该发现条款缺失问题"


# ==================== Human Review Service 测试 ====================


class TestHumanReviewService:
    """Human Review 服务测试。"""

    def test_create_review_task(self):
        """测试创建复核任务。"""
        from core.agent.workflows.contract.human_review_service import (
            HumanReviewService,
            ReviewPriority,
        )

        service = HumanReviewService()

        task = service.create_review_task(
            run_id="run_001",
            contract_name="测试采购合同",
            risk_items=[
                {
                    "risk_id": "R001",
                    "risk_type": "high",
                    "risk_description": "无条件解除",
                    "related_clause": "第5条",
                    "suggestion": "删除该条款",
                }
            ],
            review_reason="发现高风险条款",
            contract_type="采购合同",
            priority=ReviewPriority.HIGH,
        )

        assert task is not None
        assert task.review_id.startswith("review_")
        assert task.contract_name == "测试采购合同"
        assert task.status == "pending"
        assert len(task.risk_items) == 1

    def test_update_review_task(self):
        """测试更新复核任务。"""
        from core.agent.workflows.contract.human_review_service import (
            HumanReviewService,
            ReviewDecision,
        )

        service = HumanReviewService()

        # 创建任务
        task = service.create_review_task(
            run_id="run_001",
            contract_name="测试合同",
            risk_items=[{"risk_id": "R001", "risk_type": "high"}],
            review_reason="测试",
        )

        # 更新任务
        updated = service.update_review_task(
            review_id=task.review_id,
            reviewer_id="reviewer_001",
            reviewer_name="张三",
            status="in_progress",
        )

        assert updated is not None
        assert updated.reviewer_id == "reviewer_001"
        assert updated.status == "in_progress"

    def test_submit_review_result(self):
        """测试提交复核结果。"""
        from core.agent.workflows.contract.human_review_service import (
            HumanReviewService,
            ReviewDecision,
        )

        service = HumanReviewService()

        # 创建任务
        task = service.create_review_task(
            run_id="run_001",
            contract_name="测试合同",
            risk_items=[{"risk_id": "R001", "risk_type": "high"}],
            review_reason="测试",
        )

        # 提交结果
        completed = service.submit_review_result(
            review_id=task.review_id,
            reviewer_id="reviewer_001",
            reviewer_name="李四",
            decision=ReviewDecision.APPROVED,
            comments="审核通过",
        )

        assert completed is not None
        assert completed.decision == ReviewDecision.APPROVED
        assert completed.status == "completed"
        assert completed.completed_at is not None

    def test_list_pending_reviews(self):
        """测试列出待复核任务。"""
        from core.agent.workflows.contract.human_review_service import (
            HumanReviewService,
            ReviewPriority,
        )

        service = HumanReviewService()

        # 创建多个任务
        for i in range(3):
            service.create_review_task(
                run_id=f"run_{i:03d}",
                contract_name=f"测试合同{i}",
                risk_items=[{"risk_id": f"R{i:03d}"}],
                review_reason="测试",
                priority=ReviewPriority.HIGH if i == 0 else ReviewPriority.NORMAL,
            )

        # 查询待复核
        pending = service.list_pending_reviews()

        assert len(pending) == 3
        # 验证优先级排序
        if len(pending) >= 2:
            assert pending[0].priority == ReviewPriority.HIGH


# ==================== Workflow 集成测试 ====================


class TestContractWorkflow:
    """合同审查工作流集成测试。"""

    def test_create_workflow_graph(self):
        """测试创建工作流图。"""
        from core.agent.workflows.contract.nodes import ContractWorkflowNodes
        from core.agent.workflows.contract.graph import create_contract_graph

        nodes = ContractWorkflowNodes()
        graph = create_contract_graph(nodes)

        assert graph is not None

    @pytest.mark.asyncio
    async def test_workflow_nodes_initialization(self):
        """测试工作流节点初始化。"""
        from core.agent.workflows.contract.nodes import ContractWorkflowNodes

        nodes = ContractWorkflowNodes()

        assert nodes is not None
        assert len(nodes.tools) == 8
        assert nodes.tool_map is not None

    def test_decide_next_tool(self):
        """测试工具决策逻辑。"""
        from core.agent.workflows.contract.nodes import ContractWorkflowNodes

        nodes = ContractWorkflowNodes()

        # 初始状态，应该先解析合同
        next_tool = nodes._decide_next_tool([], {})
        assert next_tool == "parse_contract"

        # 解析完成后，应该检索法规
        next_tool = nodes._decide_next_tool(["parse_contract"], {})
        assert next_tool == "search_laws"

        # 检索法规后，应该检索模板
        next_tool = nodes._decide_next_tool(["parse_contract", "search_laws"], {})
        assert next_tool == "search_templates"

        # 所有工具完成后，返回 None
        next_tool = nodes._decide_next_tool(
            ["parse_contract", "search_laws", "search_templates", "extract_clauses", "analyze_risk"],
            {}
        )
        assert next_tool is None


# ==================== 性能测试 ====================


class TestContractPerformance:
    """合同审查性能测试。"""

    def test_tool_execution_time(self):
        """测试工具执行时间。"""
        import time
        from core.agent.workflows.contract.tools import search_laws

        start = time.time()
        result = search_laws.invoke({
            "query": "合同条款",
            "top_k": 5,
        })
        elapsed = time.time() - start

        assert result["status"] == "success"
        # 执行时间应该小于1秒
        assert elapsed < 1.0, f"工具执行时间过长: {elapsed:.2f}秒"


# ==================== 运行测试 ====================


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

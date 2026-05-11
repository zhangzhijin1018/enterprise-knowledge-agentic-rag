"""评估 API 接口。

提供评估相关的 REST API 接口：
1. POST /api/v1/evaluation/contract - 评估单个合同
2. POST /api/v1/evaluation/contract/batch - 批量评估
3. GET /api/v1/evaluation/contract/{report_id} - 获取评估报告
4. GET /api/v1/evaluation/reports - 获取评估报告列表
5. GET /api/v1/evaluation/statistics - 获取评估统计

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field

from core.evaluation.contract_evaluator import (
    ContractEvaluator,
    ContractJudgeConfig,
    ContractTestSuite,
    ContractTestCase,
    ContractGroundTruth,
    ContractTestDataGenerator,
    ReportGenerator,
    ContractEvaluationReport,
    JudgeModel,
    EvaluationMode,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/evaluation", tags=["评估"])


# ==================== 请求模型 ====================


class ContractEvaluationRequest(BaseModel):
    """合同评估请求。"""

    contract_id: str = Field(description="合同ID")
    contract_text: str = Field(description="合同文本内容")
    contract_name: str = Field(description="合同名称")
    contract_type: str = Field(description="合同类型（可选，Agent会自动识别）")

    ground_truth: dict[str, Any] | None = Field(
        default=None,
        description="标准答案（可选）"
    )

    judge_model: str = Field(
        default="qwen-32b",
        description="评估模型：qwen-32b, qwen-14b, qwen-7b"
    )

    async_execution: bool = Field(
        default=False,
        description="是否异步执行"
    )


class BatchEvaluationRequest(BaseModel):
    """批量评估请求。"""

    test_suite_id: str | None = Field(
        default=None,
        description="测试套件ID（从数据库加载）"
    )

    test_suite_data: dict[str, Any] | None = Field(
        default=None,
        description="测试套件数据（直接提供）"
    )

    generate_synthetic: bool = Field(
        default=False,
        description="是否生成合成测试数据"
    )

    synthetic_count: int = Field(
        default=10,
        description="合成测试用例数量"
    )

    judge_model: str = Field(
        default="qwen-32b",
        description="评估模型"
    )

    max_concurrent: int = Field(
        default=5,
        description="最大并发数"
    )


class EvaluationReportResponse(BaseModel):
    """评估报告响应。"""

    report_id: str
    report_title: str
    report_type: str
    generated_at: str
    total_cases: int
    passed_cases: int
    failed_cases: int
    pass_rate: float
    overall_score: float
    download_url: str


# ==================== 评估服务 ====================


class EvaluationService:
    """评估服务。"""

    def __init__(self) -> None:
        """初始化评估服务。"""
        self._evaluator: ContractEvaluator | None = None
        self._report_generator = ReportGenerator()
        self._reports: dict[str, ContractEvaluationReport] = {}

    def get_evaluator(self, judge_model: str) -> ContractEvaluator:
        """获取评估器。"""
        config = ContractJudgeConfig(
            judge_model=JudgeModel(judge_model),
            evaluation_mode=EvaluationMode.OFFLINE_BATCH,
        )
        return ContractEvaluator(llm_judge_config=config)

    async def evaluate_single(
        self,
        request: ContractEvaluationRequest,
    ) -> ContractEvaluationReport:
        """评估单个合同。"""
        # 创建测试用例
        test_case = ContractTestCase(
            case_id=request.contract_id,
            contract_name=request.contract_name,
            contract_type=request.contract_type,
            contract_text=request.contract_text,
            ground_truth=ContractGroundTruth.from_dict(
                request.ground_truth or {}
            ),
        )

        # 获取评估器
        evaluator = self.get_evaluator(request.judge_model)

        # 执行评估（模拟 Agent 输出）
        # 实际场景中应该调用真实的 Agent
        agent_output = {
            "contract_type": request.contract_type,
            "clauses": [],
            "risks": [],
            "review_report": {},
        }

        # 执行评估
        result = await evaluator.evaluate_single(
            test_case=test_case,
            agent_output=agent_output,
        )

        # 生成报告
        report = self._report_generator.generate_single_report(
            evaluation_result=result,
            judge_model=request.judge_model,
            judge_config={"judge_model": request.judge_model},
        )

        # 存储报告
        self._reports[report.report_id] = report

        return report

    async def evaluate_batch(
        self,
        request: BatchEvaluationRequest,
    ) -> ContractEvaluationReport:
        """批量评估。"""
        test_suite: ContractTestSuite

        if request.test_suite_data:
            # 从提供的数据加载
            test_suite = ContractTestSuite.from_dict(request.test_suite_data)
        elif request.generate_synthetic:
            # 生成合成数据
            generator = ContractTestDataGenerator()
            cases = []
            for i in range(request.synthetic_count):
                case = generator.generate_synthetic_case(
                    contract_type="procurement" if i % 2 == 0 else "service",
                    include_risks=True,
                    difficulty="medium",
                )
                cases.append(case)

            test_suite = ContractTestSuite(
                suite_id=f"synthetic_{uuid.uuid4().hex[:8]}",
                suite_name="合成测试套件",
                suite_description="自动生成的合成测试数据",
                test_cases=cases,
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="必须提供 test_suite_data 或设置 generate_synthetic=true"
            )

        # 获取评估器
        evaluator = self.get_evaluator(request.judge_model)

        # 执行批量评估
        results = await evaluator.evaluate_batch(
            test_suite=test_suite,
            max_concurrent=request.max_concurrent,
        )

        # 生成报告
        report = self._report_generator.generate_batch_report(
            evaluation_results=results,
            judge_model=request.judge_model,
            judge_config={
                "judge_model": request.judge_model,
                "max_concurrent": request.max_concurrent,
            },
            test_suite_info={
                "suite_id": test_suite.suite_id,
                "total_cases": test_suite.total_cases,
            },
        )

        # 存储报告
        self._reports[report.report_id] = report

        return report

    def get_report(self, report_id: str) -> ContractEvaluationReport | None:
        """获取评估报告。"""
        return self._reports.get(report_id)

    def list_reports(self) -> list[dict[str, Any]]:
        """列出所有评估报告。"""
        return [
            {
                "report_id": r.report_id,
                "report_title": r.report_title,
                "report_type": r.report_type,
                "generated_at": r.generated_at,
                "total_cases": r.total_cases,
                "passed_cases": r.passed_cases,
                "pass_rate": r.passed_cases / r.total_cases if r.total_cases > 0 else 0,
                "overall_score": r.summary_statistics.get("avg_overall", 0),
            }
            for r in self._reports.values()
        ]


# 全局评估服务实例
evaluation_service = EvaluationService()


# ==================== API 路由 ====================


@router.post("/contract", response_model=dict[str, Any])
async def evaluate_contract(request: ContractEvaluationRequest):
    """评估单个合同。

    Args:
        request: 合同评估请求

    Returns:
        评估报告
    """
    logger.info(f"收到评估请求: contract_id={request.contract_id}")

    try:
        report = await evaluation_service.evaluate_single(request)
        return report.to_dict()

    except Exception as e:
        logger.error(f"评估失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/contract/batch", response_model=dict[str, Any])
async def evaluate_contract_batch(
    request: BatchEvaluationRequest,
    background_tasks: BackgroundTasks,
):
    """批量评估合同。

    Args:
        request: 批量评估请求
        background_tasks: 后台任务

    Returns:
        评估任务信息
    """
    logger.info(f"收到批量评估请求: synthetic={request.generate_synthetic}")

    try:
        # 同步执行（简化实现）
        report = await evaluation_service.evaluate_batch(request)
        return report.to_dict()

    except Exception as e:
        logger.error(f"批量评估失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/contract/{report_id}", response_model=dict[str, Any])
async def get_evaluation_report(report_id: str):
    """获取评估报告。

    Args:
        report_id: 报告ID

    Returns:
        评估报告
    """
    report = evaluation_service.get_report(report_id)

    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")

    return report.to_dict()


@router.get("/reports", response_model=list[dict[str, Any]])
async def list_evaluation_reports():
    """获取评估报告列表。

    Returns:
        报告列表
    """
    return evaluation_service.list_reports()


@router.get("/statistics", response_model=dict[str, Any])
async def get_evaluation_statistics():
    """获取评估统计信息。

    Returns:
        统计信息
    """
    reports = evaluation_service.list_reports()

    if not reports:
        return {
            "total_reports": 0,
            "total_cases": 0,
            "average_pass_rate": 0,
            "average_score": 0,
        }

    total_cases = sum(r["total_cases"] for r in reports)
    total_passed = sum(r["passed_cases"] for r in reports)
    total_score = sum(r["overall_score"] for r in reports)

    return {
        "total_reports": len(reports),
        "total_cases": total_cases,
        "average_pass_rate": total_passed / total_cases if total_cases > 0 else 0,
        "average_score": total_score / len(reports) if reports else 0,
        "recent_reports": reports[-10:] if len(reports) > 10 else reports,
    }


@router.get("/health")
async def evaluation_health():
    """评估服务健康检查。"""
    return {"status": "healthy", "service": "contract-evaluator"}

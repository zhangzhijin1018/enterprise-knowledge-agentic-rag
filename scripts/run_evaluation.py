#!/usr/bin/env python3
"""合同审核 Agent 评估脚本。

用法：
    python scripts/run_evaluation.py                    # 运行完整评估
    python scripts/run_evaluation.py --synthetic 50    # 生成50个合成测试用例
    python scripts/run_evaluation.py --suite data/test_suite.json  # 使用指定测试套件
    python scripts/run_evaluation.py --judge-model qwen-7b  # 使用轻量模型

Author: Enterprise Knowledge Agentic RAG Platform
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.evaluation.contract_evaluator import (
    ContractEvaluator,
    ContractJudgeConfig,
    ContractTestSuite,
    ContractTestDataGenerator,
    ReportGenerator,
    JudgeModel,
    EvaluationMode,
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def run_evaluation(
    test_suite: ContractTestSuite,
    judge_model: str,
    output_dir: Path,
    max_concurrent: int = 5,
) -> None:
    """运行评估。

    Args:
        test_suite: 测试套件
        judge_model: 评估模型
        output_dir: 输出目录
        max_concurrent: 最大并发数
    """
    logger.info("=" * 60)
    logger.info("合同审核 Agent 评估")
    logger.info("=" * 60)
    logger.info(f"测试用例数: {test_suite.total_cases}")
    logger.info(f"评估模型: {judge_model}")
    logger.info(f"最大并发: {max_concurrent}")
    logger.info("-" * 60)

    # 创建评估器
    config = ContractJudgeConfig(
        judge_model=JudgeModel(judge_model),
        evaluation_mode=EvaluationMode.OFFLINE_BATCH,
        enable_reasoning=True,
        enable_bias_mitigation=True,
        use_cached_judgments=True,
    )
    evaluator = ContractEvaluator(llm_judge_config=config)
    report_generator = ReportGenerator()

    # 执行评估
    start_time = datetime.now()

    results = await evaluator.evaluate_batch(
        test_suite=test_suite,
        max_concurrent=max_concurrent,
        progress_callback=lambda current, total: logger.info(
            f"进度: {current}/{total} ({current/total*100:.1f}%)"
        ),
    )

    elapsed = (datetime.now() - start_time).total_seconds()

    # 生成报告
    logger.info("-" * 60)
    logger.info("生成评估报告...")

    report = report_generator.generate_batch_report(
        evaluation_results=results,
        judge_model=judge_model,
        judge_config=config.to_dict(),
        test_suite_info={
            "suite_id": test_suite.suite_id,
            "suite_name": test_suite.suite_name,
            "total_cases": test_suite.total_cases,
        },
    )

    # 保存报告
    output_dir.mkdir(parents=True, exist_ok=True)

    # JSON 报告
    json_path = output_dir / f"evaluation_report_{report.report_id}.json"
    report_generator.save_report(report, json_path, format="json")
    logger.info(f"JSON 报告: {json_path}")

    # Markdown 报告
    md_path = output_dir / f"evaluation_report_{report.report_id}.md"
    report_generator.save_report(report, md_path, format="markdown")
    logger.info(f"Markdown 报告: {md_path}")

    # CSV 报告
    csv_path = output_dir / f"evaluation_results_{report.report_id}.csv"
    report_generator.save_report(report, csv_path, format="csv")
    logger.info(f"CSV 报告: {csv_path}")

    # 打印汇总
    logger.info("=" * 60)
    logger.info("评估完成")
    logger.info("=" * 60)
    logger.info(f"总用例数: {report.total_cases}")
    logger.info(f"通过数: {report.passed_cases}")
    logger.info(f"失败数: {report.failed_cases}")
    logger.info(f"通过率: {report.passed_cases / report.total_cases * 100:.1f}%")
    logger.info(f"平均得分: {report.summary_statistics.get('avg_overall', 0):.2f}")
    logger.info(f"耗时: {elapsed:.1f}秒")
    logger.info("-" * 60)
    logger.info("各维度得分:")
    for dim, score in report.dimension_scores.items():
        logger.info(f"  {dim}: {score:.2f}")
    logger.info("-" * 60)

    if report.common_issues:
        logger.info("常见问题:")
        for issue in report.common_issues[:3]:
            logger.info(f"  - {issue['title']}: {issue['impact']}")
    logger.info("=" * 60)


def create_synthetic_test_suite(count: int) -> ContractTestSuite:
    """创建合成测试套件。

    Args:
        count: 测试用例数量

    Returns:
        测试套件
    """
    logger.info(f"生成 {count} 个合成测试用例...")

    generator = ContractTestDataGenerator()
    cases = []

    contract_types = ["procurement", "service", "construction", "lease"]
    difficulties = ["easy", "medium", "hard"]

    for i in range(count):
        contract_type = contract_types[i % len(contract_types)]
        difficulty = difficulties[i % len(difficulties)]

        case = generator.generate_synthetic_case(
            contract_type=contract_type,
            include_risks=(difficulty != "easy"),
            difficulty=difficulty,
        )
        cases.append(case)

    suite = ContractTestSuite(
        suite_id=f"synthetic_{datetime.now().strftime('%Y%m%d%H%M%S')}",
        suite_name="合成测试套件",
        suite_description=f"自动生成的 {count} 个测试用例",
        test_cases=cases,
    )

    logger.info(f"生成完成: {suite.total_cases} 个用例")
    logger.info(f"按难度分布: {suite.by_difficulty}")
    logger.info(f"按类型分布: {suite.by_contract_type}")

    return suite


def load_test_suite(path: str | Path) -> ContractTestSuite:
    """从文件加载测试套件。

    Args:
        path: 文件路径

    Returns:
        测试套件
    """
    path = Path(path)
    logger.info(f"加载测试套件: {path}")

    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")

    suite = ContractTestSuite.from_json_file(path)
    logger.info(f"加载完成: {suite.total_cases} 个用例")

    return suite


def main():
    """主函数。"""
    parser = argparse.ArgumentParser(
        description="合同审核 Agent 评估脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/run_evaluation.py --synthetic 50
  python scripts/run_evaluation.py --suite data/test_suite.json
  python scripts/run_evaluation.py --synthetic 100 --judge-model qwen-7b
        """,
    )

    parser.add_argument(
        "--synthetic",
        type=int,
        default=0,
        help="生成合成测试用例数量（与 --suite 互斥）",
    )
    parser.add_argument(
        "--suite",
        type=str,
        default="",
        help="测试套件文件路径",
    )
    parser.add_argument(
        "--judge-model",
        type=str,
        default="qwen-32b",
        choices=["qwen-32b", "qwen-14b", "qwen-7b"],
        help="评估模型",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="outputs/evaluation",
        help="输出目录",
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=5,
        help="最大并发数",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="详细输出",
    )

    args = parser.parse_args()

    # 设置日志级别
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # 加载或生成测试套件
    if args.synthetic > 0:
        test_suite = create_synthetic_test_suite(args.synthetic)
    elif args.suite:
        test_suite = load_test_suite(args.suite)
    else:
        # 默认生成 20 个测试用例
        test_suite = create_synthetic_test_suite(20)

    # 运行评估
    output_dir = Path(args.output_dir)

    try:
        asyncio.run(run_evaluation(
            test_suite=test_suite,
            judge_model=args.judge_model,
            output_dir=output_dir,
            max_concurrent=args.max_concurrent,
        ))
    except KeyboardInterrupt:
        logger.info("评估被用户中断")
        sys.exit(1)
    except Exception as e:
        logger.error(f"评估失败: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

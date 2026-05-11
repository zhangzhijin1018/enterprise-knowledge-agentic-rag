"""合同审查示例脚本。

演示如何使用合同审查 Agent 进行合同审核。

使用方法：
```bash
# 方式1：直接运行
python scripts/test_contract_review.py

# 方式2：带参数运行
python scripts/test_contract_review.py --contract-id contract_001 --type 采购合同
```

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ==================== 示例合同文本 ====================


SAMPLE_CONTRACTS = {
    "采购合同": """
采购合同

甲方：新疆能源集团有限公司
乙方：某某设备制造有限公司

签订日期：2024年1月15日

第一条 合同标的
甲方向乙方采购光伏发电设备一批，包括光伏组件、逆变器、支架等设备。

第二条 合同价款
合同总金额为人民币壹仟万元整（10000000元）。

第三条 付款方式
1. 预付款：合同签订后5个工作日内，甲方向乙方支付合同总价款的30%作为预付款；
2. 进度款：设备发货前，甲方向乙方支付合同总价款的50%；
3. 验收款：设备安装调试完毕并验收合格后30日内，甲方向乙方支付合同总价款的15%；
4. 质保金：剩余5%作为质保金，在质保期满且无质量问题后支付。

第四条 履行期限
自合同签订之日起，乙方应在60日内完成设备交付，并在90日内完成安装调试。

第五条 质量标准
设备应符合国家标准GB/T 20041-2018及相关行业标准，质量保证期为设备验收合格之日起24个月。

第六条 无条件解除
甲方有权无条件解除本合同，乙方应在收到解除通知后10日内返还已支付款项。

第七条 违约责任
1. 乙方逾期交货的，每逾期一日，应向甲方支付合同总价款0.5%的违约金；
2. 甲方逾期付款的，每逾期一日，应向乙方支付逾期付款金额0.5%的违约金。

第八条 争议解决
本合同在履行过程中发生的争议，双方应协商解决；协商不成的，提交合同签订地仲裁委员会仲裁。
""",
    "服务合同": """
服务合同

甲方：新疆能源集团有限公司
乙方：某某运维服务公司

签订日期：2024年2月1日

第一条 服务内容
乙方向甲方提供光伏电站运维服务，包括日常巡检、故障维修、备件更换等。

第二条 服务费用
年度服务费用为人民币贰佰万元整（2000000元/年）。

第三条 付款方式
服务费用按季度支付，每季度末支付当季服务费用。

第四条 服务期限
服务期限为3年，自2024年3月1日起至2027年2月28日止。

第五条 保密条款
双方应对在合作过程中知悉的对方商业秘密负有保密义务，未经对方书面同意，不得向第三方披露。

第六条 单方变更权
甲方有权单方变更服务范围和服务标准，乙方应无条件执行。

第七条 责任限制
因不可抗力导致的服务中断，乙方不承担责任。
""",
    "建设合同": """
建设工程施工合同

甲方：新疆能源集团有限公司
乙方：某某建设集团有限公司

签订日期：2024年3月1日

第一条 工程概况
工程名称：新疆某光伏电站建设工程
工程地点：新疆维吾尔自治区
工程内容：光伏电站土建工程、设备安装工程

第二条 合同价款
合同总价为人民币伍仟万元整（50000000元）。

第三条 工程款支付
1. 预付款：合同签订后10日内，甲方支付合同价款的20%；
2. 进度款：按月进度支付已完成工程量的80%；
3. 结算款：工程竣工验收合格后支付至结算价款的95%；
4. 质保金：结算价款的5%作为质保金，在缺陷责任期满后支付。

第四条 工期要求
总工期为12个月，自开工通知之日起算。

第五条 工程质量
工程质量应符合国家标准GB 50300-2013及相关行业标准，一次性验收合格。

第六条 无限责任
乙方对施工过程中发生的一切安全事故承担无限责任。
""",
}


# ==================== 测试函数 ====================


async def test_contract_review(contract_type: str = "采购合同") -> dict:
    """测试合同审查流程。

    Args:
        contract_type: 合同类型

    Returns:
        审查结果
    """
    logger.info(f"开始测试合同审查 | 类型: {contract_type}")

    # 获取合同文本
    contract_text = SAMPLE_CONTRACTS.get(contract_type)
    if not contract_text:
        raise ValueError(f"未知合同类型: {contract_type}")

    # 导入模块
    from core.agent.workflows.contract.tools import (
        parse_contract,
        search_laws,
        search_templates,
        extract_clauses,
        analyze_risk,
        generate_report,
    )

    run_id = f"test_{uuid.uuid4().hex[:8]}"
    logger.info(f"Run ID: {run_id}")

    # 步骤1：解析合同
    logger.info("步骤1/5：解析合同...")
    parse_result = parse_contract.invoke({
        "contract_file_id": f"test_{run_id}",
    })
    logger.info(f"解析结果: {parse_result.get('status')}")

    # 步骤2：检索法规
    logger.info("步骤2/5：检索法规...")
    laws_result = search_laws.invoke({
        "query": f"{contract_type} 违约金 解除",
        "contract_type": contract_type,
        "business_domain": "能源",
        "top_k": 5,
    })
    logger.info(f"检索到 {laws_result.get('count')} 条法规")

    # 步骤3：检索模板
    logger.info("步骤3/5：检索模板...")
    templates_result = search_templates.invoke({
        "contract_type": contract_type,
        "business_domain": "能源",
        "top_k": 3,
    })
    logger.info(f"检索到 {templates_result.get('count')} 个模板")

    # 步骤4：抽取条款
    logger.info("步骤4/5：抽取条款...")
    clauses_result = extract_clauses.invoke({
        "contract_text": contract_text,
        "contract_type": contract_type,
    })
    logger.info(
        f"抽取条款: {len(clauses_result.get('clauses', []))} 条, "
        f"当事人: {len(clauses_result.get('parties', []))} 个"
    )

    # 步骤5：分析风险
    logger.info("步骤5/5：分析风险...")
    risk_result = analyze_risk.invoke({
        "clauses": clauses_result.get("clauses", []),
        "contract_type": contract_type,
        "laws_context": laws_result.get("laws", []),
        "templates_context": templates_result.get("templates", []),
    })
    logger.info(
        f"风险分析: 高风险 {risk_result.get('high_risk_count', 0)} 项, "
        f"中风险 {risk_result.get('medium_risk_count', 0)} 项"
    )

    # 生成报告
    report_result = generate_report.invoke({
        "contract_name": f"测试{contract_type}",
        "contract_type": contract_type,
        "clauses": clauses_result.get("clauses", []),
        "parties": clauses_result.get("parties", []),
        "risks": risk_result.get("risks", []),
        "laws_context": laws_result.get("laws", []),
        "templates_context": templates_result.get("templates", []),
    })

    # 构建最终结果
    result = {
        "run_id": run_id,
        "contract_type": contract_type,
        "timestamp": datetime.now().isoformat(),
        "parse_result": parse_result.get("status"),
        "laws_count": laws_result.get("count", 0),
        "templates_count": templates_result.get("count", 0),
        "clauses_count": len(clauses_result.get("clauses", [])),
        "parties_count": len(clauses_result.get("parties", [])),
        "risk_analysis": {
            "overall_level": risk_result.get("overall_level"),
            "high_risk_count": risk_result.get("high_risk_count", 0),
            "medium_risk_count": risk_result.get("medium_risk_count", 0),
            "need_human_review": risk_result.get("need_human_review", False),
        },
        "report": report_result.get("report"),
        "conclusion": report_result.get("conclusion"),
    }

    return result


def print_result(result: dict):
    """打印审查结果。"""
    print("\n" + "=" * 60)
    print("合同审查结果")
    print("=" * 60)

    print(f"\nRun ID: {result['run_id']}")
    print(f"合同类型: {result['contract_type']}")
    print(f"时间: {result['timestamp']}")

    print("\n--- 审查统计 ---")
    print(f"条款数量: {result['clauses_count']}")
    print(f"当事人数量: {result['parties_count']}")
    print(f"检索法规: {result['laws_count']} 条")
    print(f"检索模板: {result['templates_count']} 个")

    print("\n--- 风险分析 ---")
    risk = result["risk_analysis"]
    print(f"整体风险等级: {risk['overall_level']}")
    print(f"高风险: {risk['high_risk_count']} 项")
    print(f"中风险: {risk['medium_risk_count']} 项")
    print(f"需要人工复核: {'是' if risk['need_human_review'] else '否'}")

    print("\n--- 审查结论 ---")
    print(result["conclusion"])

    if risk["high_risk_count"] > 0:
        print("\n--- 高风险项 ---")
        for risk_item in result["report"].get("risks", []):
            if risk_item.get("risk_type") == "high":
                print(f"  * [{risk_item.get('risk_id')}] {risk_item.get('risk_description')}")
                print(f"    相关条款: {risk_item.get('related_clause')}")

    print("\n" + "=" * 60)


async def main():
    """主函数。"""
    parser = argparse.ArgumentParser(description="合同审查示例脚本")
    parser.add_argument(
        "--type",
        "-t",
        choices=list(SAMPLE_CONTRACTS.keys()),
        default="采购合同",
        help="合同类型",
    )
    parser.add_argument(
        "--json",
        "-j",
        action="store_true",
        help="输出JSON格式",
    )
    args = parser.parse_args()

    try:
        result = await test_contract_review(args.type)

        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print_result(result)

        return 0

    except Exception as e:
        logger.error(f"测试失败: {e}", exc_info=True)
        print(f"错误: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

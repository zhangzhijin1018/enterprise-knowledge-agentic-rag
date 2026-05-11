"""合同审查训练数据集生成脚本。

提供两种数据来源：
1. 合成数据：基于模板生成（用于测试和演示）
2. 真实数据：标注平台采集（用于生产环境）

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import json
import logging
import random
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Optional

from finetune.dataset.dataset_schema import (
    ContractAnnotation,
    ClauseAnnotation,
    PartyAnnotation,
    DatasetConfig,
    DataQualityStandard,
    ContractClauseType,
    RiskLevel,
)

logger = logging.getLogger(__name__)


# ==================== 合同模板库 ====================


@dataclass
class ContractTemplate:
    """合同模板。

    用于快速生成多样化的合成训练数据。
    """

    # 合同类型
    contract_type: str

    # 甲方模板
    party_a_template: str

    # 乙方模板
    party_b_template: str

    # 条款模板列表
    clause_templates: list[dict[str, str]]

    # 必要的条款类型
    required_clause_types: list[str]

    # 常见的缺失条款
    common_missing_clauses: list[str]


# 预定义合同模板
CONTRACT_TEMPLATES = {
    "能源运维合同": ContractTemplate(
        contract_type="能源运维合同",
        party_a_template="新疆能源集团有限公司",
        party_b_template="{}",
        clause_templates=[
            {
                "type": "标的条款",
                "title": "运维服务范围",
                "content": "甲方委托乙方对位于{}的风电场/光伏电站进行日常运维服务，包括设备巡检、故障维修、安全管理、数据统计等工作。运维期限为{}年，自{}起至{}止。",
            },
            {
                "type": "价款条款",
                "title": "服务费用",
                "content": "本合同总价为人民币{}元/年（大写：{}），含税价。付款方式为{}，甲方在收到乙方发票后{}日内支付。",
            },
            {
                "type": "履行期限",
                "title": "服务期限",
                "content": "乙方应在本合同生效后{}日内完成进场准备，正式开始提供运维服务。运维服务时间为每日{}至{}。",
            },
            {
                "type": "质量标准",
                "title": "服务质量要求",
                "content": "乙方应按照国家及行业相关标准提供服务，确保设备可用率不低于{}%。如因乙方原因导致设备停运超过{}小时，乙方应承担相应责任。",
            },
            {
                "type": "违约责任",
                "title": "违约条款",
                "content": "任何一方违反本合同约定，应向守约方支付合同总价的{}%作为违约金。如因乙方原因造成安全事故，乙方应承担全部赔偿责任。",
            },
            {
                "type": "保密条款",
                "title": "保密义务",
                "content": "双方应对在合同履行过程中知悉的对方商业秘密和技术秘密负有保密义务，未经对方书面同意，不得向第三方披露。保密期限为本合同终止后{}年。",
            },
            {
                "type": "争议解决",
                "title": "争议解决方式",
                "content": "因本合同引起的或与本合同有关的任何争议，双方应协商解决；协商不成的，提交{}仲裁委员会仲裁/向甲方所在地人民法院提起诉讼。",
            },
            {
                "type": "不可抗力",
                "title": "不可抗力",
                "content": "因不可抗力导致本合同无法履行时，遭受不可抗力的一方应及时通知对方，并提供相关证明文件。双方可根据不可抗力的影响程度协商变更或解除本合同。",
            },
        ],
        required_clause_types=["标的条款", "价款条款", "履行期限", "违约责任"],
        common_missing_clauses=["知识产权条款", "保险条款", "验收标准"],
    ),
    "设备采购合同": ContractTemplate(
        contract_type="设备采购合同",
        party_a_template="新疆能源集团有限公司",
        party_b_template="{}",
        clause_templates=[
            {
                "type": "标的条款",
                "title": "采购设备",
                "content": "甲方向乙方采购以下设备：{}，设备型号：{}，数量：{}台/套。设备应符合国家及行业相关标准。",
            },
            {
                "type": "价款条款",
                "title": "合同价款",
                "content": "本合同总价为人民币{}元（大写：{}元），含增值税发票。付款方式：预付款{}%，到货款{}%，验收款{}%。",
            },
            {
                "type": "履行期限",
                "title": "交货期限",
                "content": "乙方应在合同生效后{}日内完成设备制造，于{}日前送达甲方指定地点。",
            },
            {
                "type": "质量标准",
                "title": "质量要求",
                "content": "设备质量应符合国家标准GB/T{}及行业标准要求。设备质保期为到货验收合格后{}个月。",
            },
            {
                "type": "违约责任",
                "title": "违约责任",
                "content": "乙方逾期交货的，每逾期一日应支付合同总价的{}%作为违约金。如设备质量不符合要求，乙方应无条件退换并承担相应损失。",
            },
        ],
        required_clause_types=["标的条款", "价款条款", "履行期限", "质量标准"],
        common_missing_clauses=["技术培训条款", "备件供应条款"],
    ),
    "工程建设合同": ContractTemplate(
        contract_type="工程建设合同",
        party_a_template="新疆能源集团有限公司",
        party_b_template="{}",
        clause_templates=[
            {
                "type": "标的条款",
                "title": "工程项目",
                "content": "甲方委托乙方承建{}项目，工程地点：{}，工程内容：{}。",
            },
            {
                "type": "价款条款",
                "title": "工程价款",
                "content": "本合同采用{}方式计价，合同总价为人民币{}元。进度款按月支付，支付比例为完成工程量的{}%。",
            },
            {
                "type": "履行期限",
                "title": "工期要求",
                "content": "本工程工期为{}日历天，自{}起至{}止。如因甲方原因或不可抗力导致工期顺延，乙方应提供相关证明。",
            },
            {
                "type": "质量标准",
                "title": "质量标准",
                "content": "工程质量应符合国家施工质量验收统一标准GB50300及相关专业标准，一次性验收合格。",
            },
            {
                "type": "违约责任",
                "title": "违约责任",
                "content": "因乙方原因造成工期延误，每延误一天支付合同总价的{}‰作为违约金。因甲方原因造成停工，工期相应顺延。",
            },
            {
                "type": "安全责任",
                "title": "安全管理",
                "content": "乙方应严格执行安全生产法律法规，确保施工安全。如发生安全事故，由乙方承担相应责任。",
            },
        ],
        required_clause_types=["标的条款", "价款条款", "履行期限", "质量标准", "安全责任"],
        common_missing_clauses=["变更签证条款", "竣工验收条款"],
    ),
    "技术咨询合同": ContractTemplate(
        contract_type="技术咨询合同",
        party_a_template="新疆能源集团有限公司",
        party_b_template="{}",
        clause_templates=[
            {
                "type": "标的条款",
                "title": "咨询服务内容",
                "content": "乙方为甲方提供{}方面的技术咨询服务，包括：{}。",
            },
            {
                "type": "价款条款",
                "title": "咨询费用",
                "content": "本合同咨询费用为人民币{}元，付款方式为{}。",
            },
            {
                "type": "履行期限",
                "title": "服务期限",
                "content": "乙方应在{}至{}期间完成咨询服务，并向甲方提交咨询报告。",
            },
            {
                "type": "知识产权",
                "title": "知识产权归属",
                "content": "咨询服务产生的知识产权归{}方所有，未经授权，另一方不得使用。",
            },
        ],
        required_clause_types=["标的条款", "价款条款", "知识产权"],
        common_missing_clauses=["保密条款", "验收标准"],
    ),
}


# ==================== 风险指示器模板 ====================


RISK_INDICATORS = {
    "高风险": [
        "无条件解除权",
        "无限连带责任",
        "免除全部责任",
        "单方解释权",
        "无条件赔偿",
        "霸王条款",
        "显失公平",
        "格式合同风险",
    ],
    "中风险": [
        "违约金超过30%",
        "赔偿无上限",
        "单方变更权",
        "自动续期",
        "延长质保期",
        "限制竞争",
        "转让限制",
    ],
    "低风险": [
        "付款期限较短",
        "通知义务",
        "保密期限较长",
        "竞业限制",
    ],
}


# ==================== 数据生成器 ====================


class ContractDatasetGenerator:
    """合同数据集生成器。

    用于生成多样化的训练数据，支持：
    1. 基于模板的合成数据
    2. 随机变体生成
    3. 数据质量验证
    """

    def __init__(self, config: Optional[DatasetConfig] = None):
        """初始化生成器。

        Args:
            config: 数据集配置
        """
        self.config = config or DatasetConfig()

    def generate_synthetic_dataset(
        self,
        count: int,
        contract_types: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """生成合成数据集。

        Args:
            count: 生成数量
            contract_types: 合同类型列表（None 表示全部类型）

        Returns:
            训练样本列表
        """
        if contract_types is None:
            contract_types = list(CONTRACT_TEMPLATES.keys())

        samples = []

        for i in range(count):
            # 随机选择合同类型
            contract_type = random.choice(contract_types)
            template = CONTRACT_TEMPLATES[contract_type]

            # 生成样本
            sample = self._generate_sample(template, f"synthetic_{i:06d}")
            samples.append(sample)

            # 进度日志
            if (i + 1) % 100 == 0:
                logger.info(f"已生成 {i+1}/{count} 条数据")

        return samples

    def _generate_sample(
        self, template: ContractTemplate, sample_id: str
    ) -> dict[str, Any]:
        """生成单个样本。

        Args:
            template: 合同模板
            sample_id: 样本ID

        Returns:
            训练样本
        """
        # 填充甲方乙方
        party_a = template.party_a_template
        party_b = template.party_b_template.format(
            random.choice(["北京华能科技有限公司", "上海电气集团", "深圳能源发展公司",
                          "成都电力设备厂", "武汉新能源有限公司", "西安能源科技股份公司"])
        )

        # 填充条款
        clauses = []
        filled_content = []

        for clause_template in template.clause_templates:
            # 随机决定是否添加风险指示器
            risk_level = self._decide_risk_level()
            risk_indicators = []

            if risk_level == "高风险":
                risk_indicators = random.sample(
                    RISK_INDICATORS["高风险"], random.randint(1, 2)
                )
            elif risk_level == "中风险":
                risk_indicators = random.sample(
                    RISK_INDICATORS["中风险"], random.randint(1, 2)
                )
            elif risk_level == "低风险":
                risk_indicators = random.sample(
                    RISK_INDICATORS["低风险"], 1
                )

            # 生成条款内容
            clause_content = clause_template["content"].format(
                random.choice(["新疆乌鲁木齐风电场", "甘肃酒泉光伏电站", "青海德令哈光热电站",
                              "内蒙古乌兰察布风电场", "江苏盐城海上风电场", "广东汕头潮汐电站"]),
                random.randint(1, 5),
                "2024年1月1日",
                "2028年12月31日",
                random.randint(50, 200),
                "十分之一",
                random.choice(["季度", "半年", "年度"]),
                random.choice([30, 45, 60]),
                random.randint(3, 30),
                "8:00",
                "18:00",
                random.randint(95, 99),
                random.choice([24, 48, 72]),
                random.choice([10, 15, 20, 30]),
                random.randint(2, 5),
                random.choice(["乌鲁木齐", "北京", "上海", "西安"]),
                "乌鲁木齐仲裁委员会",
                random.choice(["三", "五", "十"]),
                random.randint(500, 5000),
                "叁佰万",
                random.choice(["3-3-4", "5-3-2", "3-5-2", "5-4-1"]),
                random.randint(30, 90),
                random.choice(["2024年6月1日", "2024年9月1日", "2025年1月1日"]),
                random.choice(["固定总价", "成本加酬金", "综合单价"]),
                random.randint(100, 5000),
                random.choice([50, 100, 200, 500]),
                random.choice([300, 365, 450, 730]),
                random.randint(1, 3),
                random.choice(["技术方案优化", "造价咨询", "安全评估", "环境影响评价"]),
                random.choice(["双方", "甲", "乙"]),
                random.randint(10, 50),
                "万元",
            )

            clause = ClauseAnnotation(
                clause_id=f"第{len(clauses)+1}条",
                clause_type=clause_template["type"],
                clause_title=clause_template["title"],
                clause_content=clause_content,
                risk_indicators=risk_indicators,
                risk_level=risk_level,
            )
            clauses.append(clause)
            filled_content.append(f"{clause.clause_id} {clause.clause_title}\n{clause.clause_content}")

        # 随机决定缺失条款
        missing_clauses = random.sample(
            template.common_missing_clauses,
            min(random.randint(0, 2), len(template.common_missing_clauses))
        )

        # 生成当事人
        parties = [
            PartyAnnotation(name=party_a, role="甲方"),
            PartyAnnotation(name=party_b, role="乙方"),
        ]

        # 生成合同文本
        contract_text = f"甲方：{party_a}\n乙方：{party_b}\n\n" + "\n\n".join(filled_content)

        # 生成检索主题
        legal_search_topics = [
            f"{t} 合同 法律规定" for t in random.sample(
                ["运维服务", "设备采购", "工程建设", "技术咨询"],
                2
            )
        ] + [
            f"{r} 法律效力" for r in random.sample(
                ["违约金", "解除权", "保密义务"],
                2
            )
        ]

        # 生成法律问题
        contract_legal_issues = [
            random.choice([
                "违约责任条款是否合理",
                "是否存在单方解除风险",
                "违约金比例是否符合司法解释",
                "保密期限设置是否适当",
            ])
        ]

        # 创建标注对象
        annotation = ContractAnnotation(
            sample_id=sample_id,
            contract_text=contract_text,
            contract_type=template.contract_type,
            clauses=clauses,
            parties=parties,
            missing_clauses=missing_clauses,
            legal_search_topics=legal_search_topics,
            contract_legal_issues=contract_legal_issues,
            metadata={
                "source": "synthetic",
                "template": template.contract_type,
                "generation_method": "template_filling",
            },
        )

        # 转换为训练样本格式
        return annotation.to_training_sample()

    def _decide_risk_level(self) -> str:
        """随机决定风险等级。

        分布：高风险10%，中风险30%，低风险30%，无风险30%
        """
        rand = random.random()
        if rand < 0.1:
            return RiskLevel.HIGH.value
        elif rand < 0.4:
            return RiskLevel.MEDIUM.value
        elif rand < 0.7:
            return RiskLevel.LOW.value
        else:
            return RiskLevel.NONE.value

    def validate_dataset(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        """验证数据集质量。

        Args:
            samples: 样本列表

        Returns:
            验证报告
        """
        report = {
            "total_samples": len(samples),
            "valid_samples": 0,
            "invalid_samples": 0,
            "issues": [],
            "quality_score": 0.0,
        }

        for sample in samples:
            try:
                annotation = ContractAnnotation.from_training_sample(sample)
                issues = DataQualityStandard.validate_contract_annotation(annotation)

                if issues:
                    report["issues"].append({
                        "sample_id": sample["sample_id"],
                        "issues": issues,
                    })
                    report["invalid_samples"] += 1
                else:
                    report["valid_samples"] += 1

            except Exception as e:
                report["issues"].append({
                    "sample_id": sample.get("sample_id", "unknown"),
                    "issues": [f"解析错误: {str(e)}"],
                })
                report["invalid_samples"] += 1

        # 计算质量分数
        if report["total_samples"] > 0:
            report["quality_score"] = (
                report["valid_samples"] / report["total_samples"]
            ) * 100

        return report

    def split_dataset(
        self,
        samples: list[dict[str, Any]],
        train_ratio: float = 0.8,
        val_ratio: float = 0.1,
        test_ratio: float = 0.1,
    ) -> tuple[list[dict], list[dict], list[dict]]:
        """拆分数据集。

        Args:
            samples: 样本列表
            train_ratio: 训练集比例
            val_ratio: 验证集比例
            test_ratio: 测试集比例

        Returns:
            (训练集, 验证集, 测试集)
        """
        # 打乱顺序
        shuffled = samples.copy()
        random.shuffle(shuffled)

        # 计算分割点
        total = len(shuffled)
        train_end = int(total * train_ratio)
        val_end = train_end + int(total * val_ratio)

        train_set = shuffled[:train_end]
        val_set = shuffled[train_end:val_end]
        test_set = shuffled[val_end:]

        logger.info(
            f"数据集拆分完成 | train={len(train_set)} | "
            f"val={len(val_set)} | test={len(test_set)}"
        )

        return train_set, val_set, test_set

    def save_dataset(
        self,
        samples: list[dict[str, Any]],
        output_path: str,
        format: str = "jsonl",
    ) -> None:
        """保存数据集。

        Args:
            samples: 样本列表
            output_path: 输出路径
            format: 输出格式（jsonl 或 json）
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if format == "jsonl":
            with open(output_path, "w", encoding="utf-8") as f:
                for sample in samples:
                    f.write(json.dumps(sample, ensure_ascii=False) + "\n")
        else:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(samples, f, ensure_ascii=False, indent=2)

        logger.info(f"数据集已保存至 {output_path} | 共 {len(samples)} 条")


# ==================== 批量生成脚本 ====================


def generate_full_dataset(
    output_dir: str,
    train_count: int = 1000,
    val_count: int = 100,
    test_count: int = 100,
) -> dict[str, Any]:
    """生成完整数据集。

    Args:
        output_dir: 输出目录
        train_count: 训练集数量
        val_count: 验证集数量
        test_count: 测试集数量

    Returns:
        数据统计信息
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 初始化生成器
    generator = ContractDatasetGenerator()

    # 生成各数据集
    logger.info("开始生成训练集...")
    train_samples = generator.generate_synthetic_dataset(
        count=train_count,
        contract_types=list(CONTRACT_TEMPLATES.keys()),
    )

    logger.info("开始生成验证集...")
    val_samples = generator.generate_synthetic_dataset(
        count=val_count,
        contract_types=list(CONTRACT_TEMPLATES.keys()),
    )

    logger.info("开始生成测试集...")
    test_samples = generator.generate_synthetic_dataset(
        count=test_count,
        contract_types=list(CONTRACT_TEMPLATES.keys()),
    )

    # 保存数据集
    generator.save_dataset(train_samples, str(output_dir / "train.jsonl"))
    generator.save_dataset(val_samples, str(output_dir / "val.jsonl"))
    generator.save_dataset(test_samples, str(output_dir / "test.jsonl"))

    # 合并训练验证集用于训练（验证集也参与训练以便观察过拟合）
    all_train = train_samples + val_samples
    generator.save_dataset(all_train, str(output_dir / "train_all.jsonl"))

    # 验证数据集
    logger.info("验证数据集质量...")
    train_report = generator.validate_dataset(train_samples)
    test_report = generator.validate_dataset(test_samples)

    stats = {
        "train": {
            "count": len(train_samples),
            "valid_count": train_report["valid_samples"],
            "quality_score": train_report["quality_score"],
        },
        "val": {
            "count": len(val_samples),
        },
        "test": {
            "count": len(test_samples),
            "valid_count": test_report["valid_samples"],
            "quality_score": test_report["quality_score"],
        },
    }

    logger.info(f"数据集生成完成 | {stats}")
    return stats


# ==================== 主函数 ====================


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # 生成数据集
    output_dir = Path(__file__).parent / "data"
    stats = generate_full_dataset(
        output_dir=str(output_dir),
        train_count=1000,
        val_count=100,
        test_count=100,
    )

    print("\n数据集生成完成！")
    print(json.dumps(stats, indent=2, ensure_ascii=False))

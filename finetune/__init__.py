"""Finetune 模块。

提供 LoRA 微调训练框架，包括：
- 数据集生成
- LLaMA-Factory 训练
- PEFT 训练
- 模型评估
"""

from finetune.dataset.dataset_schema import (
    ContractAnnotation,
    ClauseAnnotation,
    PartyAnnotation,
    ContractClauseType,
    RiskLevel,
    DatasetConfig,
    DataQualityStandard,
)

from finetune.dataset.data_generator import (
    ContractDatasetGenerator,
    ContractTemplate,
    generate_full_dataset,
)

__all__ = [
    "ContractAnnotation",
    "ClauseAnnotation",
    "PartyAnnotation",
    "ContractClauseType",
    "RiskLevel",
    "DatasetConfig",
    "DataQualityStandard",
    "ContractDatasetGenerator",
    "ContractTemplate",
    "generate_full_dataset",
]

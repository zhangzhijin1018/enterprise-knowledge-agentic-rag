"""合并 LoRA Adapter 脚本。

将训练好的 LoRA Adapter 与基础模型合并，生成可独立部署的完整模型。

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def merge_adapter(
    base_model_path: str,
    adapter_path: str,
    output_path: str,
    save_format: str = "safetensors",
    torch_dtype: str = "bfloat16",
) -> None:
    """合并 LoRA Adapter 到基础模型。

    Args:
        base_model_path: 基础模型路径
        adapter_path: LoRA Adapter 路径
        output_path: 输出路径
        save_format: 保存格式 (safetensors/pytorch)
        torch_dtype: 模型精度 (float16/bfloat16/float32)
    """
    logger.info("=" * 50)
    logger.info("合并 LoRA Adapter")
    logger.info("=" * 50)
    logger.info(f"基础模型: {base_model_path}")
    logger.info(f"Adapter: {adapter_path}")
    logger.info(f"输出路径: {output_path}")
    logger.info(f"精度: {torch_dtype}")
    logger.info("-" * 50)

    # 设置精度
    dtype_map = {
        "float16": torch.float16,
        "bfloat16": torch.bfloat16,
        "float32": torch.float32,
    }
    dtype = dtype_map.get(torch_dtype, torch.bfloat16)

    # 加载基础模型
    logger.info("加载基础模型...")
    base_model = AutoModelForCausalLM.from_pretrained(
        base_model_path,
        torch_dtype=dtype,
        device_map="auto",
        trust_remote_code=True,
    )

    # 加载 Adapter
    logger.info("加载 LoRA Adapter...")
    model = PeftModel.from_pretrained(
        base_model,
        adapter_path,
        device_map="auto",
    )

    # 合并权重
    logger.info("合并权重...")
    merged_model = model.merge_and_unload()

    # 保存合并后的模型
    logger.info("保存合并后的模型...")
    output_path = Path(output_path)
    output_path.mkdir(parents=True, exist_ok=True)

    merged_model.save_pretrained(
        output_path,
        safe_serialization=(save_format == "safetensors"),
    )

    # 保存分词器
    logger.info("保存分词器...")
    tokenizer = AutoTokenizer.from_pretrained(
        base_model_path,
        trust_remote_code=True,
    )
    tokenizer.save_pretrained(output_path)

    # 保存元数据
    metadata = {
        "base_model": base_model_path,
        "adapter_path": adapter_path,
        "merge_dtype": torch_dtype,
        "save_format": save_format,
    }
    with open(output_path / "merge_metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    logger.info("=" * 50)
    logger.info("合并完成！")
    logger.info(f"模型已保存至: {output_path}")
    logger.info("=" * 50)


def main():
    """主函数。"""
    parser = argparse.ArgumentParser(description="合并 LoRA Adapter")
    parser.add_argument("--base-model", type=str, required=True, help="基础模型路径")
    parser.add_argument("--adapter", type=str, required=True, help="Adapter 路径")
    parser.add_argument("--output", type=str, required=True, help="输出路径")
    parser.add_argument(
        "--format",
        type=str,
        default="safetensors",
        choices=["safetensors", "pytorch"],
        help="保存格式",
    )
    parser.add_argument(
        "--dtype",
        type=str,
        default="bfloat16",
        choices=["float16", "bfloat16", "float32"],
        help="模型精度",
    )

    args = parser.parse_args()

    merge_adapter(
        base_model_path=args.base_model,
        adapter_path=args.adapter,
        output_path=args.output,
        save_format=args.format,
        torch_dtype=args.dtype,
    )


if __name__ == "__main__":
    main()

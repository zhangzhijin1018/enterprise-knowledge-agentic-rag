"""PEFT 训练脚本 - 基于 HuggingFace PEFT 库。

使用 HuggingFace PEFT 库进行 LoRA 微调训练。
相比 LLaMA-Factory，PEFT 更轻量，适合自定义训练流程。

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
import math

import torch
from torch.utils.data import DataLoader, Dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    DataCollatorForSeq2Seq,
    TrainingArguments,
    Trainer,
    TrainerCallback,
    TrainerControl,
    TrainerState,
)
from peft import (
    LoraConfig,
    get_peft_model,
    prepare_model_for_kbit_training,
    TaskType,
)
from tqdm import tqdm

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ==================== 配置 ====================


@dataclass
class LoRATrainingConfig:
    """LoRA 训练配置。"""

    # 模型配置
    base_model_path: str = "Qwen/Qwen3-8B"
    model_revision: Optional[str] = None
    trust_remote_code: bool = True

    # 量化配置
    use_quantization: bool = True
    quantization_bit: int = 4
    bnb_compute_dtype: str = "bfloat16"

    # LoRA 配置
    lora_rank: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    lora_target_modules: list[str] = field(
        default_factory=lambda: ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
    )

    # 数据配置
    train_data_path: str = "./finetune/dataset/data/train.jsonl"
    val_data_path: str = "./finetune/dataset/data/val.jsonl"
    max_length: int = 2048
    preprocessing_num_workers: int = 8

    # 训练配置
    output_dir: str = "./finetune/peft/output"
    num_train_epochs: int = 3
    per_device_train_batch_size: int = 2
    per_device_eval_batch_size: int = 2
    gradient_accumulation_steps: int = 8
    learning_rate: float = 5e-5
    weight_decay: float = 0.01
    warmup_ratio: float = 0.1
    lr_scheduler_type: str = "cosine"
    logging_steps: int = 10
    save_steps: int = 500
    eval_steps: int = 500
    save_total_limit: int = 3
    bf16: bool = True
    fp16: bool = False

    # 其他
    seed: int = 42
    debug_mode: bool = False
    remove_unused_columns: bool = False
    group_by_length: bool = False


# ==================== 数据集类 ====================


class ContractDataset(Dataset):
    """合同条款提取数据集。"""

    def __init__(
        self,
        data_path: str,
        tokenizer: AutoTokenizer,
        max_length: int = 2048,
    ):
        """初始化数据集。

        Args:
            data_path: 数据文件路径（JSONL 格式）
            tokenizer: 分词器
            max_length: 最大序列长度
        """
        self.data = []
        self.tokenizer = tokenizer
        self.max_length = max_length

        # 加载数据
        with open(data_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    self.data.append(json.loads(line))

        logger.info(f"加载数据集: {data_path} | 共 {len(self.data)} 条")

    def __len__(self) -> int:
        return len(self.data)

    def __getitem__(self, idx: int) -> dict[str, Any]:
        """获取单个样本。"""
        sample = self.data[idx]

        # 构建 prompt
        instruction = sample.get("instruction", "")
        input_text = sample.get("input", "")
        output_text = sample.get("output", "")

        # 使用 Qwen 模板格式
        prompt = f"<|im_start|>system\n你是一个专业的合同法律审查助手。<|im_end|>\n"
        prompt += f"<|im_start|>user\n{instruction}\n\n{input_text}<|im_end|>\n"
        prompt += f"<|im_start|>assistant\n{output_text}<|im_end|>"

        # Tokenize
        encoded = self.tokenizer(
            prompt,
            max_length=self.max_length,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
        )

        # 训练时使用 labels
        labels = encoded["input_ids"].clone()
        labels[labels == self.tokenizer.pad_token_id] = -100

        return {
            "input_ids": encoded["input_ids"].squeeze(),
            "attention_mask": encoded["attention_mask"].squeeze(),
            "labels": labels.squeeze(),
        }


# ==================== 自定义回调 ====================


class LoggingCallback(TrainerCallback):
    """自定义日志回调。"""

    def __init__(self):
        self.train_losses = []
        self.eval_losses = []
        self.global_steps = []

    def on_log(
        self,
        args: TrainingArguments,
        state: TrainerState,
        control: TrainerControl,
        logs: dict = None,
        **kwargs,
    ):
        """记录训练日志。"""
        if logs:
            if "loss" in logs:
                self.train_losses.append(logs["loss"])
                self.global_steps.append(state.global_step)
                logger.info(f"Step {state.global_step} | Loss: {logs['loss']:.4f}")

            if "eval_loss" in logs:
                self.eval_losses.append(logs["eval_loss"])
                logger.info(f"Step {state.global_step} | Eval Loss: {logs['eval_loss']:.4f}")

    def on_train_end(
        self,
        args: TrainingArguments,
        state: TrainerState,
        control: TrainerControl,
        **kwargs,
    ):
        """训练结束时保存损失曲线数据。"""
        output_dir = Path(args.output_dir)
        loss_data = {
            "train_losses": self.train_losses,
            "eval_losses": self.eval_losses,
            "global_steps": self.global_steps,
        }
        with open(output_dir / "loss_history.json", "w") as f:
            json.dump(loss_data, f, indent=2)
        logger.info(f"损失历史已保存至 {output_dir / 'loss_history.json'}")


# ==================== 训练器类 ====================


class LoRATrainer:
    """LoRA 训练器。

    基于 HuggingFace Trainer 和 PEFT 库实现 LoRA 微调。
    """

    def __init__(self, config: Optional[LoRATrainingConfig] = None):
        """初始化训练器。

        Args:
            config: 训练配置
        """
        self.config = config or LoRATrainingConfig()
        self.model = None
        self.tokenizer = None
        self.trainer = None

    def setup_model(self) -> None:
        """设置模型和分词器。"""
        logger.info("初始化模型...")

        # 量化配置
        bnb_config = None
        if self.config.use_quantization:
            compute_dtype = getattr(torch, self.config.bnb_compute_dtype)
            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=compute_dtype,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4",
            )
            logger.info(f"使用 {self.config.quantization_bit}bit 量化")

        # 加载分词器
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.config.base_model_path,
            revision=self.config.model_revision,
            trust_remote_code=self.config.trust_remote_code,
            padding_side="right",
        )

        # 设置 pad token
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
            self.tokenizer.pad_token_id = self.tokenizer.eos_token_id

        # 加载模型
        logger.info(f"加载基础模型: {self.config.base_model_path}")

        if self.config.use_quantization:
            self.model = AutoModelForCausalLM.from_pretrained(
                self.config.base_model_path,
                revision=self.config.model_revision,
                quantization_config=bnb_config,
                device_map="auto",
                trust_remote_code=self.config.trust_remote_code,
            )
            # 为量化模型准备训练
            self.model = prepare_model_for_kbit_training(self.model)
        else:
            self.model = AutoModelForCausalLM.from_pretrained(
                self.config.base_model_path,
                revision=self.config.model_revision,
                device_map="auto",
                trust_remote_code=self.config.trust_remote_code,
                torch_dtype=torch.bfloat16 if self.config.bf16 else torch.float16,
            )

        # 应用 LoRA
        logger.info("应用 LoRA...")
        lora_config = LoraConfig(
            r=self.config.lora_rank,
            lora_alpha=self.config.lora_alpha,
            lora_dropout=self.config.lora_dropout,
            target_modules=self.config.lora_target_modules,
            bias="none",
            task_type=TaskType.CAUSAL_LM,
        )

        self.model = get_peft_model(self.model, lora_config)

        # 打印可训练参数
        trainable_params, all_params = self._count_parameters()
        logger.info(
            f"可训练参数: {trainable_params:,} ({trainable_params/all_params*100:.2f}%) "
            f"/ 总参数: {all_params:,}"
        )

        # 打印 LoRA 配置
        self.model.print_trainable_parameters()

    def _count_parameters(self) -> tuple[int, int]:
        """计算参数数量。"""
        trainable_params = 0
        all_params = 0

        for param in self.model.parameters():
            all_params += param.numel()
            if param.requires_grad:
                trainable_params += param.numel()

        return trainable_params, all_params

    def setup_data(self) -> tuple[Dataset, Dataset]:
        """设置数据集。"""
        logger.info("加载数据集...")

        train_dataset = ContractDataset(
            data_path=self.config.train_data_path,
            tokenizer=self.tokenizer,
            max_length=self.config.max_length,
        )

        val_dataset = None
        if self.config.val_data_path and os.path.exists(self.config.val_data_path):
            val_dataset = ContractDataset(
                data_path=self.config.val_data_path,
                tokenizer=self.tokenizer,
                max_length=self.config.max_length,
            )

        return train_dataset, val_dataset

    def setup_training_arguments(self) -> TrainingArguments:
        """设置训练参数。"""
        output_dir = Path(self.config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        return TrainingArguments(
            output_dir=str(output_dir),
            num_train_epochs=self.config.num_train_epochs,
            per_device_train_batch_size=self.config.per_device_train_batch_size,
            per_device_eval_batch_size=self.config.per_device_eval_batch_size,
            gradient_accumulation_steps=self.config.gradient_accumulation_steps,
            learning_rate=self.config.learning_rate,
            weight_decay=self.config.weight_decay,
            warmup_ratio=self.config.warmup_ratio,
            lr_scheduler_type=self.config.lr_scheduler_type,
            logging_steps=self.config.logging_steps,
            save_steps=self.config.save_steps,
            eval_steps=self.config.eval_steps,
            save_total_limit=self.config.save_total_limit,
            bf16=self.config.bf16,
            fp16=self.config.fp16,
            logging_dir=str(output_dir / "logs"),
            remove_unused_columns=self.config.remove_unused_columns,
            group_by_length=self.config.group_by_length,
            seed=self.config.seed,
            report_to=["tensorboard"],
            gradient_checkpointing=True,
            gradient_checkpointing_kwargs={"use_reentrant": False},
        )

    def train(self) -> None:
        """执行训练。"""
        logger.info("=" * 50)
        logger.info("开始 LoRA 训练")
        logger.info("=" * 50)

        # 设置模型
        self.setup_model()

        # 设置数据
        train_dataset, val_dataset = self.setup_data()

        # 设置训练参数
        training_args = self.setup_training_arguments()

        # 数据整理器
        data_collator = DataCollatorForSeq2Seq(
            tokenizer=self.tokenizer,
            model=self.model,
            padding=True,
            max_length=self.config.max_length,
        )

        # 创建训练器
        callbacks = [LoggingCallback()]

        self.trainer = Trainer(
            model=self.model,
            args=training_args,
            train_dataset=train_dataset,
            eval_dataset=val_dataset,
            data_collator=data_collator,
            callbacks=callbacks,
        )

        # 开始训练
        logger.info("开始训练...")
        self.trainer.train()

        # 保存最终模型
        logger.info("保存模型...")
        self.trainer.save_model(str(Path(self.config.output_dir) / "final"))
        self.tokenizer.save_pretrained(str(Path(self.config.output_dir) / "final"))

        logger.info("=" * 50)
        logger.info("训练完成！")
        logger.info(f"模型保存至: {self.config.output_dir}")
        logger.info("=" * 50)

    def save_adapter(self, output_path: str) -> None:
        """保存 LoRA Adapter。

        Args:
            output_path: 输出路径
        """
        if self.model is None:
            raise ValueError("模型未初始化，请先调用 train()")

        output_path = Path(output_path)
        output_path.mkdir(parents=True, exist_ok=True)

        self.model.save_pretrained(output_path)
        self.tokenizer.save_pretrained(output_path)

        logger.info(f"Adapter 已保存至: {output_path}")

    def merge_and_save(self, output_path: str) -> None:
        """合并 LoRA 并保存完整模型。

        Args:
            output_path: 输出路径
        """
        if self.model is None:
            raise ValueError("模型未初始化，请先调用 train()")

        output_path = Path(output_path)
        output_path.mkdir(parents=True, exist_ok=True)

        logger.info("合并 LoRA 权重...")
        merged_model = self.model.merge_and_unload()

        logger.info("保存合并后的模型...")
        merged_model.save_pretrained(output_path)
        self.tokenizer.save_pretrained(output_path)

        logger.info(f"合并模型已保存至: {output_path}")


# ==================== 主函数 ====================


def main():
    """主函数。"""
    import argparse

    parser = argparse.ArgumentParser(description="PEFT LoRA 训练脚本")
    parser.add_argument("--config", type=str, help="配置文件路径")
    parser.add_argument("--model", type=str, help="基础模型路径")
    parser.add_argument("--data", type=str, help="训练数据路径")
    parser.add_argument("--output", type=str, help="输出目录")
    parser.add_argument("--rank", type=int, default=16, help="LoRA rank")
    parser.add_argument("--alpha", type=int, default=32, help="LoRA alpha")
    parser.add_argument("--epochs", type=int, default=3, help="训练轮数")
    parser.add_argument("--lr", type=float, default=5e-5, help="学习率")
    parser.add_argument("--batch-size", type=int, default=2, help="批大小")
    parser.add_argument("--quantize", action="store_true", help="使用量化")

    args = parser.parse_args()

    # 加载或构建配置
    if args.config:
        # 从配置文件加载
        with open(args.config, "r") as f:
            config_dict = json.load(f)
            config = LoRATrainingConfig(**config_dict)
    else:
        # 从命令行参数构建
        config = LoRATrainingConfig(
            base_model_path=args.model or "Qwen/Qwen2-7B-Instruct",
            train_data_path=args.data or "./finetune/dataset/data/train.jsonl",
            output_dir=args.output or "./finetune/peft/output",
            lora_rank=args.rank,
            lora_alpha=args.alpha,
            num_train_epochs=args.epochs,
            learning_rate=args.lr,
            per_device_train_batch_size=args.batch_size,
            use_quantization=args.quantize,
        )

    # 创建训练器
    trainer = LoRATrainer(config)

    # 执行训练
    trainer.train()

    # 保存 Adapter
    trainer.save_adapter(str(Path(config.output_dir) / "adapter"))


if __name__ == "__main__":
    main()

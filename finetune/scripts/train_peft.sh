#!/bin/bash
#
# PEFT 训练启动脚本
# 合同审查条款提取 - Qwen2-7B LoRA 微调
#

set -e

# ==================== 配置 ====================

# 项目根目录
PROJECT_ROOT="/Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag"
cd "${PROJECT_ROOT}"

# 训练配置
MODEL_PATH="/path/to/your/qwen2-7b-instruct"
TRAIN_DATA="./finetune/dataset/data/train.jsonl"
VAL_DATA="./finetune/dataset/data/val.jsonl"
OUTPUT_DIR="./finetune/peft/output"

# 训练参数
LORA_RANK=16
LORA_ALPHA=32
LEARNING_RATE=5.0e-5
NUM_EPOCHS=3
BATCH_SIZE=2
GRADIENT_ACCUMULATION=8

# ==================== 环境检查 ====================

echo "=============================================="
echo "  PEFT 合同条款提取 LoRA 训练"
echo "=============================================="
echo ""

# 检查 CUDA
if command -v nvidia-smi &> /dev/null; then
    echo "[INFO] NVIDIA GPU 检测通过"
    nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv
    echo ""
else
    echo "[ERROR] 未检测到 NVIDIA GPU"
    exit 1
fi

# 检查显存
FREE_MEM=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1)
echo "[INFO] 可用显存: ${FREE_MEM} MB"

if [ "${FREE_MEM}" -lt 20000 ]; then
    echo "[WARN] 显存可能不足，建议使用量化训练"
fi

# ==================== 安装依赖 ====================

echo "[INFO] 安装依赖..."
pip install peft transformers accelerate bitsandbytes -q

# ==================== 生成数据 ====================

echo ""
echo "[INFO] 生成训练数据..."
mkdir -p ./finetune/dataset/data
conda run -n tmf_project python -c "
import sys
sys.path.insert(0, '${PROJECT_ROOT}')
from finetune.dataset.data_generator import generate_full_dataset
generate_full_dataset(
    output_dir='${PROJECT_ROOT}/finetune/dataset/data',
    train_count=500,
    val_count=50,
    test_count=50
)
"

# ==================== 开始训练 ====================

echo ""
echo "[INFO] 开始训练..."
echo "=============================================="

# 构建命令
CMD="conda run -n tmf_project python -m finetune.peft.train_peft \
    --model=${MODEL_PATH} \
    --data=${TRAIN_DATA} \
    --output=${OUTPUT_DIR} \
    --rank=${LORA_RANK} \
    --alpha=${LORA_ALPHA} \
    --lr=${LEARNING_RATE} \
    --epochs=${NUM_EPOCHS} \
    --batch-size=${BATCH_SIZE} \
    --quantize"

echo "执行命令: ${CMD}"
eval ${CMD}

# ==================== 训练完成 ====================

echo ""
echo "=============================================="
echo "  训练完成！"
echo "=============================================="
echo ""
echo "输出目录: ${OUTPUT_DIR}"
echo "Adapter 文件: ${OUTPUT_DIR}/adapter/"
echo ""
echo "下一步："
echo "1. 评估模型: bash finetune/scripts/evaluate.sh"
echo "2. 合并模型: python -m finetune.peft.merge_adapter"
echo "3. 部署服务: 参考 docs/LORA_FINETUNE_GUIDE.md"

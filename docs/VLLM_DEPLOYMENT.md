# =============================================================================
# vLLM Qwen3-32B 部署指南
#
# 本文档说明如何部署 Qwen3-32B 模型服务
# Qwen3 系列相比 Qwen2.5 有显著性能提升，支持思考模式
#
# =============================================================================

# 一、硬件要求
# =============================================================================

## 最低配置（勉强运行，需要量化）
| 配置项 | 要求 |
|--------|------|
| GPU | NVIDIA GPU，24GB+ 显存 |
| 推荐 | RTX 4090 (24GB), A5000 (24GB), A100 (40GB/80GB) |
| 内存 | 64GB+ |
| 存储 | 100GB+ 可用空间（模型约 66GB） |
| CUDA | 12.1+ |

## 推荐配置（流畅运行）
| 配置项 | 要求 |
|--------|------|
| GPU | A100 80GB 或多卡 |
| 内存 | 128GB+ |
| 存储 | 200GB+ SSD |
| CUDA | 12.1+ |

## 显存计算
```
Qwen3-32B 参数说明：
- 32B = 320亿参数
- 每个参数 float16 = 2 bytes
- 模型本身 = 32B × 2 bytes = 66GB (比 Qwen2.5 略大)

加上 KV Cache 和激活值，实际需要：
- FP16: ~85GB
- INT8: ~48GB
- INT4/FP8: ~26GB
```

## Qwen3 系列模型规格对比

| 模型 | 参数量 | FP16 显存 | INT4 量化显存 | 激活参数 | 适用场景 |
|------|--------|-----------|---------------|----------|----------|
| Qwen3-8B | 8B | ~18GB | ~6GB | 8B | 单卡可运行 |
| Qwen3-14B | 14B | ~30GB | ~10GB | 14B | 单卡勉强 |
| Qwen3-32B | 32B | ~66GB | ~20GB | 32B | 需要多卡 |
| Qwen3-30B-A3B | 30B MoE | ~65GB | ~20GB | 3B | MoE 高效 |

# 二、安装步骤
# =============================================================================

## 步骤 1：安装 vLLM

```bash
# 激活 conda 环境
conda activate tmf_project

# 安装 vLLM（稳定版，推荐）
pip install vllm

# 或者安装最新版本（可能不稳定）
pip install vllm --pre

# 验证安装
python -c "import vllm; print(vllm.__version__)"
```

## 步骤 2：下载模型

```bash
# 安装 huggingface_hub（如果没有）
pip install huggingface_hub

# 设置 HF_TOKEN（可选，需要同意模型协议）
export HF_TOKEN="your-huggingface-token"

# 下载模型（约 66GB，需要代理）
export HTTPS_PROXY="http://127.0.0.1:7890"  # 你的代理地址
export HTTP_PROXY="http://127.0.0.1:7890"

# Qwen3-32B
huggingface-cli download Qwen/Qwen3-32B \
    --local-dir ~/.cache/huggingface/hub/models--Qwen--Qwen3-32B

# Qwen3-8B（更小，推荐单卡使用）
huggingface-cli download Qwen/Qwen3-8B \
    --local-dir ~/.cache/huggingface/hub/models--Qwen--Qwen3-8B
```

**注意**：国内下载可能很慢，建议使用镜像或代理。

## 步骤 3：启动服务

```bash
# 方式一：使用脚本（推荐）
chmod +x scripts/deploy_qwen32b.sh
./scripts/deploy_qwen32b.sh install   # 安装 + 下载模型
./scripts/deploy_qwen32b.sh start     # 启动服务

# 方式二：直接启动 Qwen3-32B（需要多卡）
python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen3-32B \
    --trust-remote-code \
    --host 0.0.0.0 \
    --port 8000 \
    --gpu-memory-utilization 0.9 \
    --max-model-len 32768 \
    --tensor-parallel-size 2  # 32B 需要双卡

# 方式三：直接启动 Qwen3-8B（单卡可运行）
python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen3-8B \
    --trust-remote-code \
    --host 0.0.0.0 \
    --port 8001 \
    --gpu-memory-utilization 0.9 \
    --max-model-len 32768
```

## 步骤 4：验证服务

```bash
# 检查服务状态
curl http://localhost:8000/v1/models

# 测试推理
curl -X POST "http://localhost:8000/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d '{
        "model": "Qwen/Qwen3-32B",
        "messages": [{"role": "user", "content": "你好"}],
        "max_tokens": 100
    }'

# 测试思考模式（Qwen3 新特性）
curl -X POST "http://localhost:8000/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d '{
        "model": "Qwen/Qwen3-32B",
        "messages": [{"role": "user", "content": "解释量子计算"}],
        "extra_body": {
            "thinking": true,
            "thought_depth": 6
        }
    }'
```

# 三、显存不足时的优化方案
# =============================================================================

## 方案 1：使用 INT8 量化（推荐，A100 40G 可用）

```bash
pip install vllm[quantization]

python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen3-32B \
    --quantization awq \
    --gpu-memory-utilization 0.9 \
    --tensor-parallel-size 2
```

## 方案 2：使用 INT4 量化（需要更少显存）

```bash
python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen3-32B \
    --quantization gptq \
    --type gptq \
    --bits 4
```

## 方案 3：使用更小的模型

如果显存实在不够，可以考虑：
- Qwen3-14B (~30GB)
- Qwen3-8B (~18GB) - **推荐单卡使用**

```bash
# Qwen3-8B 单卡部署（推荐）
python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen3-8B \
    --host 0.0.0.0 \
    --port 8001 \
    --gpu-memory-utilization 0.9
```

# 四、多卡部署
# =============================================================================

## Qwen3-32B 双卡 A100 40G

```bash
python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen3-32B \
    --tensor-parallel-size 2 \
    --gpu-memory-utilization 0.95 \
    --port 8000
```

## Qwen3-32B 四卡 A100 40G

```bash
python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen3-32B \
    --tensor-parallel-size 4 \
    --gpu-memory-utilization 0.95 \
    --port 8000
```

## 推荐：小模型 + 大模型组合部署

建议同时部署两个模型：
- Qwen3-8B（端口 8001）：处理简单任务，单卡可运行
- Qwen3-32B（端口 8000）：处理复杂任务，需要多卡

```bash
# 终端 1: 启动 Qwen3-8B
python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen3-8B \
    --port 8001

# 终端 2: 启动 Qwen3-32B
python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen3-32B \
    --port 8000 \
    --tensor-parallel-size 2
```

# 五、配置项目环境变量
# =============================================================================

编辑 `.env` 文件：

```bash
# .env

# ========== LLM 配置 ==========
# Qwen3 系列配置
LLM_PROVIDER=vllm
LLM_BASE_URL=http://localhost:8000/v1
LLM_API_KEY=EMPTY

# 大模型（复杂任务）
LLM_MODEL_NAME=Qwen/Qwen3-32B

# 小模型（简单任务，可选）
# LLM_MODEL_SMALL=Qwen/Qwen3-8B

LLM_TIMEOUT_SECONDS=120

# ========== 其他配置（可选）==========
# 如果使用代理下载模型
# HTTPS_PROXY=http://127.0.0.1:7890
# HTTP_PROXY=http://127.0.0.1:7890
```

# 六、Qwen3 新特性配置
# =============================================================================

## 思考模式

Qwen3 支持思考模式，适合复杂推理任务：

```bash
# 启用思考模式
python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen3-32B \
    --enable-thinking

# API 调用时控制
curl -X POST "http://localhost:8000/v1/chat/completions" \
    -d '{
        "model": "Qwen/Qwen3-32B",
        "messages": [{"role": "user", "content": "证明 P=NP"}],
        "extra_body": {
            "thinking": true,
            "thought_depth": 6  # 思考深度 1-10
        }
    }'
```

## 非思考模式（快速响应）

对于简单问答，关闭思考模式可以加速：

```python
# Python 调用示例
response = client.chat.completions.create(
    model="Qwen/Qwen3-8B",
    messages=[{"role": "user", "content": "今天天气如何？"}],
    extra_body={
        "thinking": False  # 关闭思考模式
    }
)
```

# 七、常见问题
# =============================================================================

## Q1: 显存不足 (CUDA out of memory)

**解决方案**：
1. 降低 `gpu-memory-utilization` 到 0.8
2. 启用量化：`--quantization awq`
3. 使用更小的模型：Qwen3-8B

## Q2: 模型下载慢或失败

**解决方案**：
1. 使用代理
2. 使用 HuggingFace 镜像
3. 先下载到本地，再指定本地路径

```bash
export HF_ENDPOINT=https://hf-mirror.com
huggingface-cli download Qwen/Qwen3-32B
```

## Q3: 服务启动慢

**正常现象**：首次启动需要加载约 66GB 模型，约需 2-5 分钟。

**加速方法**：
1. 使用 SSD 存储模型
2. 确保有足够显存
3. 减少 `max-model-len`

## Q4: 推理速度慢

**可能原因**：
1. 显存不足，导致频繁交换
2. `max-model-len` 设置过大
3. GPU 利用率低

**优化方法**：
1. 启用量化：`--quantization awq`
2. 减少 `max-model-len`
3. 增加 `gpu-memory-utilization`
4. 使用更小的模型处理简单任务

## Q5: 如何更新到 Qwen3？

```bash
# 停止服务
./scripts/deploy_qwen32b.sh stop

# 删除旧模型
rm -rf ~/.cache/huggingface/hub/models--Qwen--Qwen3-32B

# 重新下载
huggingface-cli download Qwen/Qwen3-32B

# 重启服务
./scripts/deploy_qwen32b.sh start
```

# 八、systemd 服务配置（可选）
# =============================================================================

创建 `/etc/systemd/system/vllm-qwen3-32b.service`：

```ini
[Unit]
Description=vLLM Qwen3-32B Service
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/path/to/enterprise-knowledge-agentic-rag
ExecStart=/path/to/conda/envs/tmf_project/bin/python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen3-32B \
    --trust-remote-code \
    --host 0.0.0.0 \
    --port 8000 \
    --gpu-memory-utilization 0.9 \
    --max-model-len 32768 \
    --tensor-parallel-size 2
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启用服务：

```bash
sudo systemctl enable vllm-qwen3-32b
sudo systemctl start vllm-qwen3-32b
sudo systemctl status vllm-qwen3-32b
```

# 九、性能基准参考
# =============================================================================

使用 vLLM + Qwen3 的参考性能：

| 配置 | 吞吐量 (tokens/s) | 首次生成延迟 | 显存占用 |
|------|------------------|-------------|---------|
| A100 80G (32B) | ~100-150 | ~0.5s | ~80GB |
| A100 40G + INT8 (32B) | ~60-80 | ~1s | ~45GB |
| 双 A100 40G (32B) | ~150-200 | ~0.3s | ~80GB |
| A100 80G (8B) | ~200-300 | ~0.2s | ~20GB |
| RTX 4090 + INT4 (8B) | ~50-80 | ~1s | ~10GB |

*注：实际性能取决于输入输出长度和系统负载*

## Qwen3 vs Qwen2.5 性能对比

| 指标 | Qwen2.5-32B | Qwen3-32B | 提升 |
|------|-------------|-----------|------|
| 预训练数据 | 18 万亿 tokens | 36 万亿 tokens | 2x |
| AIME25 数学 | 42 分 | 81.5 分 | +94% |
| LiveCodeBench | 35 分 | 70+ 分 | +100% |
| 支持语言 | ~30 种 | 119 种 | 4x |
| 思考模式 | ❌ | ✅ | 新特性 |

# 十、架构建议
# =============================================================================

## 推荐架构：大小模型组合

```
┌─────────────────────────────────────────────────────────────────┐
│                    Agent 平台 LLM 架构                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  请求入口                                                        │
│      │                                                          │
│      ├── 简单任务 ──→ Qwen3-8B (单卡)                            │
│      │              快速响应，适合 RAG 问答                       │
│      │                                                          │
│      └── 复杂任务 ──→ Qwen3-32B (多卡)                           │
│                      深度推理，适合合同审查/分析                   │
│                                                                  │
│  路由策略：                                                      │
│  • 意图识别后自动路由                                            │
│  • 简单问答 → 8B（省成本）                                       │
│  • 复杂推理 → 32B（高质量）                                       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## 环境变量配置示例

```bash
# .env 配置
LLM_BASE_URL_SMALL=http://localhost:8001/v1  # Qwen3-8B
LLM_BASE_URL_LARGE=http://localhost:8000/v1  # Qwen3-32B
LLM_MODEL_SMALL=Qwen/Qwen3-8B
LLM_MODEL_LARGE=Qwen/Qwen3-32B
```

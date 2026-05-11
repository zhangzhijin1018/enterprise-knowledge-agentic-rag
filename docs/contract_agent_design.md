# Contract Agent 技术文档

## 1. 概述

Contract Agent（合同审查 Agent）是企业知识 Agent 平台的专用 Agent，负责：

1. **合同文档解析** - 支持 PDF、Word、文本等格式
2. **条款自动抽取** - 从合同文本中提取关键条款
3. **风险智能识别** - 识别高风险、中风险、低风险条款
4. **审查报告生成** - 生成结构化审查报告

## 2. 架构

```
┌─────────────────────────────────────────────────────────────────┐
│                     Contract Agent Server                        │
│                         (port: 6003)                            │
│                                                                 │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐        │
│  │   A2A       │    │   HTTP API  │    │   LangGraph │        │
│  │   Handler   │    │   Handler   │───►│   Workflow  │        │
│  └─────────────┘    └─────────────┘    └──────┬──────┘        │
│                                                │                 │
│                    ┌───────────────────────────┼───────────┐   │
│                    │                           │           │   │
│                    ▼                           ▼           ▼   │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────┐ │
│  │   Parser    │ │  Extractor  │ │   Risk      │ │ Report  │ │
│  │   文档解析  │ │   条款抽取  │ │  Identifier │ │Generator│ │
│  └─────────────┘ └─────────────┘ └─────────────┘ └─────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## 3. 工作流

```
START
  │
  ▼
┌─────────────────┐
│   contract_entry │ ── 验证输入、记录开始时间
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  contract_parse  │ ── 解析合同文档
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ contract_extract │ ── 抽取条款、当事人、元数据
└────────┬────────┘
         │
         ▼
┌─────────────────────┐
│ contract_identify_risk│ ── 识别风险、计算整体风险等级
└────────┬────────────┘
         │
         ▼
┌──────────────────────┐
│ contract_generate_report│ ── 生成审查报告
└────────┬─────────────┘
         │
         ▼
┌─────────────────┐
│  contract_finish │ ── 记录完成状态
└────────┬────────┘
         │
         ▼
        END
```

## 4. 核心组件

### 4.1 文档解析器 (LocalDocumentParser)

```python
from core.tools.local.parser import LocalDocumentParser

parser = LocalDocumentParser()
blocks = parser.parse(file_path, file_type)
```

**支持格式：**
- PDF (.pdf)
- Word (.docx, .doc)
- 文本 (.txt, .md)

### 4.2 条款抽取器 (ClauseExtractor)

```python
from core.contracts.extractor import ClauseExtractor

extractor = ClauseExtractor()
clauses, parties, metadata = await extractor.extract_clauses(
    contract_text=text,
    contract_type=ContractType.采购合同,
)
```

**功能：**
- 正则抽取甲方、乙方等当事人信息
- 提取合同金额、期限、付款方式等元数据
- 识别条款类型（标的、价款、违约责任等）
- 检测风险关键词

### 4.3 风险识别器 (RiskIdentifier)

```python
from core.contracts.risk_identifier import RiskIdentifier

identifier = RiskIdentifier()
risks, key_concerns = identifier.identify_risks(clauses)
overall_risk = identifier.calculate_overall_risk_level(risks)
```

**风险等级：**
- `CRITICAL` - 严重风险（违反法律法规）
- `HIGH` - 高风险（明显不公平）
- `MEDIUM` - 中风险（需要注意）
- `LOW` - 低风险（建议优化）

### 4.4 报告生成器 (ReportGenerator)

```python
from core.contracts.report_generator import ReportGenerator

generator = ReportGenerator()
report = generator.generate_report(
    report_id="R001",
    contract_id="C001",
    contract_name="采购合同",
    ...
)
```

## 5. API 接口

### 5.1 合同审查接口

```
POST /api/v1/review
```

**请求：**
```json
{
    "query": "审查这份采购合同",
    "contract_file_id": "contract_abc123",
    "contract_name": "设备采购合同",
    "contract_type": "采购合同",
    "user_id": "user001",
    "user_role": "user"
}
```

**响应：**
```json
{
    "review_id": "review_contract_xxx",
    "contract_id": "contract_abc123",
    "contract_name": "设备采购合同",
    "overall_risk_level": "high",
    "status": "pending_review",
    "need_human_review": true,
    "report": {
        "risk_summary": "整体风险等级：高风险...",
        "high_risk_count": 2,
        "medium_risk_count": 3,
        "low_risk_count": 1,
        "risks": [...],
        "suggestions": [...]
    },
    "processing_time_ms": 1234
}
```

### 5.2 异步审查接口

```
POST /api/v1/review/async
```

适用于大型合同文档，返回任务 ID 后可通过 `/api/v1/review/{review_id}` 查询结果。

## 6. 数据模型

### 6.1 风险枚举

```python
class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class RiskCategory(str, Enum):
    TYRANNY = "霸王条款"
    AMBIGUOUS = "模糊表述"
    VIOLATION = "违规条款"
    MISSING = "缺失条款"
    UNEQUAL = "不对等条款"
```

### 6.2 风险关键词

```python
class RiskIndicatorKeywords:
    HIGH_RISK = [
        "无条件解除", "无限责任", "免除全部责任",
        "强制仲裁", "单方解释权", "永久有效",
    ]
    MEDIUM_RISK = [
        "违约金过高", "赔偿无上限", "单方变更",
        "限制权利", "自动续期",
    ]
```

## 7. 使用示例

### 7.1 通过 A2A 协议调用

```python
from python_a2a import A2AClient

client = A2AClient()
result = await client.send_task(
    agent_name="contract-agent",
    message="审查这份采购合同",
    metadata={
        "contract_file_id": "contract_abc123",
        "contract_type": "采购合同",
    }
)
```

### 7.2 通过 HTTP API 调用

```python
import httpx

async with httpx.AsyncClient() as client:
    response = await client.post(
        "http://localhost:6003/api/v1/review",
        json={
            "query": "审查这份采购合同",
            "contract_file_id": "contract_abc123",
            "contract_type": "采购合同",
        }
    )
    result = response.json()
```

## 8. 风险判断规则

### 8.1 整体风险计算

```
CRITICAL 存在 → CRITICAL
HIGH >= 2 → HIGH
HIGH >= 1 → MEDIUM
MEDIUM >= 3 → MEDIUM
MEDIUM >= 1 → LOW
其他 → LOW
```

### 8.2 是否需要人工复核

```
HIGH 或 CRITICAL → 需要人工复核
其他 → 自动通过
```

## 9. 文件结构

```
core/
├── contracts/
│   ├── __init__.py
│   ├── models.py           # 数据模型
│   ├── extractor.py        # 条款抽取器
│   ├── risk_identifier.py  # 风险识别器
│   └── report_generator.py # 报告生成器
└── agent/workflows/contract/
    ├── __init__.py
    ├── state.py            # 状态定义
    ├── nodes.py            # 工作流节点
    └── graph.py            # StateGraph 定义
```

## 10. 启动方式

```bash
# 直接启动
uvicorn apps.agents.contract_agent_server:app --host 0.0.0.0 --port 6003

# 通过模块启动
python -m apps.agents.contract_agent_server
```

## 11. 注意事项

1. **合同文件路径** - 合同文件应存放在 `storage/uploads/` 目录下
2. **风险判断** - 高风险和严重风险条款必须经过人工复核
3. **法律依据** - 系统内置常用法律依据，但仅供参考
4. **异步处理** - 大型文档建议使用异步接口

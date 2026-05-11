# 提示词优化完整指南：以意图分类为例

> 目标：让你从"一头雾水"到"完全理解"提示词优化的判断方法、理论知识、优化步骤

---

## 一、先看一个"糟糕版"的提示词

假设我们最初的提示词是这样的：

```python
PROMPT_V0 = """
用户问题：{query}

请判断这个问题的意图：
- rag_qa: 知识问答
- analytics_query: 数据分析
- contract_review: 合同审查
- general_chat: 闲聊

直接输出意图类型。
"""
```

**你觉得这个提示词有什么问题？**

---

## 二、如何判断提示词需要优化？

### 2.1 判断标准：问题症状

| 症状 | 表现 | 说明 |
|------|------|------|
| **准确率低** | "本月光伏发电量" 被判为 rag_qa | 模型无法区分"制度问答"和"数据分析" |
| **不稳定** | 同样问题多次调用，结果不同 | 输出格式不固定 |
| **边界混淆** | "合同条款是什么"被判为 rag_qa | 合同定义和合同审查混淆 |
| **缺乏推理** | 直接输出结果，没有思考过程 | 无法追溯判断理由 |
| **槽位丢失** | 能识别意图，但无法提取时间范围 | 没有要求提取槽位 |

**如果你遇到这些问题，就需要优化提示词。**

### 2.2 测试方法

```python
# 用这些测试用例来发现问题
TEST_CASES = [
    ("本月光伏发电量是多少？", "analytics_query"),      # 期望
    ("集团差旅费报销标准", "rag_qa"),                    # 期望
    ("帮我审查合同", "contract_review"),                 # 期望
    ("你好", "general_chat"),                           # 期望
    ("发电量和收入有关系吗？", "analytics_query"),       # 期望
    ("这个制度是什么时候发布的？", "rag_qa"),            # 期望
]

def evaluate_prompt(prompt: str, test_cases: list):
    """评估提示词准确率"""
    results = []
    for query, expected in test_cases:
        actual = call_llm(prompt.format(query=query))
        results.append({
            "query": query,
            "expected": expected,
            "actual": actual,
            "correct": expected == actual
        })

    accuracy = sum(1 for r in results if r["correct"]) / len(results)
    print(f"准确率: {accuracy:.2%}")

    # 打印错误案例
    for r in results:
        if not r["correct"]:
            print(f"❌ '{r['query']}': 期望={r['expected']}, 实际={r['actual']}")
```

---

## 三、理论知识：提示词工程核心概念

### 3.1 提示词的三层结构

```
┌─────────────────────────────────────────────────────────┐
│  第一层：System Prompt（系统提示词）                      │
│  - 定义角色和身份                                        │
│  - 提供背景知识                                          │
│  - 说明任务目标                                          │
├─────────────────────────────────────────────────────────┤
│  第二层：Few-shot Examples（示例）                        │
│  - 提供 3-7 个典型案例                                   │
│  - 覆盖边界情况                                          │
│  - 展示输入-输出格式                                      │
├─────────────────────────────────────────────────────────┤
│  第三层：User Input（用户输入）                           │
│  - 当前问题                                              │
│  - 历史上下文                                            │
└─────────────────────────────────────────────────────────┘
```

### 3.2 核心技巧

| 技巧 | 作用 | 示例 |
|------|------|------|
| **角色定义** | 让模型进入正确"思维模式" | "你是一个能源集团的资深数据分析师" |
| **边界说明** | 明确什么该做，什么不该做 | "只有当问题明显是闲聊时，才识别为 general_chat" |
| **示例学习** | 通过例子让模型理解模式 | 提供 7 个覆盖各意图的示例 |
| **思维链** | 要求模型先推理再结论 | "分析：... 输出：..." |
| **格式约束** | 让输出结构化、可解析 | JSON Schema 约束 |

### 3.3 理论基础

**1. Few-shot Learning（少样本学习）**
- 原理：LLM 有"上下文学习"能力，给 3-7 个示例就能学会模式
- 作用：比纯规则更灵活，比微调更轻量

**2. Chain-of-Thought（思维链）**
- 原理：让模型"想清楚再回答"，减少"冲动错误"
- 作用：提高复杂推理准确率，方便调试

**3. 指令微调 vs 提示词工程**
- 指令微调：需要 GPU + 训练数据，周期长
- 提示词工程：改文字即可，实时生效，**优先选择**

---

## 四、优化过程：从 V0 到 V1

### 4.1 第一轮优化：添加角色和示例

**问题诊断**：
- 直接输出意图类型，太简单
- 模型不知道"能源集团"的业务背景

**优化策略**：
- 添加 System Prompt 定义角色
- 添加 Few-shot Examples

```python
PROMPT_V1 = """
你是一个企业智能问答系统的意图识别专家，服务于新疆能源集团。

## 业务背景
新疆能源集团主要业务涵盖：
- 煤炭开采与销售
- 新能源发电（光伏、风电）
- 电力生产与销售
- 设备检修与运维

## 意图类型
1. rag_qa: 知识问答（制度、安全规程、设备操作）
2. analytics_query: 数据分析（发电量、收入、利润）
3. contract_review: 合同审查
4. general_chat: 闲聊

## 示例
用户问题：请问集团差旅费报销标准是多少？
意图：rag_qa

用户问题：本月光伏发电量是多少？
意图：analytics_query

用户问题：帮我审查合同
意图：contract_review

用户问题：你好
意图：general_chat

## 当前问题
用户问题：{query}
意图：
"""
```

### 4.2 第二轮优化：解决"边界混淆"

**问题诊断**：
测试发现 "合同条款是什么" 被误判为 rag_qa，应该是 contract_review

**优化策略**：
- 明确边界，区分"询问定义"和"审查合同"
- 添加思维链（CoT）

```python
PROMPT_V2 = """
你是一个企业智能问答系统的意图识别专家。

## 意图定义
1. **rag_qa（知识问答）**：询问制度定义、操作流程、安全规程等"是什么"类问题
2. **analytics_query（数据分析）**：询问具体数值、统计数据、对比分析
3. **contract_review（合同审查）**：要求审查合同、识别风险、检查合规
4. **general_chat（闲聊）**：问候、寒暄、无业务目的

## 边界说明
- "合同条款是什么" → rag_qa（询问定义）
- "帮我审查这份合同的条款" → contract_review（审查任务）
- "本月发电量多少" → analytics_query（数据查询）
- "发电量是什么" → rag_qa（概念定义）

## 示例
用户问题：请问集团差旅费报销标准是多少？
分析：询问制度定义
意图：rag_qa

用户问题：本月光伏发电量是多少？
分析：询问具体数据
意图：analytics_query

## 当前问题
用户问题：{query}
分析：
"""
```

### 4.3 第三轮优化：结构化输出

**问题诊断**：
- 模型输出格式不固定，有时是 "rag_qa"，有时是 "知识问答"
- 无法提取置信度和槽位

**优化策略**：
- 强制 JSON 格式输出
- 添加置信度字段
- 添加槽位提取

```python
PROMPT_V3 = """
你是一个企业智能问答系统的意图识别专家。

## 输出格式
请以 JSON 格式输出：
{
    "intent_type": "rag_qa|analytics_query|contract_review|general_chat",
    "confidence": 0.0-1.0,
    "reasoning": "判断理由",
    "slot_extraction": {}
}

## 示例
输入：请问集团差旅费报销标准是多少？
输出：{"intent_type": "rag_qa", "confidence": 0.95, "reasoning": "询问制度定义", "slot_extraction": {}}

输入：本月光伏发电量是多少？和上月相比呢？
输出：{"intent_type": "analytics_query", "confidence": 0.92, "reasoning": "询问数据并要求对比", "slot_extraction": {"metric": "发电量", "time_range": "本月", "comparison": "上月"}}

## 意图定义
1. rag_qa: 知识问答（制度、安全规程、设备操作）
2. analytics_query: 数据分析（发电量、收入、利润）
3. contract_review: 合同审查（审查合同、识别风险）
4. general_chat: 闲聊

## 当前问题
{query}

输出：
"""
```

### 4.4 第四轮优化：添加更多示例 + 边界案例

**问题诊断**：
- 某些边界情况仍然出错
- "发电量和收入有关系吗" 被判为 rag_qa

**优化策略**：
- 添加更多边界示例
- 明确"分析类"和"定义类"的区别

```python
PROMPT_V4 = """
你是一个企业智能问答系统的意图识别专家。

## 输出格式
{
    "intent_type": "rag_qa|analytics_query|contract_review|general_chat",
    "confidence": 0.0-1.0,
    "reasoning": "判断理由"
}

## 示例

### rag_qa 示例
输入：请问集团差旅费报销标准是多少？
输出：{"intent_type": "rag_qa", "confidence": 0.95, "reasoning": "询问制度定义"}

输入：动火作业的安全操作规程是什么？
输出：{"intent_type": "rag_qa", "confidence": 0.96, "reasoning": "询问安全操作规程"}

输入：设备故障了怎么处理？
输出：{"intent_type": "rag_qa", "confidence": 0.88, "reasoning": "询问设备故障处理方法"}

### analytics_query 示例
输入：本月光伏发电量是多少？
输出：{"intent_type": "analytics_query", "confidence": 0.94, "reasoning": "询问具体数据"}

输入：本月收入比上月增长了多少？
输出：{"intent_type": "analytics_query", "confidence": 0.93, "reasoning": "询问数据对比"}

输入：各分公司一季度营收情况怎么样？
输出：{"intent_type": "analytics_query", "confidence": 0.91, "reasoning": "询问多维度经营数据"}

### contract_review 示例
输入：帮我审查这份采购合同的风险条款
输出：{"intent_type": "contract_review", "confidence": 0.94, "reasoning": "要求审查合同风险"}

输入：这份合同符合集团制度吗？
输出：{"intent_type": "contract_review", "confidence": 0.92, "reasoning": "要求合规检查"}

### general_chat 示例
输入：你好
输出：{"intent_type": "general_chat", "confidence": 0.98, "reasoning": "简单问候"}

## 边界说明
- "发电量是什么" → rag_qa（概念定义）
- "发电量是多少" → analytics_query（数据查询）
- "发电量和收入有关系吗" → analytics_query（数据分析）
- "合同条款是什么" → rag_qa（条款定义）
- "帮我审查这份合同" → contract_review（审查任务）

## 当前问题
{query}

输出：
"""
```

---

## 五、最终优化版（生产推荐）

### 5.1 最终版提示词

```python
# 这是我们在代码中实际使用的版本
SYSTEM_PROMPT = """你是一个企业智能问答系统的意图识别专家，服务于新疆能源集团。

你的职责是准确识别用户查询的意图，并提取关键槽位信息。

## 业务背景

新疆能源集团主要业务涵盖：
- 煤炭开采与销售
- 新能源发电（光伏、风电）
- 电力生产与销售
- 设备检修与运维
- 项目建设与管理

## 意图类型定义

1. **rag_qa（知识库问答）**：关于制度政策、安全规程、设备操作、新能源运维、项目资料等知识类问题
2. **analytics_query（经营分析）**：查询发电量、收入、利润、成本等经营数据，或需要 SQL 查询
3. **contract_review（合同审查）**：审查合同条款、识别风险、进行合规检查
4. **general_chat（通用聊天）**：问候、寒暄、无明确业务目的的对话

## 业务域分类

- policy：集团制度、报销标准、审批流程
- safety：安全生产规程、应急预案、隐患治理
- equipment：设备检修、维修、故障排查
- new_energy：光伏/风电运维、发电量分析、告警处理
- project：项目可研、环评，施工进度
- contract：合同审查、合规检查

## 输出要求

请以 JSON 格式输出，包含以下字段：
- intent_type: 意图类型
- business_domain: 业务域（可选）
- routing_target: 路由目标（rag_agent/analytics_agent/contract_agent/supervisor）
- confidence: 置信度（0-1）
- reasoning: 识别理由
- requires_clarification: 是否需要澄清
- clarification_questions: 澄清问题列表（如需澄清）
- slot_extraction: 槽位提取结果

## 注意事项

1. 当意图模糊时，优先选择更具体的意图
2. 涉及数据查询的分析类问题，优先识别为 analytics_query
3. 合同相关问题，优先识别为 contract_review
4. 只有当问题明显属于闲聊时，才识别为 general_chat"""

FEW_SHOT_EXAMPLES = """
## 示例 1

用户问题：请问集团差旅费报销标准是多少？

分析：
- 询问集团制度/报销标准
- 属于知识库问答
- 业务域：policy

输出：
```json
{
    "intent_type": "rag_qa",
    "business_domain": "policy",
    "routing_target": "rag_agent",
    "confidence": 0.95,
    "reasoning": "用户询问集团差旅费报销标准，属于集团制度政策类问题，应由RAG Agent处理"
}
```

## 示例 2

用户问题：本月光伏电站发电量是多少？和上月相比增长了多少？

分析：
- 询问发电量数据
- 涉及环比分析
- 需要 SQL 查询经营数据

输出：
```json
{
    "intent_type": "analytics_query",
    "business_domain": "new_energy",
    "routing_target": "analytics_agent",
    "confidence": 0.92,
    "reasoning": "用户询问发电量数据并要求环比分析，涉及经营数据查询，应由Analytics Agent处理"
}
```

## 示例 3

用户问题：帮我审查一下这份采购合同的风险条款

分析：
- 审查合同风险条款
- 属于合同审查

输出：
```json
{
    "intent_type": "contract_review",
    "business_domain": "contract",
    "routing_target": "contract_agent",
    "confidence": 0.94,
    "reasoning": "用户明确要求审查合同风险条款，属于合同审查范畴，应由Contract Agent处理"
}
```

## 示例 4

用户问题：动火作业的安全操作规程是什么？

分析：
- 询问安全操作规程
- 属于安全生产知识

输出：
```json
{
    "intent_type": "rag_qa",
    "business_domain": "safety",
    "routing_target": "rag_agent",
    "confidence": 0.96,
    "reasoning": "用户询问动火作业安全操作规程，属于安全生产知识问答，应由RAG Agent处理"
}
```

## 示例 5

用户问题：你好

分析：
- 简单问候
- 无明确业务目的

输出：
```json
{
    "intent_type": "general_chat",
    "business_domain": null,
    "routing_target": "rag_agent",
    "confidence": 0.98,
    "reasoning": "用户发送问候语，属于通用聊天，应由RAG Agent处理"
}
```

## 示例 6

用户问题：设备故障了怎么办

分析：
- 询问设备故障处理
- 属于设备检修问答

输出：
```json
{
    "intent_type": "rag_qa",
    "business_domain": "equipment",
    "routing_target": "rag_agent",
    "confidence": 0.88,
    "reasoning": "用户询问设备故障处理方法，属于设备检修知识问答，应由RAG Agent处理"
}
```

## 示例 7

用户问题：各分公司一季度营收情况怎么样？

分析：
- 询问营收数据
- 涉及多维度经营分析
- 需要 SQL 查询

输出：
```json
{
    "intent_type": "analytics_query",
    "business_domain": null,
    "routing_target": "analytics_agent",
    "confidence": 0.91,
    "reasoning": "用户询问各分公司营收情况，涉及经营数据汇总分析，应由Analytics Agent处理"
}
```"""
```

### 5.2 优化对比表

| 版本 | 问题 | 优化手段 | 准确率 |
|------|------|----------|--------|
| V0 | 太简单，无法区分意图 | 添加角色和业务背景 | ~60% |
| V1 | 边界混淆 | 添加边界说明 + CoT | ~75% |
| V2 | 输出格式不固定 | 强制 JSON + 置信度 | ~82% |
| V3 | 边界案例仍出错 | 添加更多示例 | ~90% |
| V4（最终） | - | 完整示例 + 业务域 | ~95% |

---

## 六、优化 Checklist（以后优化提示词照着做）

```markdown
### 1. 结构检查
- [ ] 是否有 System Prompt（角色定义）
- [ ] 是否有 Few-shot Examples（至少 5 个）
- [ ] 是否有输出格式说明（JSON Schema）

### 2. 准确率检查
- [ ] 意图准确率 > 90%
- [ ] 边界案例是否测试过
- [ ] 置信度是否合理（0.85-0.98）

### 3. 完整性检查
- [ ] 是否覆盖所有意图类型
- [ ] 是否有边界说明
- [ ] 是否有错误案例说明

### 4. 可维护性检查
- [ ] 示例是否易于添加/修改
- [ ] 注释是否清晰
- [ ] 版本是否有记录
```

---

## 七、常见问题

**Q1: Few-shot 示例越多越好吗？**

A: 不是，3-7 个最佳。太多会增加 token 消耗和干扰。

**Q2: 什么时候用 CoT？**

A: 复杂推理时用（如意图模糊、边界情况）。简单场景可以不加。

**Q3: 提示词优化和微调怎么选？**

A: 优先提示词优化，成本低、见效快。如果准确率仍不满足，再考虑微调。

**Q4: 怎么判断优化是否有效？**

A: 用固定的测试集，每次优化后跑一遍，对比准确率。

---

## 八、参考资源

- [Prompt Engineering Guide](https://www.promptingguide.ai/)
- [OpenAI Prompt Best Practices](https://help.openai.com/en/articles/6654000-best-practices-for-prompting)
- [Anthropic Prompt Engineering](https://docs.anthropic.com/claude/docs)

---

*本文档帮助你理解提示词优化的完整过程。核心是：通过测试发现问题 → 针对问题优化 → 验证效果。*

- # 新疆能源集团知识与生产经营智能 Agent 平台 产品需求文档 

  ## 1. 文档说明

  本文档为 **新疆能源集团知识与生产经营智能 Agent 平台** 的产品需求文档 v3 版本。

  本版本采用 **生产级完整建设模式**，不再按照“先 MVP、后高级功能”的方式拆分需求，而是从一开始按照最终生产级系统形态进行产品、架构和功能设计。

  开发过程仍然可以按模块逐步实现，但所有模块都必须遵循最终生产级架构标准，避免先写临时 Demo、后期大规模重构。

  ---

  ## 2. 项目名称

  ### 2.1 产品中文名

  **新疆能源集团知识与生产经营智能 Agent 平台**

  ### 2.2 产品英文名

  **Enterprise Knowledge Agentic RAG Platform**

  ### 2.3 推荐仓库名

  ```text
  enterprise-knowledge-agentic-rag
  ```

  ### 2.4 项目副标题

  面向煤炭、新能源、安全生产、设备运维、经营分析、合同合规、项目建设与企业流程协同的生产级 Agentic RAG 系统。

  ---

  ## 3. 建设原则

  本项目采用 **终局架构驱动开发** 思路。

  ### 3.1 不采用临时 Demo 模式

  本项目不以“先做一个简单 RAG 问答 Demo”为目标，而是从一开始就按照企业生产级系统进行设计。

  系统需要完整考虑：

  - 多业务知识库
  - 多角色权限
  - 多业务 Agent
  - RAG 检索增强
  - SQL 数据分析
  - 合同合规审查
  - Human-in-the-loop 人工复核
  - MCP 工具接入
  - Trace 审计
  - Evaluation 评估体系
  - 前端管理页面
  - 私有化部署
  - 可观测性
  - 安全合规

  ### 3.2 架构一次性按最终形态设计

  系统架构、模块边界、数据模型、Agent 工作流、权限模型、工具调用模型、Trace 模型和评估模型都按照最终生产形态设计。

  即使某些模块后续分批编码，也不能在架构上临时处理。

  ### 3.3 代码按模块逐步落地

  虽然产品能力按完整版本设计，但代码开发仍然按模块逐步推进。

  推荐开发顺序：

  1. 项目文档与架构设计
  2. 项目工程骨架
  3. 用户、组织、角色、权限基础模型
  4. 知识库与文档管理
  5. 文档解析、切分、索引
  6. RAG 检索服务
  7. Agent 编排服务
  8. 业务 Agent 能力
  9. SQL 数据分析能力
  10. 合同审查能力
  11. Human Review 能力
  12. MCP 工具接入
  13. Trace 与审计
  14. Evaluation 评估
  15. 前端管理页面
  16. 部署与可观测性

  ---

  ## 4. 项目背景

  新疆能源（集团）有限责任公司作为能源类集团企业，业务场景覆盖煤炭生产、新能源开发、能源服务、供应链管理、项目建设、安全生产、经营分析、合同合规等多个方向。

  集团内部存在大量文档、制度、规程、报表和业务数据，例如：

  - 集团制度文件
  - 安全生产规程
  - 岗位操作手册
  - 设备检修手册
  - 事故案例资料
  - 应急预案
  - 作业票管理制度
  - 合同模板
  - 采购合同
  - 销售合同
  - 项目可研报告
  - 环评、安评、能评资料
  - 项目会议纪要
  - 经营分析报表
  - 煤炭产量数据
  - 煤炭销售数据
  - 新能源发电量数据
  - 设备告警数据
  - 检修工单数据
  - 供应链业务数据

  这些数据存在以下典型问题：

  ### 4.1 知识分散

  文档分散在不同部门、系统和人员手中，知识查询依赖人工经验，效率低。

  ### 4.2 制度复杂

  集团制度、安全规程、合同制度、项目管理制度内容多、层级多、版本多，人工检索容易遗漏或引用旧版本。

  ### 4.3 安全生产要求高

  煤炭生产、设备检修、危险作业、新能源电站运维等场景涉及安全风险，AI 系统必须做到有依据、可追踪、可审计、可复核。

  ### 4.4 设备运维经验难沉淀

  设备故障处理依赖设备手册、检修记录、历史工单和人员经验，缺少统一的知识复用入口。

  ### 4.5 经营分析成本高

  经营管理人员需要从多个业务表和报表中整理数据，人工写 SQL、导出 Excel、生成报告耗时较长。

  ### 4.6 合同合规压力大

  煤炭销售、设备采购、工程建设、供应链贸易、新能源项目等合同数量多，风险条款识别依赖人工审查。

  ### 4.7 AI 应用必须可控

  能源集团场景不能只做普通聊天机器人，系统必须支持权限控制、风险判断、人工复核、Trace 追踪和审计日志。

  ---

  ## 5. 产品定位

  本项目定位为：

  > 面向新疆能源集团内部知识、生产、安全、经营、合同和项目资料的智能 Agent 平台。

  系统以企业知识库和业务数据为基础，以 Agent 为任务调度核心，通过 RAG、工具调用、SQL 查询、合同审查、人工复核、权限控制和审计追踪能力，为集团内部用户提供统一智能入口。

  系统不是单纯的：

  ```text
  文档问答系统
  聊天机器人
  知识库搜索
  SQL 生成器
  ```

  而是一个综合性的：

  ```text
  企业知识库
    +
  业务场景 Agent
    +
  RAG 检索增强
    +
  SQL 数据分析
    +
  合同审查
    +
  工具调用
    +
  权限安全
    +
  Human Review
    +
  Trace 审计
    +
  Evaluation 评估
  ```

  ---

  ## 6. 产品目标

  ### 6.1 业务目标

  1. 建设新疆能源集团统一智能知识入口。
  2. 提升制度、规程、手册、项目资料的查询效率。
  3. 辅助安全生产人员快速查询规程和处置流程。
  4. 辅助设备运维人员进行故障排查和检修建议生成。
  5. 辅助新能源运维人员分析电站异常和设备告警。
  6. 辅助经营分析人员进行自然语言数据查询和报告生成。
  7. 辅助法务、采购、供应链人员识别合同风险。
  8. 辅助项目管理人员查询项目资料、识别审批缺失和进度风险。
  9. 形成可追踪、可审计、可复核的企业 AI 应用体系。

  ### 6.2 工程目标

  1. 构建生产级 Agentic RAG 系统。
  2. 支持多知识库、多业务域、多角色权限。
  3. 支持文档解析、切分、向量化、检索、重排序。
  4. 支持 Agent 对业务场景进行路由和工具选择。
  5. 支持 SQL 安全查询和经营分析。
  6. 支持合同条款抽取和风险识别。
  7. 支持 Human-in-the-loop 人工复核。
  8. 支持 MCP 或类似协议的外部工具接入。
  9. 支持完整 Trace、审计和评估。
  10. 支持私有化部署和可观测性。

  ### 6.3 展示目标

  本项目需要能够作为高级 AI 工程师项目展示，体现：

  - 真实行业背景
  - 复杂业务建模能力
  - 生产级 RAG 架构能力
  - Agent 工作流设计能力
  - 工具调用与权限安全能力
  - 数据分析 Agent 能力
  - 审计与评估能力
  - 工程化落地能力

  ---

  ## 7. 目标用户

  ### 7.1 普通员工

  使用制度政策、流程规范、通知公告等知识问答能力。

  典型问题：

  - 集团差旅报销标准是什么？
  - 合同审批流程需要经过哪些部门？
  - 员工安全培训制度有哪些要求？
  - 项目立项需要提交哪些材料？

  ### 7.2 安全生产管理人员

  使用安全生产规程、操作规范、事故案例、隐患治理等知识。

  典型问题：

  - 动火作业前需要办理哪些审批？
  - 进入有限空间作业前需要做哪些检测？
  - 露天煤矿边坡巡检有哪些要求？
  - 设备检修挂牌上锁流程是什么？

  ### 7.3 设备运维与检修人员

  使用设备手册、点检标准、检修规程、历史故障记录。

  典型问题：

  - 皮带输送机跑偏有哪些常见原因？
  - 斗轮机运行异响应该怎么排查？
  - 变压器温度过高可能是什么原因？
  - 风机振动异常如何处理？

  ### 7.4 新能源电站运维人员

  使用光伏、风电、储能、电站巡检、设备告警和发电数据。

  典型问题：

  - 某光伏电站发电量连续三天下降，可能原因是什么？
  - 逆变器 E101 告警是什么意思？
  - 风电场停机率升高应该重点排查哪些问题？
  - 储能系统温度异常需要检查哪些项目？

  ### 7.5 经营分析人员

  使用煤炭产量、销售收入、新能源发电量、成本利润、供应链数据等。

  典型问题：

  - 统计本月各矿区煤炭产量完成情况。
  - 分析最近三个月煤炭销售收入变化原因。
  - 对比新能源板块和煤炭板块利润变化。
  - 生成本月经营分析简报。

  ### 7.6 法务、采购与供应链人员

  使用合同模板、采购制度、供应商资料、合规制度。

  典型问题：

  - 这份煤炭采购合同有哪些风险？
  - 合同付款条件是否符合集团制度？
  - 设备采购合同中质保条款是否完整？
  - 工程合同中安全责任是否明确？

  ### 7.7 项目管理人员

  使用项目可研、审批文件、环评、安评、能评、施工进度资料。

  典型问题：

  - 这个新能源项目还缺少哪些审批材料？
  - 可研报告中项目建设条件有哪些？
  - 环评批复中有哪些约束要求？
  - 项目施工进度滞后的风险是什么？

  ### 7.8 系统管理员

  负责系统配置、用户权限、知识库管理、工具管理、Trace 审计和模型配置。

  ---

  ## 8. 完整业务场景

  ### 8.1 集团制度政策问答

  系统需要支持对集团制度、流程规范、管理办法、通知文件的智能问答。

  #### 8.1.1 数据来源

  - 集团管理制度
  - 采购管理办法
  - 合同管理办法
  - 财务报销制度
  - 人事培训制度
  - 项目管理制度
  - 安全培训制度

  #### 8.1.2 核心能力

  - 制度条款检索
  - 版本识别
  - 部门范围识别
  - 引用来源返回
  - 过期制度提醒
  - 多制度交叉回答

  #### 8.1.3 输出要求

  回答必须包含：

  - 直接结论
  - 引用制度名称
  - 引用章节
  - 适用范围
  - 版本或生效日期，若有
  - 不确定性说明，若知识库证据不足

  ---

  ### 8.2 安全生产规程问答

  系统需要支持安全生产、危险作业、事故预案、隐患治理等问答。

  #### 8.2.1 数据来源

  - 安全生产责任制
  - 岗位操作规程
  - 动火作业制度
  - 有限空间作业制度
  - 高处作业制度
  - 设备检修安全规程
  - 应急预案
  - 事故案例材料

  #### 8.2.2 核心能力

  - 作业类型识别
  - 风险等级判断
  - 安全规程检索
  - 事故案例检索
  - 安全措施生成
  - 高风险问题人工复核
  - 禁止无依据建议

  #### 8.2.3 风险控制

  安全类问题必须遵循：

  1. 答案必须基于知识库证据。
  2. 不得编造现场操作流程。
  3. 高风险问题必须标记风险等级。
  4. 涉及现场作业的问题必须提示以正式制度和现场负责人确认为准。
  5. 无明确依据时必须回答“知识库中未找到明确依据”。

  ---

  ### 8.3 设备检修与故障排查

  系统需要支持设备故障分析、点检建议、检修步骤、备件建议等能力。

  #### 8.3.1 数据来源

  - 设备说明书
  - 点检标准
  - 检修规程
  - 故障案例
  - 历史工单
  - 备品备件清单
  - 运维经验库

  #### 8.3.2 核心能力

  - 设备类型识别
  - 故障现象识别
  - 可能原因排序
  - 排查步骤生成
  - 安全注意事项生成
  - 检修工单草稿生成
  - 历史案例引用

  #### 8.3.3 输出要求

  输出应包含：

  - 故障现象理解
  - 可能原因
  - 排查顺序
  - 安全注意事项
  - 需要查看的数据或参数
  - 可能涉及的备件
  - 引用来源

  ---

  ### 8.4 新能源电站运维辅助

  系统需要支持光伏、风电、储能等新能源业务的运维辅助。

  #### 8.4.1 数据来源

  - 光伏运维手册
  - 风电运维手册
  - 储能设备手册
  - 逆变器告警码手册
  - 电站巡检记录
  - 发电量数据
  - 气象数据
  - 告警数据
  - 工单数据

  #### 8.4.2 核心能力

  - 电站类型识别
  - 告警码解释
  - 发电异常分析
  - 停机率异常分析
  - 设备故障原因分析
  - 运维建议生成
  - 数据工具调用

  #### 8.4.3 输出要求

  输出应包含：

  - 异常现象总结
  - 可能原因
  - 建议排查指标
  - 相关设备或系统
  - 风险等级
  - 引用来源

  ---

  ### 8.5 合同与合规审查

  系统需要支持合同解析、条款抽取、制度对比、风险识别和人工复核。

  #### 8.5.1 数据来源

  - 合同模板
  - 合同管理办法
  - 采购管理制度
  - 法务审查规则
  - 历史合同案例
  - 供应商管理制度
  - 安全环保责任条款模板

  #### 8.5.2 核心能力

  - 合同类型识别
  - 合同主体识别
  - 金额、付款、交付、验收、违约责任抽取
  - 与标准模板对比
  - 风险条款识别
  - 风险等级划分
  - 法务复核流程
  - 审查报告生成

  #### 8.5.3 风险等级

  | 风险等级 | 说明                                                   |
  | -------- | ------------------------------------------------------ |
  | low      | 表述不规范，但业务风险较低                             |
  | medium   | 条款缺失或责任不清，需要修改                           |
  | high     | 涉及重大金额、违约责任、安全环保责任缺失，需要人工复核 |
  | critical | 存在明显重大风险，禁止直接通过                         |

  ---

  ### 8.6 经营数据分析

  系统需要支持自然语言查询经营数据，并生成分析结论。

  #### 8.6.1 数据来源

  - 煤炭产量表
  - 煤炭销售收入表
  - 新能源发电量表
  - 成本利润表
  - 供应链业务表
  - 客户信息表
  - 项目进度表
  - 预算执行表

  #### 8.6.2 核心能力

  - 自然语言理解
  - 数据表 schema 理解
  - SQL 生成
  - SQL 安全校验
  - 只读查询
  - 查询结果解释
  - 图表生成
  - 经营分析报告生成
  - 查询审计

  #### 8.6.3 SQL 安全要求

  1. 默认只允许 SELECT。
  2. 禁止 INSERT、UPDATE、DELETE、DROP、ALTER、TRUNCATE。
  3. 自动添加 LIMIT。
  4. 使用只读数据库账号。
  5. 敏感字段必须做权限校验。
  6. 所有 SQL 必须记录审计日志。
  7. 大查询需要限制返回行数。
  8. 高风险查询需要人工确认。

  ---

  ### 8.7 项目建设资料问答

  系统需要支持项目立项、可研、环评、安评、能评、施工、验收等资料问答。

  #### 8.7.1 数据来源

  - 项目可研报告
  - 环评批复
  - 安评报告
  - 能评报告
  - 土地手续
  - 项目会议纪要
  - 施工进度资料
  - 验收资料
  - 政策文件

  #### 8.7.2 核心能力

  - 项目名称识别
  - 项目阶段识别
  - 审批材料检索
  - 缺失材料识别
  - 项目风险提示
  - 项目摘要生成
  - 会议纪要总结

  ---

  ### 8.8 报告生成

  系统需要支持基于知识库、经营数据和用户要求生成报告。

  #### 8.8.1 报告类型

  - 安全生产分析报告
  - 设备故障分析报告
  - 月度经营分析报告
  - 合同风险审查报告
  - 项目进展报告
  - 新能源电站运维分析报告

  #### 8.8.2 核心能力

  - 多来源资料汇总
  - 自动生成报告大纲
  - 引用资料溯源
  - 结构化输出
  - 风险提示
  - 人工审核
  - 导出为 Markdown、Word 或 PDF

  ---

  ## 9. 完整功能范围

  ### 9.1 用户与组织权限模块

  系统需要支持：

  - 用户管理
  - 部门管理
  - 角色管理
  - 权限管理
  - 知识库访问权限
  - 文档访问权限
  - 工具调用权限
  - SQL 查询权限
  - Trace 查看权限
  - 人工审核权限

  ### 9.2 知识库管理模块

  系统需要支持：

  - 多知识库创建
  - 知识库分类
  - 知识库权限配置
  - 知识库状态管理
  - 知识库文档统计
  - 知识库检索配置
  - 知识库评估集管理

  ### 9.3 文档管理模块

  系统需要支持：

  - 文档上传
  - 文档元数据录入
  - 文档版本管理
  - 文档权限管理
  - 文档状态管理
  - 文档删除与重建索引
  - 文档解析日志
  - 文档索引日志

  ### 9.4 文档解析模块

  系统需要支持：

  - TXT 解析
  - Markdown 解析
  - PDF 解析
  - DOCX 解析
  - Excel 解析
  - HTML 解析
  - OCR 预留或接入
  - 解析失败重试
  - 解析结果标准化

  ### 9.5 文档切分模块

  系统需要支持：

  - 固定长度切分
  - 按标题层级切分
  - 语义切分
  - parent-child chunk
  - chunk overlap
  - 页码保留
  - 章节保留
  - 元数据继承
  - 权限信息继承

  ### 9.6 向量化与索引模块

  系统需要支持：

  - Embedding 生成
  - 批量向量化
  - 增量索引
  - 重建索引
  - 删除索引
  - 向量库写入
  - 稀疏向量预留
  - 索引状态监控

  ### 9.7 RAG 检索模块

  系统需要支持：

  - Dense Retrieval
  - Sparse Retrieval
  - Hybrid Search
  - BM25 检索
  - Rerank
  - Query Rewrite
  - Multi-query Retrieval
  - HyDE
  - Context Compression
  - Metadata Filter
  - 权限过滤
  - 引用来源返回

  ### 9.8 Agent 编排模块

  系统需要支持：

  - 用户问题理解
  - 业务场景路由
  - 工具选择
  - 多节点工作流
  - 条件分支
  - 错误重试
  - Human Review 中断
  - 状态恢复
  - 多轮上下文
  - 最终答案生成
  - 执行轨迹记录

  ### 9.9 业务 Agent 模块

  系统需要支持以下业务 Agent：

  - 制度政策问答 Agent
  - 安全生产 Agent
  - 设备检修 Agent
  - 新能源运维 Agent
  - 合同审查 Agent
  - 经营分析 Agent
  - 项目资料 Agent
  - 报告生成 Agent

  ### 9.10 工具调用模块

  系统需要支持：

  - RAG 检索工具
  - 文档读取工具
  - SQL 查询工具
  - 合同审查工具
  - 报告生成工具
  - 邮件草稿工具
  - 工单草稿工具
  - 外部 API 工具
  - MCP 工具代理
  - 工具权限校验
  - 工具风险等级
  - 工具调用审计

  ### 9.11 SQL 分析模块

  系统需要支持：

  - schema 读取
  - 表字段解释
  - 自然语言转 SQL
  - SQL 安全校验
  - 只读执行
  - 查询结果解释
  - 图表生成
  - 分析报告生成
  - SQL Trace

  ### 9.12 Human Review 模块

  系统需要支持：

  - 高风险任务识别
  - 审核任务创建
  - 审核人分配
  - 审核通过
  - 审核拒绝
  - 审核意见记录
  - 审核后继续执行
  - 审核日志追踪

  ### 9.13 Trace 与审计模块

  系统需要支持：

  - Agent Run 记录
  - Tool Call 记录
  - Retrieval Log 记录
  - LLM Call 记录
  - SQL Query 记录
  - Human Review 记录
  - 错误日志
  - 延迟统计
  - Token 统计
  - 成本统计
  - Trace 查询

  ### 9.14 Evaluation 评估模块

  系统需要支持：

  - 检索召回率评估
  - 答案忠实度评估
  - 答案相关性评估
  - 工具调用准确率评估
  - Agent 路由准确率评估
  - SQL 正确率评估
  - 合同风险识别评估
  - 人工评分
  - 评估集管理
  - 评估报告生成

  ### 9.15 前端管理模块

  系统需要支持：

  - 登录页面
  - 知识库管理
  - 文档上传与管理
  - 智能问答页面
  - 合同审查页面
  - 经营分析页面
  - Trace 查看页面
  - Human Review 审核页面
  - 系统配置页面
  - 评估结果页面

  ### 9.16 部署运维模块

  系统需要支持：

  - 本地开发启动
  - Docker Compose 部署
  - 生产环境配置
  - 服务健康检查
  - 日志输出
  - 可观测性接入
  - 模型服务配置
  - 数据库初始化
  - 向量库初始化
  - 环境变量管理

  ---

  ## 10. 知识库设计

  ### 10.1 业务知识库类型

  | 知识库 ID                | 中文名称           | 主要内容                       |
  | ------------------------ | ------------------ | ------------------------------ |
  | group_policy_kb          | 集团制度政策知识库 | 集团制度、流程、管理办法       |
  | safety_production_kb     | 安全生产知识库     | 安全规程、作业制度、事故案例   |
  | equipment_maintenance_kb | 设备运维知识库     | 设备手册、检修规程、工单案例   |
  | new_energy_ops_kb        | 新能源运维知识库   | 光伏、风电、储能运维资料       |
  | contract_compliance_kb   | 合同与合规知识库   | 合同模板、法务规则、采购制度   |
  | project_management_kb    | 项目建设知识库     | 可研、审批、会议纪要、进度资料 |
  | operation_analysis_kb    | 经营分析知识库     | 指标口径、报表说明、分析模板   |

  ### 10.2 文档元数据

  每份文档应包含：

  ```json
  {
    "document_id": "doc_xxx",
    "title": "动火作业安全管理制度",
    "filename": "动火作业安全管理制度.pdf",
    "file_type": "pdf",
    "business_domain": "safety_production",
    "knowledge_base_id": "safety_production_kb",
    "department": "安全生产部",
    "version": "2025-v1",
    "effective_date": "2025-01-01",
    "security_level": "internal",
    "access_scope": ["admin", "safety_manager"],
    "uploaded_by": "user_xxx",
    "status": "indexed"
  }
  ```

  ### 10.3 Chunk 元数据

  每个 chunk 应包含：

  ```json
  {
    "chunk_id": "chunk_xxx",
    "document_id": "doc_xxx",
    "knowledge_base_id": "safety_production_kb",
    "business_domain": "safety_production",
    "content": "chunk 内容",
    "chunk_index": 12,
    "page": 8,
    "section": "第三章 动火作业管理",
    "security_level": "internal",
    "access_scope": ["admin", "safety_manager"],
    "embedding_model": "待定"
  }
  ```

  ---

  ## 11. Agent 能力设计

  ### 11.1 Agent 总体职责

  Agent 负责：

  1. 理解用户问题。
  2. 识别业务领域。
  3. 判断任务类型。
  4. 选择知识库。
  5. 判断是否需要工具调用。
  6. 判断是否需要 SQL。
  7. 判断是否需要合同审查。
  8. 判断是否需要 Human Review。
  9. 调用对应工具。
  10. 汇总证据。
  11. 生成答案。
  12. 输出引用。
  13. 记录 Trace。
  14. 进入评估流程。

  ### 11.2 Agent 路由类型

  | Route                 | 说明             |
  | --------------------- | ---------------- |
  | policy_qa             | 集团制度政策问答 |
  | safety_qa             | 安全生产规程问答 |
  | equipment_qa          | 设备检修问答     |
  | new_energy_ops_qa     | 新能源运维问答   |
  | contract_review       | 合同合规审查     |
  | project_qa            | 项目资料问答     |
  | business_analysis     | 经营数据分析     |
  | report_generation     | 报告生成         |
  | human_review_required | 需要人工复核     |
  | unsupported           | 暂不支持         |

  ### 11.3 Agent State

  ```json
  {
    "run_id": "run_xxx",
    "user_id": "user_xxx",
    "user_role": "safety_manager",
    "query": "动火作业前需要做哪些安全确认？",
    "route": "safety_qa",
    "business_domain": "safety_production",
    "knowledge_base_ids": ["safety_production_kb"],
    "messages": [],
    "retrieved_chunks": [],
    "tool_calls": [],
    "sql_queries": [],
    "risk_level": "high",
    "need_human_review": true,
    "review_status": "pending",
    "final_answer": "",
    "status": "running"
  }
  ```

  ### 11.4 Agent 工作流

  ```text
  用户输入
    ↓
  身份与权限上下文注入
    ↓
  问题理解
    ↓
  业务场景路由
    ↓
  风险初判
    ↓
  选择知识库 / 工具 / SQL / 合同审查
    ↓
  执行检索或工具调用
    ↓
  证据汇总
    ↓
  答案生成
    ↓
  风险复判
    ↓
  是否需要人工复核？
    ├── 是：创建 Human Review 任务
    └── 否：返回答案
    ↓
  记录 Trace
    ↓
  进入评估与反馈闭环
  ```

  ---

  ## 12. 权限与安全需求

  ### 12.1 用户角色

  | 角色                | 说明             |
  | ------------------- | ---------------- |
  | admin               | 系统管理员       |
  | group_manager       | 集团管理人员     |
  | safety_manager      | 安全生产管理人员 |
  | equipment_engineer  | 设备运维人员     |
  | new_energy_operator | 新能源运维人员   |
  | business_analyst    | 经营分析人员     |
  | legal_user          | 法务人员         |
  | project_manager     | 项目管理人员     |
  | employee            | 普通员工         |

  ### 12.2 权限控制对象

  系统需要控制：

  - 知识库访问权限
  - 文档访问权限
  - Chunk 检索权限
  - 工具调用权限
  - SQL 查询权限
  - 敏感字段访问权限
  - Human Review 审核权限
  - Trace 查看权限
  - 系统配置权限

  ### 12.3 高风险内容控制

  以下任务属于高风险：

  - 安全生产操作建议
  - 危险作业处置建议
  - 设备带电检修建议
  - 合同重大风险判断
  - 经营敏感数据查询
  - 外部系统写操作
  - 邮件正式发送
  - 工单正式提交

  ### 12.4 风险等级策略

  | 风险等级 | 处理策略                         |
  | -------- | -------------------------------- |
  | low      | 直接执行并记录日志               |
  | medium   | 执行并输出风险提示               |
  | high     | 创建人工复核任务                 |
  | critical | 拒绝自动执行，并提示联系责任部门 |

  ### 12.5 数据安全要求

  1. 密钥不得提交 Git。
  2. 所有密钥必须通过环境变量或密钥管理系统读取。
  3. 经营敏感数据必须做权限校验。
  4. 检索必须强制应用 metadata filter。
  5. SQL 查询必须记录审计日志。
  6. 工具调用必须记录输入输出。
  7. 高风险任务必须进入人工复核。
  8. 用户不能访问无权限文档和 Trace。
  9. 模型输出必须基于证据，不允许编造制度条款。
  10. 私有化部署优先。

  ---

  ## 13. Trace 与审计要求

  系统必须记录完整执行链路。

  ### 13.1 Agent Run

  记录一次用户请求的完整执行过程。

  字段包括：

  - run_id
  - user_id
  - user_role
  - query
  - route
  - business_domain
  - risk_level
  - status
  - final_answer
  - started_at
  - ended_at
  - latency_ms
  - error_message

  ### 13.2 Tool Call

  字段包括：

  - tool_call_id
  - run_id
  - tool_name
  - input_json
  - output_json
  - risk_level
  - status
  - latency_ms
  - error_message
  - created_at

  ### 13.3 Retrieval Log

  字段包括：

  - retrieval_id
  - run_id
  - query
  - knowledge_base_id
  - document_id
  - chunk_id
  - score
  - rank
  - content_preview
  - created_at

  ### 13.4 LLM Call

  字段包括：

  - llm_call_id
  - run_id
  - model_name
  - prompt_template
  - input_tokens
  - output_tokens
  - latency_ms
  - status
  - error_message
  - created_at

  ### 13.5 SQL Audit

  字段包括：

  - sql_audit_id
  - run_id
  - user_id
  - generated_sql
  - checked_sql
  - is_safe
  - blocked_reason
  - execution_status
  - row_count
  - latency_ms
  - created_at

  ### 13.6 Human Review Log

  字段包括：

  - review_id
  - run_id
  - risk_level
  - review_status
  - reviewer_id
  - review_comment
  - created_at
  - reviewed_at

  ---

  ## 14. Evaluation 评估要求

  系统需要内置评估体系，支持离线评估和线上反馈。

  ### 14.1 RAG 评估指标

  - Retrieval Recall
  - Context Precision
  - Context Recall
  - Answer Faithfulness
  - Answer Relevancy
  - Citation Accuracy
  - Hallucination Rate

  ### 14.2 Agent 评估指标

  - Route Accuracy
  - Tool Call Accuracy
  - Task Success Rate
  - Human Review Trigger Accuracy
  - Error Recovery Rate
  - Multi-turn Completion Rate

  ### 14.3 SQL Agent 评估指标

  - SQL Validity
  - SQL Safety
  - Execution Accuracy
  - Result Explanation Accuracy
  - Sensitive Field Violation Rate

  ### 14.4 合同审查评估指标

  - Risk Identification Recall
  - Risk Classification Accuracy
  - Clause Extraction Accuracy
  - False Positive Rate
  - Human Reviewer Agreement Rate

  ### 14.5 运行指标

  - Latency P50 / P95 / P99
  - Token Usage
  - Cost Per Task
  - Error Rate
  - Timeout Rate
  - Tool Failure Rate
  - Retrieval Empty Rate

  ---

  ## 15. 前端页面需求

  ### 15.1 登录与用户上下文页面

  - 用户登录
  - 当前角色展示
  - 当前部门展示
  - 权限范围展示

  ### 15.2 智能问答页面

  - 输入自然语言问题
  - 选择或自动识别业务场景
  - 展示答案
  - 展示引用来源
  - 展示风险等级
  - 展示 Trace ID

  ### 15.3 知识库管理页面

  - 知识库列表
  - 创建知识库
  - 查看知识库文档
  - 配置知识库权限
  - 查看索引状态

  ### 15.4 文档管理页面

  - 上传文档
  - 填写文档元数据
  - 查看文档状态
  - 查看解析结果
  - 查看 chunk
  - 重新索引
  - 删除文档

  ### 15.5 合同审查页面

  - 上传合同
  - 查看条款抽取结果
  - 查看风险点
  - 查看风险等级
  - 提交人工复核

  ### 15.6 经营分析页面

  - 输入自然语言分析问题
  - 查看生成 SQL
  - 查看 SQL 安全检查
  - 查看查询结果
  - 查看图表
  - 生成分析报告

  ### 15.7 Human Review 页面

  - 查看待审核任务
  - 查看原始问题
  - 查看 Agent 答案
  - 查看引用证据
  - 审核通过
  - 审核拒绝
  - 填写审核意见

  ### 15.8 Trace 页面

  - 查询 Agent Run
  - 查看工具调用链路
  - 查看检索结果
  - 查看 LLM 调用
  - 查看 SQL 审计
  - 查看错误日志

  ### 15.9 Evaluation 页面

  - 创建评估集
  - 运行评估任务
  - 查看评估指标
  - 查看失败样本
  - 导出评估报告

  ---

  ## 16. 核心接口草案

  ### 16.1 健康检查

  ```http
  GET /health
  ```

  ### 16.2 文档上传

  ```http
  POST /api/v1/documents/upload
  ```

  ### 16.3 文档列表

  ```http
  GET /api/v1/documents
  ```

  ### 16.4 文档详情

  ```http
  GET /api/v1/documents/{document_id}
  ```

  ### 16.5 文档重新索引

  ```http
  POST /api/v1/documents/{document_id}/reindex
  ```

  ### 16.6 智能问答

  ```http
  POST /api/v1/chat
  ```

  ### 16.7 合同审查

  ```http
  POST /api/v1/contracts/review
  ```

  ### 16.8 经营分析

  ```http
  POST /api/v1/analytics/query
  ```

  ### 16.9 报告生成

  ```http
  POST /api/v1/reports/generate
  ```

  ### 16.10 Human Review 列表

  ```http
  GET /api/v1/reviews
  ```

  ### 16.11 Human Review 审核

  ```http
  POST /api/v1/reviews/{review_id}/decision
  ```

  ### 16.12 Trace 查询

  ```http
  GET /api/v1/traces/{run_id}
  ```

  ### 16.13 评估任务创建

  ```http
  POST /api/v1/evaluations
  ```

  ---

  ## 17. 数据模型草案

  ### 17.1 users

  - id
  - username
  - email
  - role
  - department
  - status
  - created_at
  - updated_at

  ### 17.2 departments

  - id
  - name
  - parent_id
  - created_at
  - updated_at

  ### 17.3 roles

  - id
  - name
  - description
  - permissions
  - created_at
  - updated_at

  ### 17.4 knowledge_bases

  - id
  - name
  - business_domain
  - description
  - access_roles
  - status
  - created_at
  - updated_at

  ### 17.5 documents

  - id
  - title
  - filename
  - file_type
  - file_size
  - storage_path
  - business_domain
  - knowledge_base_id
  - department
  - version
  - effective_date
  - security_level
  - access_scope
  - status
  - uploaded_by
  - created_at
  - updated_at

  ### 17.6 document_chunks

  - id
  - document_id
  - knowledge_base_id
  - business_domain
  - chunk_index
  - content
  - page
  - section
  - metadata
  - created_at

  ### 17.7 agent_runs

  - id
  - user_id
  - user_role
  - query
  - route
  - business_domain
  - selected_knowledge_bases
  - risk_level
  - need_human_review
  - status
  - final_answer
  - latency_ms
  - error_message
  - created_at

  ### 17.8 tool_calls

  - id
  - run_id
  - tool_name
  - input_json
  - output_json
  - risk_level
  - status
  - latency_ms
  - error_message
  - created_at

  ### 17.9 retrieval_logs

  - id
  - run_id
  - query
  - knowledge_base_id
  - document_id
  - chunk_id
  - score
  - rank
  - content_preview
  - created_at

  ### 17.10 sql_audits

  - id
  - run_id
  - user_id
  - generated_sql
  - checked_sql
  - is_safe
  - blocked_reason
  - execution_status
  - row_count
  - latency_ms
  - created_at

  ### 17.11 human_reviews

  - id
  - run_id
  - risk_level
  - review_status
  - reviewer_id
  - review_comment
  - created_at
  - reviewed_at

  ### 17.12 evaluation_tasks

  - id
  - name
  - evaluation_type
  - dataset_id
  - status
  - metrics
  - result_json
  - created_at
  - completed_at

  ---

  ## 18. 验收标准

  ### 18.1 业务验收标准

  1. 支持集团制度、安全生产、设备运维、新能源运维、合同合规、经营分析、项目资料等核心场景。
  2. 用户可以通过自然语言完成知识查询、数据分析、合同审查和报告生成。
  3. 安全生产类问题必须返回引用来源和风险提示。
  4. 合同审查必须输出风险点、风险等级和修改建议。
  5. 经营分析必须展示 SQL、安全校验结果和分析结论。
  6. 高风险任务必须进入人工复核流程。
  7. 用户只能访问自己有权限的知识库和文档。

  ### 18.2 工程验收标准

  1. 项目有清晰的工程目录结构。
  2. API 层、业务层、Agent 层、RAG 层、工具层、数据层职责清晰。
  3. 所有核心配置通过环境变量管理。
  4. 系统支持 Docker 化部署。
  5. 核心模块有基础测试。
  6. 关键流程有 Trace。
  7. 工具调用有审计。
  8. SQL 查询有安全校验。
  9. 检索过程有日志。
  10. 评估体系可以运行并生成报告。

  ### 18.3 安全验收标准

  1. 不允许无权限文档被检索。
  2. 不允许无权限工具被调用。
  3. 不允许危险 SQL 被执行。
  4. 高风险任务不能绕过人工复核。
  5. 敏感信息需要脱敏或权限控制。
  6. 所有审计日志可查询。

  ### 18.4 展示验收标准

  项目需要具备：

  1. 完整 PRD。
  2. 完整架构设计文档。
  3. Agent 工作流文档。
  4. RAG 设计文档。
  5. 安全设计文档。
  6. 评估设计文档。
  7. README 启动说明。
  8. 架构图。
  9. 业务流程图。
  10. 面试讲解稿。

  ---

  ## 19. 项目边界

  ### 19.1 系统可以辅助，但不替代责任人

  系统输出不能替代安全负责人、法务人员、经营管理人员、项目负责人做最终决策。

  ### 19.2 高风险任务必须人工确认

  涉及安全生产、合同重大风险、经营敏感数据和外部系统操作的任务，必须进入人工复核或人工确认。

  ### 19.3 知识库无依据时必须明确说明

  当知识库中找不到明确依据时，系统必须说明无法基于现有资料回答，不能编造答案。

  ### 19.4 技术选型暂不在本文档确定

  具体技术选型将在后续 `TECH_SELECTION.md` 中单独讨论和确定。

  本文档只描述产品目标、业务范围、功能能力、权限安全、审计评估和验收标准。

  ---

  ## 20. 后续文档清单

  后续需要继续产出以下文档：

  1. `docs/ARCHITECTURE.md`：系统架构设计文档
  2. `docs/AGENT_WORKFLOW.md`：Agent 工作流设计文档
  3. `docs/RAG_DESIGN.md`：RAG 检索与索引设计文档
  4. `docs/SECURITY_DESIGN.md`：权限、安全与审计设计文档
  5. `docs/EVALUATION_DESIGN.md`：评估体系设计文档
  6. `docs/TECH_SELECTION.md`：技术选型讨论文档
  7. `AGENTS.md`：Codex 项目级编码规则
  8. `README.md`：项目说明与启动文档

  ---

  ## 21. 当前版本说明

  当前文档为 v3 版本，核心变化包括：

  1. 删除 MVP 与高级阶段的分层描述。
  2. 改为生产级完整建设范围。
  3. 删除具体技术选型结论。
  4. 强化新疆能源集团业务场景。
  5. 增加完整 Agent、RAG、SQL、合同审查、Human Review、MCP、Trace、Evaluation、前端和部署要求。
  6. 明确后续技术选型需要单独讨论。

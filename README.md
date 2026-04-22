# Enterprise Knowledge Agentic RAG Platform

## 项目名称

新疆能源集团知识与生产经营智能 Agent 平台

## 项目定位

本项目是一个面向新疆能源集团业务场景的生产级 Agentic RAG 平台，
覆盖制度问答、安全生产、设备运维、合同审查、经营分析、项目资料问答、
报告生成、人工复核、Trace 审计和 Evaluation 评估等方向。

## 当前文档

- `AGENTS.md`：本项目编码约束与目录边界说明
- `docs/产品需求文档.md`：当前产品需求文档
- `docs/ARCHITECTURE.md`：系统架构设计文档
- `docs/TECH_SELECTION.md`：技术选型文档

## 当前阶段

当前处于项目工程骨架初始化阶段，目标是先建立清晰、稳定、可扩展的目录结构，
为后续 FastAPI、配置系统、数据库、RAG、Agent、工具注册、审计与评估能力逐步落地预留边界。

## 当前文档结构

```text
apps/    应用入口层，包含 API、Worker 和 Web
core/    核心业务层，包含配置、安全、Agent、RAG、工具等模块
tests/   测试目录，按单元测试、集成测试、端到端测试分层
scripts/ 脚本目录
docker/  容器与部署相关目录
docs/    项目产品、架构和技术选型文档
```

## 当前实现范围

当前仓库只完成了项目基础目录结构和必要占位文件：

- 创建了 FastAPI 最小应用入口
- 创建了 `GET /health` 健康检查接口
- 创建了基础配置类和工具/Agent 状态占位结构
- 创建了核心目录和测试目录

## 暂未实现的内容

当前 **暂未实现任何业务逻辑**，包括但不限于：

- RAG 文档解析、切分、Embedding 和检索
- Agent 路由、工作流和业务 Agent
- PostgreSQL、Milvus、Redis、Celery 的真实接入
- 权限、审计、Human Review、Evaluation 的具体实现
- 前端页面和部署编排

后续开发将严格按文档与模块边界逐步推进。

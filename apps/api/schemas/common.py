"""API 通用 Schema 定义。

该文件统一定义：
- 成功响应结构；
- 错误响应结构；
- meta 元信息结构；
- 健康检查响应结构。

这样做的目的不是为了“多封装一层”，而是为了从第一批接口开始，
就把前后端联调、Trace 追踪和后续工作流状态透出格式固定下来。
"""

from typing import Any

from pydantic import BaseModel, Field


class ResponseMeta(BaseModel):
    """统一响应元信息。

    业务作用：
    - 承载会话、任务运行、审核、分页等辅助信息；
    - 避免把状态字段散落到顶层或 data 中；
    - 为后续前端页面展示任务状态、恢复入口、审核入口预留统一位置。
    """

    # 当前会话 ID。多轮对话和消息追溯都依赖该标识。
    conversation_id: str | None = Field(default=None, description="会话 ID")

    # 当前任务运行 ID。后续可用于 Trace、Review、恢复执行和日志串联。
    run_id: str | None = Field(default=None, description="任务运行 ID")

    # 人工审核任务 ID。当前轮未真正实现 Review，仅预留响应字段。
    review_id: str | None = Field(default=None, description="人工审核任务 ID")

    # 主状态，例如 running、succeeded、awaiting_user_clarification。
    status: str | None = Field(default=None, description="主状态")

    # 子状态，例如 awaiting_slot_fill、drafting_answer。
    sub_status: str | None = Field(default=None, description="子状态")

    # 是否需要人工复核。
    need_human_review: bool | None = Field(default=None, description="是否需要人工复核")

    # 是否需要用户补充槽位或澄清问题。
    need_clarification: bool | None = Field(default=None, description="是否需要澄清")

    # 是否为异步任务。当前最小骨架默认返回同步 mock 结果。
    is_async: bool | None = Field(default=None, description="是否异步执行")

    # 分页场景下的总记录数。
    total: int | None = Field(default=None, description="总记录数")

    # 当前页码。
    page: int | None = Field(default=None, description="当前页码")

    # 当前页大小。
    page_size: int | None = Field(default=None, description="当前页大小")


class SuccessResponse(BaseModel):
    """统一成功响应结构。"""

    # 是否成功。成功响应固定为 True。
    success: bool = Field(default=True, description="请求是否成功")

    # Trace 标识。后续用于串联 access log、task run、tool call 和错误日志。
    trace_id: str = Field(description="Trace 标识")

    # 请求标识。用于定位单次 HTTP 请求。
    request_id: str = Field(description="请求标识")

    # 业务数据载荷。
    data: dict[str, Any] = Field(default_factory=dict, description="业务数据")

    # 元信息。
    meta: ResponseMeta = Field(default_factory=ResponseMeta, description="响应元信息")


class ErrorResponse(BaseModel):
    """统一错误响应结构。"""

    # 是否成功。错误响应固定为 False。
    success: bool = Field(default=False, description="请求是否成功")

    # Trace 标识。用于日志追踪和排障。
    trace_id: str = Field(description="Trace 标识")

    # 请求标识。用于定位单次 HTTP 请求。
    request_id: str = Field(description="请求标识")

    # 稳定错误码。前后端应依赖该字段而不是 message 做程序逻辑判断。
    error_code: str = Field(description="错误码")

    # 面向调用方的错误说明。
    message: str = Field(description="错误信息")

    # 结构化错误详情。可用于携带校验失败字段、上下文补充等信息。
    detail: dict[str, Any] = Field(default_factory=dict, description="错误详情")


class HealthResponse(BaseModel):
    """健康检查响应模型。"""

    # 当前服务状态。当前阶段固定返回 ok，用于最小健康检查。
    status: str = Field(description="服务健康状态")

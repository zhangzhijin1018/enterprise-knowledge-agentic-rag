"""经营分析接口路由。

支持两种进度推送方式：
1. SSE 流式推送：GET /analytics/stream/{run_id}
2. 轮询：GET /analytics/status/{run_id}

推荐使用 SSE，支持实时推送、无需轮询。

SSE 实现基于 Redis Streams，支持：
- 多 worker 部署
- 断线重连
- 跨进程通信
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from apps.api.deps import get_analytics_service, get_current_user_context
from apps.api.schemas.analytics import (
    AnalyticsQueryRequest,
    AnalyticsChatRequest,
)
from apps.api.schemas.common import SuccessResponse
from core.common.response import build_success_response
from core.common.sse_progress import RedisSSEConsumer, get_redis_pool
from core.security.auth import UserContext
from core.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.post("/chat", response_model=SuccessResponse)
async def analytics_chat(
    request: Request,
    payload: AnalyticsChatRequest,
    analytics_service: AnalyticsService = Depends(get_analytics_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """经营分析聊天接口 - 前端聊天框专用。

    与 /analytics/query 的区别：
    1. 简化响应结构，更适合前端展示
    2. 支持 Mock LLM 生成自然语言摘要和洞察
    3. 返回格式更适合 ChatGPT 风格的聊天展示
    """

    result = await analytics_service.chat_query(
        query=payload.query,
        conversation_id=payload.conversation_id,
        output_mode=payload.output_mode,
        user_context=user_context,
    )
    return build_success_response(
        request=request,
        data=result["data"],
        meta=result["meta"],
    )


@router.post("/query", response_model=SuccessResponse)
async def submit_analytics_query(
    request: Request,
    payload: AnalyticsQueryRequest,
    analytics_service: AnalyticsService = Depends(get_analytics_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """提交最小经营分析请求。"""

    result = await analytics_service.submit_query(
        query=payload.query,
        conversation_id=payload.conversation_id,
        output_mode=payload.output_mode,
        need_sql_explain=payload.need_sql_explain,
        user_context=user_context,
    )
    return build_success_response(
        request=request,
        data=result["data"],
        meta=result["meta"],
    )


@router.get("/runs/{run_id}", response_model=SuccessResponse)
async def get_analytics_run_detail(
    request: Request,
    run_id: str,
    analytics_service: AnalyticsService = Depends(get_analytics_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """读取经营分析运行详情。"""

    result = await analytics_service.get_run_detail(
        run_id=run_id,
        user_context=user_context,
    )
    return build_success_response(
        request=request,
        data=result["data"],
        meta=result["meta"],
    )


@router.get("/status/{run_id}", response_model=SuccessResponse)
async def get_analytics_run_status(
    request: Request,
    run_id: str,
    analytics_service: AnalyticsService = Depends(get_analytics_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> dict:
    """轮询任务状态接口 - 用于前端进度展示。

    前端通过定期轮询此接口获取当前任务执行状态：
    - processing: 正在处理，显示当前步骤
    - succeeded: 完成，返回完整结果
    - failed: 失败，返回错误信息
    - awaiting_clarification: 等待用户澄清
    """

    result = await analytics_service.get_run_status(
        run_id=run_id,
        user_context=user_context,
    )
    return build_success_response(
        request=request,
        data=result["data"],
        meta=result["meta"],
    )


@router.get("/stream/{run_id}")
async def stream_analytics_progress(
    request: Request,
    run_id: str,
    analytics_service: AnalyticsService = Depends(get_analytics_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> StreamingResponse:
    """SSE 流式进度推送接口。

    基于 Redis Streams 实现，支持：
    - 多 worker 部署：Workflow 和 API 可以在不同进程
    - 断线重连：从上次读取位置继续
    - 跨进程通信：通过 Redis 中转

    前端使用方式：
    ```javascript
    const eventSource = new EventSource(`/api/v1/analytics/stream/${run_id}`);

    eventSource.addEventListener('connected', (e) => {
        console.log('已连接:', JSON.parse(e.data));
    });

    eventSource.addEventListener('progress', (e) => {
        const data = JSON.parse(e.data);
        updateProgress(data.progress, data.current_step);
        // 可选：更新步骤列表
        if (data.steps) {
            updateSteps(data.steps);
        }
    });

    eventSource.addEventListener('complete', (e) => {
        const data = JSON.parse(e.data);
        showResult(data.result);
        eventSource.close();
    });

    eventSource.addEventListener('error', (e) => {
        console.error('错误:', JSON.parse(e.data));
        eventSource.close();
    });
    ```

    性能优化：
    - XREAD BLOCK 阻塞等待，减少 CPU 占用
    - 一次最多读取 100 条消息
    - 心跳间隔 30 秒
    """

    async def event_generator():
        """SSE 事件流生成器。"""
        import json
        try:
            pool = await get_redis_pool()
            consumer = RedisSSEConsumer(
                run_id=run_id,
                redis_client=pool.redis,
                consumer_id=f"api_{id(request)}",
                heartbeat_interval=30,
            )

            async for message in consumer.consume():
                yield message

        except Exception as e:
            error_data = json.dumps({
                "event": "error",
                "data": {"run_id": run_id, "message": str(e)}
            })
            yield f"data: {error_data}\n\n".encode()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/download/{run_id}")
async def download_analytics_result(
    request: Request,
    run_id: str,
    analytics_service: AnalyticsService = Depends(get_analytics_service),
    user_context: UserContext = Depends(get_current_user_context),
) -> StreamingResponse:
    """下载大型分析结果

    当分析结果超过 50KB 时，结果会存储到 Redis，
    前端通过此接口下载完整的 JSON 结果。

    返回格式：
    - Content-Type: application/json
    - Content-Disposition: attachment; filename=analytics_{run_id}.json
    """

    result = await analytics_service.get_full_result(
        run_id=run_id,
        user_context=user_context,
    )

    result_json = json.dumps(result, ensure_ascii=False)

    return StreamingResponse(
        iter([result_json]),
        media_type="application/json",
        headers={
            "Content-Disposition": f"attachment; filename=analytics_{run_id}.json",
            "Content-Length": str(len(result_json.encode("utf-8"))),
        },
    )

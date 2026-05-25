"""
Chat API 路由（SSE 流式接口）

提供对话式查询的 SSE 流式接口，包括：
- POST /api/chat: 接收用户查询，返回 SSE 流式响应
- POST /api/chat/confirm: SQL 确认/拒绝接口
- POST /api/chat/cancel: 取消正在执行的查询

所有流式接口使用 Server-Sent Events (SSE) 格式返回数据，
每个事件格式为: "event: {type}\ndata: {json_data}\n\n"
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.models.schemas import QueryRequest, StreamEvent
from app.services.agent_orchestrator import agent_orchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


# ============================================================
# 请求模型定义
# ============================================================


class ConfirmRequest(BaseModel):
    """SQL 确认/拒绝请求模型

    Attributes:
        session_id: 会话标识
        confirmed: 是否确认执行 SQL
        feedback: 拒绝时的修改意见（可选）
    """
    session_id: str = Field(..., alias="sessionId", description="会话标识")
    confirmed: bool = Field(..., description="是否确认执行SQL")
    feedback: Optional[str] = Field(
        None, description="拒绝时的修改意见"
    )

    model_config = {"populate_by_name": True}


class CancelRequest(BaseModel):
    """取消查询请求模型

    Attributes:
        session_id: 会话标识
    """
    session_id: str = Field(..., alias="sessionId", description="会话标识")

    model_config = {"populate_by_name": True}


# ============================================================
# 辅助函数
# ============================================================


def _serialize_stream_event(event: StreamEvent) -> str:
    """将 StreamEvent 序列化为 SSE 格式字符串

    SSE 格式: "event: {type}\ndata: {json_data}\n\n"

    Args:
        event: 流事件对象

    Returns:
        SSE 格式的字符串
    """
    event_type = event.type.value if hasattr(event.type, "value") else str(event.type)
    data_json = json.dumps(event.data, ensure_ascii=False, default=str)
    return f"event: {event_type}\ndata: {data_json}\n\n"


# ============================================================
# 路由端点
# ============================================================


@router.post("")
async def chat(request: QueryRequest):
    """处理用户查询，返回 SSE 流式响应

    接收用户自然语言查询，通过 Agent Orchestrator 协调处理，
    逐步返回 thinking、sql_preview、executing、result 等事件。

    Args:
        request: 查询请求，包含 sessionId、message、conversationId

    Returns:
        StreamingResponse，media_type 为 text/event-stream
    """
    logger.info(
        "Chat request received, session_id=%s, message=%s",
        request.session_id, request.message[:100],
    )

    async def event_generator():
        """异步生成器，迭代 agent_orchestrator.process_query() 并序列化为 SSE"""
        try:
            async for event in agent_orchestrator.process_query(request):
                yield _serialize_stream_event(event)
        except Exception as e:
            logger.error(
                "Error in chat stream, session_id=%s, error=%s",
                request.session_id, str(e),
            )
            # 发送错误事件
            error_event = StreamEvent(
                type="error",
                data={"message": f"处理查询时发生错误：{str(e)}", "error_type": "internal_error"},
            )
            yield _serialize_stream_event(error_event)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/confirm")
async def confirm(request: ConfirmRequest):
    """处理 SQL 确认/拒绝请求

    用户确认时执行 SQL 并返回结果和图表推荐；
    用户拒绝时根据反馈重新生成 SQL。

    Args:
        request: 确认请求，包含 sessionId、confirmed、feedback

    Returns:
        StreamingResponse，media_type 为 text/event-stream
    """
    logger.info(
        "Confirm request received, session_id=%s, confirmed=%s, feedback=%s",
        request.session_id, request.confirmed, request.feedback,
    )

    async def event_generator():
        """异步生成器，迭代 handle_confirmation() 并序列化为 SSE"""
        try:
            async for event in agent_orchestrator.handle_confirmation(
                session_id=request.session_id,
                confirmed=request.confirmed,
                feedback=request.feedback,
            ):
                yield _serialize_stream_event(event)
        except Exception as e:
            logger.error(
                "Error in confirm stream, session_id=%s, error=%s",
                request.session_id, str(e),
            )
            error_event = StreamEvent(
                type="error",
                data={"message": f"处理确认时发生错误：{str(e)}", "error_type": "internal_error"},
            )
            yield _serialize_stream_event(error_event)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/cancel")
async def cancel(request: CancelRequest):
    """取消正在执行的查询

    调用 agent_orchestrator.cancel_query() 取消查询，
    返回 JSON 格式的取消结果。

    Args:
        request: 取消请求，包含 sessionId

    Returns:
        JSON 响应，包含取消结果
    """
    logger.info(
        "Cancel request received, session_id=%s", request.session_id
    )

    try:
        result = await agent_orchestrator.cancel_query(request.session_id)
        return {"type": result.type.value, "data": result.data}
    except Exception as e:
        logger.error(
            "Error cancelling query, session_id=%s, error=%s",
            request.session_id, str(e),
        )
        return {
            "type": "error",
            "data": {"message": f"取消查询时发生错误：{str(e)}", "error_type": "internal_error"},
        }

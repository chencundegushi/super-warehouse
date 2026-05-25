"""
对话管理 API 路由

提供会话的创建、查询、删除、消息获取和搜索接口。
通过 ConversationManager 服务管理对话生命周期和持久化。

路由前缀: /api/conversations
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.models.schemas import (
    ConvListParams,
    ConvSearchParams,
    ConversationSummary,
    MessageInput,
    PaginatedResult,
)
from app.services.conversation_manager import conversation_manager

logger = logging.getLogger(__name__)

# 创建路由器，设置前缀和标签
router = APIRouter(prefix="/api/conversations", tags=["对话管理"])


# ============================================================
# 请求/响应模型
# ============================================================


class CreateConversationRequest(BaseModel):
    """创建会话请求"""
    title: Optional[str] = Field(None, description="会话标题，为空时使用默认标题")


class ConversationResponse(BaseModel):
    """会话响应"""
    id: str = Field(..., description="会话ID")
    title: str = Field(..., description="会话标题")
    created_at: str = Field(..., alias="createdAt", description="创建时间")
    updated_at: str = Field(..., alias="updatedAt", description="最后活跃时间")
    context_summary: Optional[str] = Field(
        None, alias="contextSummary", description="上下文摘要"
    )
    message_count: int = Field(0, alias="messageCount", description="消息总数")

    model_config = {"populate_by_name": True}


class MessageResponse(BaseModel):
    """消息响应"""
    id: str = Field(..., description="消息ID")
    conversation_id: str = Field(..., alias="conversationId", description="所属会话ID")
    role: str = Field(..., description="消息角色(user/agent)")
    content: str = Field(..., description="消息文本内容")
    sql: Optional[str] = Field(None, description="关联的SQL语句")
    query_result: Optional[str] = Field(
        None, alias="queryResult", description="查询结果（JSON字符串）"
    )
    created_at: str = Field(..., alias="createdAt", description="创建时间")

    model_config = {"populate_by_name": True}


# ============================================================
# 搜索接口（放在 {id} 路由之前，避免路径冲突）
# ============================================================


@router.get("/search", summary="搜索会话")
async def search_conversations(
    keyword: Optional[str] = Query(None, description="搜索关键词"),
    start_time: Optional[datetime] = Query(None, alias="startTime", description="开始时间"),
    end_time: Optional[datetime] = Query(None, alias="endTime", description="结束时间"),
    limit: int = Query(50, ge=1, le=50, description="返回条数上限，最大50"),
) -> list[ConversationSummary]:
    """搜索会话

    支持按关键词和时间范围搜索，关键词搜索范围覆盖会话标题和消息文本。
    结果按时间降序排列，单次返回不超过50条。

    Args:
        keyword: 搜索关键词
        start_time: 开始时间
        end_time: 结束时间
        limit: 返回条数上限

    Returns:
        匹配的会话摘要列表
    """
    logger.info(
        "Search conversations request, keyword=%s, start_time=%s, end_time=%s, limit=%d",
        keyword, start_time, end_time, limit,
    )

    params = ConvSearchParams(
        keyword=keyword,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
    )
    results = await conversation_manager.search_conversations(params)

    logger.info("Search conversations completed, found=%d", len(results))
    return results


# ============================================================
# 会话 CRUD 接口
# ============================================================


@router.post("", summary="创建会话", status_code=201)
async def create_conversation(
    request: CreateConversationRequest,
) -> ConversationResponse:
    """创建新会话

    Args:
        request: 创建会话请求，包含可选的标题

    Returns:
        创建的会话信息
    """
    logger.info("Create conversation request, title=%s", request.title)

    conversation = await conversation_manager.create_conversation(title=request.title)

    logger.info("Conversation created, id=%s", conversation.id)
    return ConversationResponse(
        id=conversation.id,
        title=conversation.title,
        createdAt=conversation.created_at,
        updatedAt=conversation.updated_at,
        contextSummary=conversation.context_summary,
        messageCount=conversation.message_count,
    )


@router.get("", summary="获取会话列表")
async def list_conversations(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=20, alias="pageSize", description="每页条数，最大20"),
) -> PaginatedResult:
    """分页查询会话列表

    按最近活跃时间降序展示所有历史会话，每页不超过20条。

    Args:
        page: 页码
        page_size: 每页条数

    Returns:
        分页结果，包含会话摘要列表和总数
    """
    logger.info("List conversations request, page=%d, page_size=%d", page, page_size)

    params = ConvListParams(page=page, page_size=page_size)
    result = await conversation_manager.list_conversations(params)

    logger.info("List conversations completed, total=%d", result.total)
    return result


@router.get("/{conversation_id}", summary="获取会话详情")
async def get_conversation(conversation_id: str) -> ConversationResponse:
    """获取指定会话的详细信息

    Args:
        conversation_id: 会话ID

    Returns:
        会话详情

    Raises:
        HTTPException: 会话不存在时返回404
    """
    logger.info("Get conversation request, id=%s", conversation_id)

    conversation = await conversation_manager.get_conversation(conversation_id)
    if conversation is None:
        logger.warning("Conversation not found, id=%s", conversation_id)
        raise HTTPException(status_code=404, detail="会话不存在")

    return ConversationResponse(
        id=conversation.id,
        title=conversation.title,
        createdAt=conversation.created_at,
        updatedAt=conversation.updated_at,
        contextSummary=conversation.context_summary,
        messageCount=conversation.message_count,
    )


@router.get("/{conversation_id}/messages", summary="获取消息列表")
async def get_messages(conversation_id: str) -> list[MessageResponse]:
    """获取指定会话的所有消息，按创建时间升序排列

    Args:
        conversation_id: 会话ID

    Returns:
        消息列表

    Raises:
        HTTPException: 会话不存在时返回404
    """
    logger.info("Get messages request, conversation_id=%s", conversation_id)

    # 1.验证会话存在
    conversation = await conversation_manager.get_conversation(conversation_id)
    if conversation is None:
        logger.warning("Conversation not found, id=%s", conversation_id)
        raise HTTPException(status_code=404, detail="会话不存在")

    # 2.获取消息列表
    messages = await conversation_manager.get_messages(conversation_id)

    logger.info("Get messages completed, conversation_id=%s, count=%d", conversation_id, len(messages))
    return [
        MessageResponse(
            id=msg.id,
            conversationId=msg.conversation_id,
            role=msg.role,
            content=msg.content,
            sql=msg.sql,
            queryResult=msg.query_result,
            createdAt=msg.created_at,
        )
        for msg in messages
    ]


@router.delete("/{conversation_id}", summary="删除会话", status_code=204)
async def delete_conversation(conversation_id: str) -> None:
    """删除指定会话及其所有消息

    永久删除该会话的所有存储数据并从历史列表中移除。

    Args:
        conversation_id: 会话ID

    Raises:
        HTTPException: 会话不存在时返回404
    """
    logger.info("Delete conversation request, id=%s", conversation_id)

    # 1.验证会话存在
    conversation = await conversation_manager.get_conversation(conversation_id)
    if conversation is None:
        logger.warning("Conversation not found, id=%s", conversation_id)
        raise HTTPException(status_code=404, detail="会话不存在")

    # 2.执行删除
    await conversation_manager.delete_conversation(conversation_id)

    logger.info("Conversation deleted, id=%s", conversation_id)

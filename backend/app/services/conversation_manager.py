"""
对话管理器服务

管理多轮对话上下文、历史持久化和搜索。
提供会话 CRUD、消息管理、上下文管理和摘要压缩功能。

核心功能：
- 会话创建/获取/删除
- 消息添加/查询
- 会话列表分页查询（按 updated_at 降序，每页最多20条）
- 关键词和时间范围搜索（结果按时间降序，最多50条）
- 上下文管理和摘要压缩（50轮上限）
- 摘要保留表名、指标名称、筛选条件和关键数值
"""

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.database import Conversation, Message, async_session_factory
from app.models.schemas import (
    ConvListParams,
    ConvSearchParams,
    ConversationSummary,
    MessageInput,
    PaginatedResult,
)

logger = logging.getLogger(__name__)


def _iso_now() -> str:
    """生成当前时间的 ISO 8601 格式字符串（UTC）

    Returns:
        ISO 8601 格式的时间字符串
    """
    return datetime.now(timezone.utc).isoformat()


def _generate_id() -> str:
    """生成 UUID 字符串

    Returns:
        UUID4 字符串
    """
    return str(uuid.uuid4())


class ConversationManager:
    """对话管理器

    负责会话生命周期管理、消息持久化、分页查询、搜索和上下文摘要压缩。
    单个会话最多保留50轮对话记录，超出时对最早的对话轮次执行摘要压缩。
    """

    def __init__(self) -> None:
        """初始化对话管理器"""
        self._max_turns: int = settings.conversation_max_turns
        self._page_size: int = settings.conversation_page_size
        self._search_limit: int = settings.conversation_search_limit
        logger.info(
            "ConversationManager initialized, max_turns=%d, page_size=%d, search_limit=%d",
            self._max_turns, self._page_size, self._search_limit,
        )

    # ============================================================
    # 会话 CRUD
    # ============================================================

    async def create_conversation(self, title: Optional[str] = None) -> Conversation:
        """创建新会话

        Args:
            title: 会话标题，为空时使用默认标题

        Returns:
            创建的会话对象
        """
        conversation_id = _generate_id()
        now = _iso_now()
        effective_title = title or "新对话"
        logger.info(
            "Creating conversation, id=%s, title=%s", conversation_id, effective_title
        )

        async with async_session_factory() as session:
            conversation = Conversation(
                id=conversation_id,
                title=effective_title,
                created_at=now,
                updated_at=now,
                context_summary=None,
                message_count=0,
            )
            session.add(conversation)
            await session.commit()
            await session.refresh(conversation)

        logger.info("Conversation created successfully, id=%s", conversation_id)
        return conversation

    async def get_conversation(self, conversation_id: str) -> Optional[Conversation]:
        """获取会话详情

        Args:
            conversation_id: 会话ID

        Returns:
            会话对象，不存在时返回 None
        """
        logger.info("Getting conversation, id=%s", conversation_id)
        async with async_session_factory() as session:
            result = await session.execute(
                select(Conversation).where(Conversation.id == conversation_id)
            )
            conversation = result.scalar_one_or_none()

        if conversation is None:
            logger.warning("Conversation not found, id=%s", conversation_id)
        return conversation

    async def delete_conversation(self, conversation_id: str) -> None:
        """删除会话及其所有消息

        Args:
            conversation_id: 会话ID
        """
        logger.info("Deleting conversation, id=%s", conversation_id)
        async with async_session_factory() as session:
            # 1.删除关联消息
            await session.execute(
                delete(Message).where(Message.conversation_id == conversation_id)
            )
            # 2.删除会话
            await session.execute(
                delete(Conversation).where(Conversation.id == conversation_id)
            )
            await session.commit()
        logger.info("Conversation deleted successfully, id=%s", conversation_id)

    # ============================================================
    # 会话列表与搜索
    # ============================================================

    async def list_conversations(self, params: ConvListParams) -> PaginatedResult:
        """分页查询会话列表，按 updated_at 降序排列

        Args:
            params: 分页查询参数

        Returns:
            分页结果，包含会话摘要列表和总数
        """
        # 1.限制每页最大条数
        page_size = min(params.page_size, self._page_size)
        offset = (params.page - 1) * page_size
        logger.info(
            "Listing conversations, page=%d, page_size=%d",
            params.page, page_size,
        )

        async with async_session_factory() as session:
            # 2.查询总数
            count_stmt = select(func.count(Conversation.id))
            total_result = await session.execute(count_stmt)
            total = total_result.scalar() or 0

            # 3.分页查询，按 updated_at 降序
            query_stmt = (
                select(Conversation)
                .order_by(Conversation.updated_at.desc())
                .offset(offset)
                .limit(page_size)
            )
            result = await session.execute(query_stmt)
            conversations = result.scalars().all()

        # 4.转换为摘要格式
        items = [
            ConversationSummary(
                id=conv.id,
                title=conv.title,
                updatedAt=conv.updated_at,
                messageCount=conv.message_count,
            )
            for conv in conversations
        ]

        logger.info("Listed conversations, total=%d, returned=%d", total, len(items))
        return PaginatedResult(
            items=items, total=total, page=params.page, pageSize=page_size
        )

    async def search_conversations(
        self, params: ConvSearchParams
    ) -> list[ConversationSummary]:
        """搜索会话，支持关键词和时间范围过滤

        关键词搜索范围覆盖会话标题和消息文本。
        结果按时间降序排列，最多返回50条。

        Args:
            params: 搜索参数

        Returns:
            匹配的会话摘要列表
        """
        limit = min(params.limit, self._search_limit)
        logger.info(
            "Searching conversations, keyword=%s, start_time=%s, end_time=%s, limit=%d",
            params.keyword, params.start_time, params.end_time, limit,
        )

        async with async_session_factory() as session:
            # 1.构建基础查询
            query_stmt = select(Conversation)

            # 2.时间范围过滤
            if params.start_time:
                start_iso = params.start_time.isoformat()
                query_stmt = query_stmt.where(
                    Conversation.updated_at >= start_iso
                )
            if params.end_time:
                end_iso = params.end_time.isoformat()
                query_stmt = query_stmt.where(
                    Conversation.updated_at <= end_iso
                )

            # 3.关键词过滤（标题或消息内容匹配）
            if params.keyword:
                keyword_pattern = f"%{params.keyword}%"
                # 子查询：查找消息内容包含关键词的会话ID
                msg_subquery = (
                    select(Message.conversation_id)
                    .where(Message.content.like(keyword_pattern))
                    .distinct()
                    .scalar_subquery()
                )
                query_stmt = query_stmt.where(
                    (Conversation.title.like(keyword_pattern))
                    | (Conversation.id.in_(msg_subquery))
                )

            # 4.按时间降序排列，限制返回条数
            query_stmt = (
                query_stmt.order_by(Conversation.updated_at.desc()).limit(limit)
            )

            result = await session.execute(query_stmt)
            conversations = result.scalars().all()

        # 5.转换为摘要格式
        items = [
            ConversationSummary(
                id=conv.id,
                title=conv.title,
                updatedAt=conv.updated_at,
                messageCount=conv.message_count,
            )
            for conv in conversations
        ]

        logger.info("Search completed, found=%d conversations", len(items))
        return items

    # ============================================================
    # 消息管理
    # ============================================================

    async def add_message(
        self, conversation_id: str, message: MessageInput
    ) -> Message:
        """添加消息到会话

        添加消息后更新会话的 message_count 和 updated_at。
        如果消息轮次超过上限（50轮），自动对最早消息执行摘要压缩。

        Args:
            conversation_id: 会话ID
            message: 消息输入

        Returns:
            创建的消息对象
        """
        message_id = _generate_id()
        now = _iso_now()
        logger.info(
            "Adding message, conversation_id=%s, role=%s, message_id=%s",
            conversation_id, message.role, message_id,
        )

        # 1.序列化查询结果
        query_result_str = None
        if message.query_result is not None:
            query_result_str = json.dumps(
                message.query_result, ensure_ascii=False
            )

        async with async_session_factory() as session:
            # 2.创建消息记录
            msg = Message(
                id=message_id,
                conversation_id=conversation_id,
                role=message.role,
                content=message.content,
                sql=message.sql,
                query_result=query_result_str,
                created_at=now,
            )
            session.add(msg)

            # 3.更新会话的消息计数和活跃时间
            result = await session.execute(
                select(Conversation).where(Conversation.id == conversation_id)
            )
            conversation = result.scalar_one_or_none()
            if conversation:
                conversation.message_count = (conversation.message_count or 0) + 1
                conversation.updated_at = now

            await session.commit()
            await session.refresh(msg)

        # 4.检查是否需要摘要压缩
        await self._check_and_compress(conversation_id)

        logger.info("Message added successfully, message_id=%s", message_id)
        return msg

    async def get_messages(self, conversation_id: str) -> list[Message]:
        """获取会话的所有消息，按创建时间升序排列

        Args:
            conversation_id: 会话ID

        Returns:
            消息列表
        """
        logger.info("Getting messages, conversation_id=%s", conversation_id)
        async with async_session_factory() as session:
            result = await session.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.asc())
            )
            messages = result.scalars().all()

        logger.info(
            "Got messages, conversation_id=%s, count=%d",
            conversation_id, len(messages),
        )
        return messages

    # ============================================================
    # 上下文管理
    # ============================================================

    async def get_context(self, conversation_id: str) -> dict:
        """获取会话上下文，包含消息列表、摘要和引用信息

        Args:
            conversation_id: 会话ID

        Returns:
            上下文字典，包含 messages、summary、referencedTables、referencedMetrics
        """
        logger.info("Getting context, conversation_id=%s", conversation_id)

        # 1.获取会话信息
        conversation = await self.get_conversation(conversation_id)
        if conversation is None:
            return {
                "messages": [],
                "summary": None,
                "referencedTables": [],
                "referencedMetrics": [],
            }

        # 2.获取所有消息
        messages = await self.get_messages(conversation_id)

        # 3.从消息中提取引用的表名和指标
        referenced_tables = set()
        referenced_metrics = set()
        for msg in messages:
            if msg.sql:
                tables = self._extract_tables_from_sql(msg.sql)
                referenced_tables.update(tables)
            if msg.content:
                metrics = self._extract_metrics_from_content(msg.content)
                referenced_metrics.update(metrics)

        # 4.解析已有摘要
        summary = None
        if conversation.context_summary:
            try:
                summary = json.loads(conversation.context_summary)
            except (json.JSONDecodeError, TypeError):
                summary = None

        return {
            "messages": messages,
            "summary": summary,
            "referencedTables": list(referenced_tables),
            "referencedMetrics": list(referenced_metrics),
        }

    async def summarize_context(self, conversation_id: str) -> str:
        """对会话上下文执行摘要压缩

        提取并保留：表名、指标名称、筛选条件（WHERE子句）和关键数值。
        摘要结果存储到会话的 context_summary 字段。

        Args:
            conversation_id: 会话ID

        Returns:
            摘要文本（JSON格式字符串）
        """
        logger.info("Summarizing context, conversation_id=%s", conversation_id)

        messages = await self.get_messages(conversation_id)
        if not messages:
            return ""

        # 1.从所有消息中提取关键信息
        tables = set()
        metrics = set()
        filters = []
        key_values = {}

        for msg in messages:
            # 提取表名
            if msg.sql:
                extracted_tables = self._extract_tables_from_sql(msg.sql)
                tables.update(extracted_tables)
                # 提取筛选条件
                extracted_filters = self._extract_filters_from_sql(msg.sql)
                filters.extend(extracted_filters)

            # 提取指标名称
            if msg.content:
                extracted_metrics = self._extract_metrics_from_content(msg.content)
                metrics.update(extracted_metrics)

            # 提取关键数值
            if msg.query_result:
                extracted_values = self._extract_key_values(msg.query_result)
                key_values.update(extracted_values)

        # 2.构建摘要结构
        summary = {
            "tables": list(tables),
            "metrics": list(metrics),
            "filters": filters,
            "keyValues": key_values,
            "turnCount": len(messages),
        }

        summary_str = json.dumps(summary, ensure_ascii=False)

        # 3.保存摘要到会话
        async with async_session_factory() as session:
            result = await session.execute(
                select(Conversation).where(Conversation.id == conversation_id)
            )
            conversation = result.scalar_one_or_none()
            if conversation:
                conversation.context_summary = summary_str
                await session.commit()

        logger.info(
            "Context summarized, conversation_id=%s, tables=%d, metrics=%d, filters=%d",
            conversation_id, len(tables), len(metrics), len(filters),
        )
        return summary_str

    # ============================================================
    # 轮次上限控制与摘要压缩
    # ============================================================

    async def _check_and_compress(self, conversation_id: str) -> None:
        """检查消息轮次是否超出上限，超出时自动摘要压缩最早消息

        一轮对话由一对 user+agent 消息组成。
        当消息总数超过 max_turns * 2 时，对最早的消息执行摘要压缩。

        Args:
            conversation_id: 会话ID
        """
        messages = await self.get_messages(conversation_id)
        # 1.计算当前轮次（每轮包含 user 和 agent 各一条消息）
        max_messages = self._max_turns * 2

        if len(messages) <= max_messages:
            return

        logger.info(
            "Message count exceeds limit, compressing, conversation_id=%s, count=%d, max=%d",
            conversation_id, len(messages), max_messages,
        )

        # 2.确定需要压缩的消息（超出部分的最早消息）
        messages_to_compress = messages[: len(messages) - max_messages]

        # 3.从待压缩消息中提取关键信息
        tables = set()
        metrics = set()
        filters = []
        key_values = {}

        for msg in messages_to_compress:
            if msg.sql:
                tables.update(self._extract_tables_from_sql(msg.sql))
                filters.extend(self._extract_filters_from_sql(msg.sql))
            if msg.content:
                metrics.update(self._extract_metrics_from_content(msg.content))
            if msg.query_result:
                key_values.update(self._extract_key_values(msg.query_result))

        # 4.构建压缩摘要
        compressed_summary = {
            "tables": list(tables),
            "metrics": list(metrics),
            "filters": filters,
            "keyValues": key_values,
            "turnCount": len(messages_to_compress),
        }

        async with async_session_factory() as session:
            # 5.获取当前会话
            result = await session.execute(
                select(Conversation).where(Conversation.id == conversation_id)
            )
            conversation = result.scalar_one_or_none()
            if not conversation:
                return

            # 6.合并已有摘要
            existing_summary = {}
            if conversation.context_summary:
                try:
                    existing_summary = json.loads(conversation.context_summary)
                except (json.JSONDecodeError, TypeError):
                    existing_summary = {}

            merged_summary = self._merge_summaries(existing_summary, compressed_summary)
            conversation.context_summary = json.dumps(merged_summary, ensure_ascii=False)

            # 7.删除已压缩的消息
            compressed_ids = [msg.id for msg in messages_to_compress]
            await session.execute(
                delete(Message).where(Message.id.in_(compressed_ids))
            )

            # 8.更新消息计数
            remaining_count = len(messages) - len(messages_to_compress)
            conversation.message_count = remaining_count

            await session.commit()

        logger.info(
            "Compression completed, conversation_id=%s, compressed=%d, remaining=%d",
            conversation_id, len(messages_to_compress), remaining_count,
        )

    # ============================================================
    # 辅助方法：信息提取
    # ============================================================

    @staticmethod
    def _extract_tables_from_sql(sql: str) -> set[str]:
        """从 SQL 语句中提取表名

        识别 FROM 和 JOIN 子句中的表名。

        Args:
            sql: SQL 语句

        Returns:
            表名集合
        """
        tables = set()
        # 匹配 FROM table_name 和 JOIN table_name
        patterns = [
            r'\bFROM\s+`?(\w+)`?',
            r'\bJOIN\s+`?(\w+)`?',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, sql, re.IGNORECASE)
            tables.update(matches)
        return tables

    @staticmethod
    def _extract_filters_from_sql(sql: str) -> list[str]:
        """从 SQL 语句中提取 WHERE 筛选条件

        Args:
            sql: SQL 语句

        Returns:
            筛选条件列表
        """
        filters = []
        # 匹配 WHERE 子句内容（到 GROUP BY/ORDER BY/LIMIT/; 或末尾）
        where_pattern = r'\bWHERE\s+(.*?)(?:\bGROUP\s+BY\b|\bORDER\s+BY\b|\bLIMIT\b|\bHAVING\b|;|$)'
        matches = re.findall(where_pattern, sql, re.IGNORECASE | re.DOTALL)
        for match in matches:
            condition = match.strip()
            if condition:
                filters.append(condition)
        return filters

    @staticmethod
    def _extract_metrics_from_content(content: str) -> set[str]:
        """从消息内容中提取指标名称

        识别常见的指标关键词模式（如"XX率"、"XX量"、"XX额"等）。

        Args:
            content: 消息文本内容

        Returns:
            指标名称集合
        """
        metrics = set()
        # 匹配中文指标名称模式
        metric_patterns = [
            r'([\u4e00-\u9fa5]{2,8}(?:率|量|额|数|值|比|均值|总计|合计))',
        ]
        for pattern in metric_patterns:
            matches = re.findall(pattern, content)
            metrics.update(matches)
        return metrics

    @staticmethod
    def _extract_key_values(query_result_str: str) -> dict:
        """从查询结果中提取关键数值

        解析 JSON 格式的查询结果，提取数值型字段。

        Args:
            query_result_str: 查询结果 JSON 字符串

        Returns:
            关键数值字典
        """
        key_values = {}
        try:
            result_data = json.loads(query_result_str)
            # 处理结果中的数值数据
            if isinstance(result_data, dict):
                rows = result_data.get("rows", [])
                columns = result_data.get("columns", [])
                if rows and columns:
                    # 取第一行数据中的数值字段作为关键数值
                    first_row = rows[0] if rows else []
                    for i, col in enumerate(columns):
                        if i < len(first_row):
                            val = first_row[i]
                            col_name = col.get("name", f"col_{i}") if isinstance(col, dict) else str(col)
                            if isinstance(val, (int, float)):
                                key_values[col_name] = val
        except (json.JSONDecodeError, TypeError, KeyError):
            pass
        return key_values

    @staticmethod
    def _merge_summaries(existing: dict, new: dict) -> dict:
        """合并两个摘要，去重并保留所有关键信息

        Args:
            existing: 已有摘要
            new: 新摘要

        Returns:
            合并后的摘要
        """
        merged_tables = list(
            set(existing.get("tables", []) + new.get("tables", []))
        )
        merged_metrics = list(
            set(existing.get("metrics", []) + new.get("metrics", []))
        )
        # 筛选条件保留所有（可能有重复但保留完整性）
        merged_filters = existing.get("filters", []) + new.get("filters", [])
        # 关键数值合并（新值覆盖旧值）
        merged_key_values = {**existing.get("keyValues", {}), **new.get("keyValues", {})}
        # 轮次累加
        merged_turn_count = (
            existing.get("turnCount", 0) + new.get("turnCount", 0)
        )

        return {
            "tables": merged_tables,
            "metrics": merged_metrics,
            "filters": merged_filters,
            "keyValues": merged_key_values,
            "turnCount": merged_turn_count,
        }


# 全局单例
conversation_manager = ConversationManager()

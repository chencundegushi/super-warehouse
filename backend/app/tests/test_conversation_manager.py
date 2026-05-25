"""
Conversation Manager 单元测试

验证会话 CRUD、消息管理、分页查询、搜索和上下文摘要压缩功能。
使用内存数据库隔离测试环境。
"""

import json
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.database import Base, Conversation, Message
from app.models.schemas import ConvListParams, ConvSearchParams, MessageInput
from app.services.conversation_manager import ConversationManager


@pytest.fixture
async def test_engine():
    """创建内存数据库引擎用于测试"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def test_session_factory(test_engine):
    """创建测试用会话工厂"""
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    return factory


@pytest.fixture
async def manager(test_session_factory):
    """创建使用测试数据库的 ConversationManager 实例"""
    mgr = ConversationManager()
    # 用测试会话工厂替换全局工厂
    with patch(
        "app.services.conversation_manager.async_session_factory",
        test_session_factory,
    ):
        yield mgr


class TestConversationCRUD:
    """验证会话 CRUD 操作"""

    async def test_create_conversation_with_title(self, manager, test_session_factory):
        """测试创建带标题的会话"""
        with patch(
            "app.services.conversation_manager.async_session_factory",
            test_session_factory,
        ):
            conv = await manager.create_conversation(title="测试会话")
            assert conv.title == "测试会话"
            assert conv.message_count == 0
            assert conv.id is not None
            assert conv.created_at is not None
            assert conv.updated_at is not None

    async def test_create_conversation_default_title(self, manager, test_session_factory):
        """测试创建会话时使用默认标题"""
        with patch(
            "app.services.conversation_manager.async_session_factory",
            test_session_factory,
        ):
            conv = await manager.create_conversation()
            assert conv.title == "新对话"

    async def test_get_conversation(self, manager, test_session_factory):
        """测试获取已存在的会话"""
        with patch(
            "app.services.conversation_manager.async_session_factory",
            test_session_factory,
        ):
            conv = await manager.create_conversation(title="获取测试")
            fetched = await manager.get_conversation(conv.id)
            assert fetched is not None
            assert fetched.id == conv.id
            assert fetched.title == "获取测试"

    async def test_get_conversation_not_found(self, manager, test_session_factory):
        """测试获取不存在的会话返回 None"""
        with patch(
            "app.services.conversation_manager.async_session_factory",
            test_session_factory,
        ):
            result = await manager.get_conversation("non-existent-id")
            assert result is None

    async def test_delete_conversation(self, manager, test_session_factory):
        """测试删除会话及其消息"""
        with patch(
            "app.services.conversation_manager.async_session_factory",
            test_session_factory,
        ):
            conv = await manager.create_conversation(title="待删除")
            msg_input = MessageInput(role="user", content="hello")
            await manager.add_message(conv.id, msg_input)

            await manager.delete_conversation(conv.id)

            # 验证会话已删除
            result = await manager.get_conversation(conv.id)
            assert result is None

            # 验证消息已删除
            messages = await manager.get_messages(conv.id)
            assert len(messages) == 0


class TestMessageManagement:
    """验证消息管理功能"""

    async def test_add_message(self, manager, test_session_factory):
        """测试添加消息"""
        with patch(
            "app.services.conversation_manager.async_session_factory",
            test_session_factory,
        ):
            conv = await manager.create_conversation(title="消息测试")
            msg_input = MessageInput(
                role="user", content="查询销售额"
            )
            msg = await manager.add_message(conv.id, msg_input)
            assert msg.role == "user"
            assert msg.content == "查询销售额"
            assert msg.conversation_id == conv.id

    async def test_add_message_with_sql_and_result(self, manager, test_session_factory):
        """测试添加带 SQL 和查询结果的消息"""
        with patch(
            "app.services.conversation_manager.async_session_factory",
            test_session_factory,
        ):
            conv = await manager.create_conversation(title="SQL测试")
            query_result = {"columns": [{"name": "total"}], "rows": [[1000]]}
            msg_input = MessageInput(
                role="agent",
                content="查询结果如下",
                sql="SELECT SUM(amount) as total FROM orders",
                queryResult=query_result,
            )
            msg = await manager.add_message(conv.id, msg_input)
            assert msg.sql == "SELECT SUM(amount) as total FROM orders"
            assert msg.query_result is not None

    async def test_add_message_updates_count(self, manager, test_session_factory):
        """测试添加消息后更新会话消息计数"""
        with patch(
            "app.services.conversation_manager.async_session_factory",
            test_session_factory,
        ):
            conv = await manager.create_conversation(title="计数测试")
            msg_input = MessageInput(role="user", content="msg1")
            await manager.add_message(conv.id, msg_input)

            updated_conv = await manager.get_conversation(conv.id)
            assert updated_conv.message_count == 1

    async def test_get_messages_ordered(self, manager, test_session_factory):
        """测试获取消息按时间升序排列"""
        with patch(
            "app.services.conversation_manager.async_session_factory",
            test_session_factory,
        ):
            conv = await manager.create_conversation(title="排序测试")
            await manager.add_message(conv.id, MessageInput(role="user", content="first"))
            await manager.add_message(conv.id, MessageInput(role="agent", content="second"))
            await manager.add_message(conv.id, MessageInput(role="user", content="third"))

            messages = await manager.get_messages(conv.id)
            assert len(messages) == 3
            assert messages[0].content == "first"
            assert messages[1].content == "second"
            assert messages[2].content == "third"


class TestListConversations:
    """验证会话列表分页查询"""

    async def test_list_conversations_pagination(self, manager, test_session_factory):
        """测试分页查询返回正确数量"""
        with patch(
            "app.services.conversation_manager.async_session_factory",
            test_session_factory,
        ):
            # 创建5个会话
            for i in range(5):
                await manager.create_conversation(title=f"会话{i}")

            params = ConvListParams(page=1, pageSize=3)
            result = await manager.list_conversations(params)
            assert result.total == 5
            assert len(result.items) == 3
            assert result.page == 1

    async def test_list_conversations_max_page_size(self, manager, test_session_factory):
        """测试每页最多20条限制"""
        with patch(
            "app.services.conversation_manager.async_session_factory",
            test_session_factory,
        ):
            for i in range(25):
                await manager.create_conversation(title=f"会话{i}")

            params = ConvListParams(page=1, pageSize=20)
            result = await manager.list_conversations(params)
            assert len(result.items) <= 20

    async def test_list_conversations_ordered_by_updated_at_desc(
        self, manager, test_session_factory
    ):
        """测试结果按 updated_at 降序排列"""
        with patch(
            "app.services.conversation_manager.async_session_factory",
            test_session_factory,
        ):
            conv1 = await manager.create_conversation(title="旧会话")
            conv2 = await manager.create_conversation(title="新会话")
            # 给 conv2 添加消息使其 updated_at 更新
            await manager.add_message(
                conv2.id, MessageInput(role="user", content="update")
            )

            params = ConvListParams(page=1, pageSize=20)
            result = await manager.list_conversations(params)
            assert len(result.items) == 2
            # 最新更新的在前面
            assert result.items[0].title == "新会话"


class TestSearchConversations:
    """验证会话搜索功能"""

    async def test_search_by_keyword_in_title(self, manager, test_session_factory):
        """测试按标题关键词搜索"""
        with patch(
            "app.services.conversation_manager.async_session_factory",
            test_session_factory,
        ):
            await manager.create_conversation(title="销售分析")
            await manager.create_conversation(title="库存查询")

            params = ConvSearchParams(keyword="销售", limit=50)
            results = await manager.search_conversations(params)
            assert len(results) == 1
            assert results[0].title == "销售分析"

    async def test_search_by_keyword_in_message(self, manager, test_session_factory):
        """测试按消息内容关键词搜索"""
        with patch(
            "app.services.conversation_manager.async_session_factory",
            test_session_factory,
        ):
            conv = await manager.create_conversation(title="普通对话")
            await manager.add_message(
                conv.id, MessageInput(role="user", content="查询今日订单量")
            )

            params = ConvSearchParams(keyword="订单", limit=50)
            results = await manager.search_conversations(params)
            assert len(results) == 1

    async def test_search_limit(self, manager, test_session_factory):
        """测试搜索结果最多50条限制"""
        with patch(
            "app.services.conversation_manager.async_session_factory",
            test_session_factory,
        ):
            params = ConvSearchParams(keyword="test", limit=50)
            results = await manager.search_conversations(params)
            assert len(results) <= 50


class TestContextManagement:
    """验证上下文管理功能"""

    async def test_get_context(self, manager, test_session_factory):
        """测试获取会话上下文"""
        with patch(
            "app.services.conversation_manager.async_session_factory",
            test_session_factory,
        ):
            conv = await manager.create_conversation(title="上下文测试")
            await manager.add_message(
                conv.id,
                MessageInput(
                    role="agent",
                    content="查询销售额",
                    sql="SELECT SUM(amount) FROM orders WHERE date = '2024-01-01'",
                ),
            )

            context = await manager.get_context(conv.id)
            assert len(context["messages"]) == 1
            assert "orders" in context["referencedTables"]

    async def test_get_context_nonexistent(self, manager, test_session_factory):
        """测试获取不存在会话的上下文"""
        with patch(
            "app.services.conversation_manager.async_session_factory",
            test_session_factory,
        ):
            context = await manager.get_context("non-existent")
            assert context["messages"] == []
            assert context["summary"] is None

    async def test_summarize_context(self, manager, test_session_factory):
        """测试上下文摘要压缩"""
        with patch(
            "app.services.conversation_manager.async_session_factory",
            test_session_factory,
        ):
            conv = await manager.create_conversation(title="摘要测试")
            await manager.add_message(
                conv.id,
                MessageInput(
                    role="agent",
                    content="查询转化率结果",
                    sql="SELECT conversion_rate FROM metrics WHERE date > '2024-01-01'",
                    queryResult={"columns": [{"name": "conversion_rate"}], "rows": [[0.85]]},
                ),
            )

            summary_str = await manager.summarize_context(conv.id)
            summary = json.loads(summary_str)
            assert "metrics" in summary["tables"]
            assert "date > '2024-01-01'" in summary["filters"][0]
            assert summary["keyValues"]["conversion_rate"] == 0.85


class TestTurnLimitCompression:
    """验证消息轮次上限控制和摘要压缩"""

    async def test_no_compression_within_limit(self, manager, test_session_factory):
        """测试未超出上限时不触发压缩"""
        with patch(
            "app.services.conversation_manager.async_session_factory",
            test_session_factory,
        ):
            # 使用较小的 max_turns 便于测试
            manager._max_turns = 3
            conv = await manager.create_conversation(title="限制测试")

            # 添加6条消息（3轮），不超出限制
            for i in range(3):
                await manager.add_message(
                    conv.id, MessageInput(role="user", content=f"user msg {i}")
                )
                await manager.add_message(
                    conv.id, MessageInput(role="agent", content=f"agent msg {i}")
                )

            messages = await manager.get_messages(conv.id)
            assert len(messages) == 6  # 未压缩

    async def test_compression_when_exceeds_limit(self, manager, test_session_factory):
        """测试超出上限时触发摘要压缩"""
        with patch(
            "app.services.conversation_manager.async_session_factory",
            test_session_factory,
        ):
            # 设置较小的上限便于测试
            manager._max_turns = 2
            conv = await manager.create_conversation(title="压缩测试")

            # 添加6条消息（3轮），超出2轮限制
            for i in range(3):
                await manager.add_message(
                    conv.id,
                    MessageInput(
                        role="user",
                        content=f"查询销售额 {i}",
                        sql=f"SELECT * FROM orders_{i}",
                    ),
                )
                await manager.add_message(
                    conv.id,
                    MessageInput(role="agent", content=f"结果 {i}"),
                )

            # 验证压缩后消息数不超过 max_turns * 2
            messages = await manager.get_messages(conv.id)
            assert len(messages) <= manager._max_turns * 2

            # 验证摘要已生成
            updated_conv = await manager.get_conversation(conv.id)
            assert updated_conv.context_summary is not None
            summary = json.loads(updated_conv.context_summary)
            assert "tables" in summary


class TestHelperMethods:
    """验证辅助方法"""

    def test_extract_tables_from_sql(self):
        """测试从 SQL 中提取表名"""
        sql = "SELECT * FROM orders JOIN customers ON orders.cid = customers.id"
        tables = ConversationManager._extract_tables_from_sql(sql)
        assert "orders" in tables
        assert "customers" in tables

    def test_extract_filters_from_sql(self):
        """测试从 SQL 中提取 WHERE 条件"""
        sql = "SELECT * FROM orders WHERE date > '2024-01-01' AND status = 'paid' ORDER BY date"
        filters = ConversationManager._extract_filters_from_sql(sql)
        assert len(filters) >= 1
        assert "date > '2024-01-01'" in filters[0]

    def test_extract_metrics_from_content(self):
        """测试从内容中提取指标名称"""
        content = "请查看销售额。转化率是多少？订单量有增长吗？"
        metrics = ConversationManager._extract_metrics_from_content(content)
        # 正则匹配中文指标模式：2-8个汉字 + 率/量/额/数/值等后缀
        # 验证包含指标后缀的词被提取
        assert any("销售额" in m for m in metrics)
        assert any("转化率" in m for m in metrics)
        assert any("订单量" in m for m in metrics)

    def test_extract_key_values(self):
        """测试从查询结果中提取关键数值"""
        result_str = json.dumps({
            "columns": [{"name": "total_sales"}, {"name": "order_count"}],
            "rows": [[15000.5, 120]],
        })
        values = ConversationManager._extract_key_values(result_str)
        assert values["total_sales"] == 15000.5
        assert values["order_count"] == 120

    def test_merge_summaries(self):
        """测试摘要合并"""
        existing = {
            "tables": ["orders"],
            "metrics": ["销售额"],
            "filters": ["date > '2024-01-01'"],
            "keyValues": {"total": 100},
            "turnCount": 5,
        }
        new = {
            "tables": ["customers"],
            "metrics": ["转化率"],
            "filters": ["status = 'active'"],
            "keyValues": {"rate": 0.8},
            "turnCount": 3,
        }
        merged = ConversationManager._merge_summaries(existing, new)
        assert "orders" in merged["tables"]
        assert "customers" in merged["tables"]
        assert "销售额" in merged["metrics"]
        assert "转化率" in merged["metrics"]
        assert len(merged["filters"]) == 2
        assert merged["keyValues"]["total"] == 100
        assert merged["keyValues"]["rate"] == 0.8
        assert merged["turnCount"] == 8

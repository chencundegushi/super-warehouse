"""
Agent Orchestrator 单元测试

测试智能体编排器的核心流程：
- 会话状态管理
- process_query 调用 LangChain Agent
- SQL 确认/拒绝流程
- 查询取消
- Dashboard Builder 模式
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.schemas import (
    MessageInput,
    QueryRequest,
    StreamEvent,
    StreamEventType,
)
from app.services.agent_orchestrator import (
    AgentOrchestrator,
    SessionState,
)


# ============================================================
# SessionState 测试
# ============================================================


class TestSessionState:
    """测试会话状态管理"""

    def test_initial_state(self):
        """验证初始状态正确"""
        state = SessionState("test-session-1")
        assert state.session_id == "test-session-1"
        assert state.conversation_id is None
        assert state.pending_sql is None
        assert state.pending_explanation is None
        assert state.last_query is None
        assert state.mode is None

    def test_clear_pending(self):
        """验证清除待确认状态"""
        state = SessionState("test-session-2")
        state.pending_sql = "SELECT 1"
        state.pending_explanation = "测试"

        state.clear_pending()

        assert state.pending_sql is None
        assert state.pending_explanation is None


# ============================================================
# AgentOrchestrator 核心流程测试
# ============================================================


@pytest.fixture
def orchestrator():
    """创建测试用编排器实例"""
    return AgentOrchestrator()


class TestProcessQuery:
    """测试 process_query 核心流程"""

    @pytest.mark.asyncio
    async def test_process_query_creates_session(self, orchestrator):
        """验证 process_query 创建会话状态"""
        request = QueryRequest(
            session_id="sess-1",
            message="查询今天的销售额",
        )

        # Mock data_query_agent.run 返回一个 thinking 事件
        async def mock_run(**kwargs):
            yield StreamEvent(
                type=StreamEventType.thinking,
                data={"message": "正在分析查询..."},
            )

        with patch("app.services.agent_orchestrator.data_query_agent") as mock_agent, \
             patch("app.services.agent_orchestrator.conversation_manager") as mock_cm:

            mock_agent.run = mock_run
            mock_cm.create_conversation = AsyncMock(
                return_value=MagicMock(id="conv-1")
            )
            mock_cm.add_message = AsyncMock(return_value=MagicMock())
            mock_cm.get_context = AsyncMock(
                return_value={"messages": [], "summary": None}
            )

            events = []
            async for event in orchestrator.process_query(request):
                events.append(event)

        # 验证会话已创建
        session = orchestrator._sessions.get("sess-1")
        assert session is not None
        assert session.last_query == "查询今天的销售额"
        assert session.conversation_id == "conv-1"

    @pytest.mark.asyncio
    async def test_process_query_yields_events_from_agent(self, orchestrator):
        """验证 process_query 转发 Agent 事件"""
        request = QueryRequest(
            session_id="sess-2",
            message="查询日活跃用户数",
        )

        # Mock data_query_agent.run 返回多个事件
        async def mock_run(**kwargs):
            yield StreamEvent(
                type=StreamEventType.thinking,
                data={"message": "正在分析..."},
            )
            yield StreamEvent(
                type=StreamEventType.sql_preview,
                data={"sql": "SELECT COUNT(*) FROM users", "explanation": "统计用户数"},
            )

        with patch("app.services.agent_orchestrator.data_query_agent") as mock_agent, \
             patch("app.services.agent_orchestrator.conversation_manager") as mock_cm:

            mock_agent.run = mock_run
            mock_cm.create_conversation = AsyncMock(
                return_value=MagicMock(id="conv-2")
            )
            mock_cm.add_message = AsyncMock(return_value=MagicMock())
            mock_cm.get_context = AsyncMock(
                return_value={"messages": [], "summary": None}
            )

            events = []
            async for event in orchestrator.process_query(request):
                events.append(event)

        event_types = [e.type for e in events]
        assert StreamEventType.thinking in event_types
        assert StreamEventType.sql_preview in event_types

    @pytest.mark.asyncio
    async def test_process_query_saves_pending_sql(self, orchestrator):
        """验证 sql_preview 事件时保存 pending_sql"""
        request = QueryRequest(
            session_id="sess-3",
            message="查询订单总金额",
            auto_execute=False,
        )

        async def mock_run(**kwargs):
            yield StreamEvent(
                type=StreamEventType.sql_preview,
                data={"sql": "SELECT SUM(amount) FROM orders", "explanation": "订单总金额"},
            )

        with patch("app.services.agent_orchestrator.data_query_agent") as mock_agent, \
             patch("app.services.agent_orchestrator.conversation_manager") as mock_cm:

            mock_agent.run = mock_run
            mock_cm.create_conversation = AsyncMock(
                return_value=MagicMock(id="conv-3")
            )
            mock_cm.add_message = AsyncMock(return_value=MagicMock())
            mock_cm.get_context = AsyncMock(
                return_value={"messages": [], "summary": None}
            )

            events = []
            async for event in orchestrator.process_query(request):
                events.append(event)

        session = orchestrator._sessions["sess-3"]
        assert session.pending_sql == "SELECT SUM(amount) FROM orders"
        assert session.pending_explanation == "订单总金额"

    @pytest.mark.asyncio
    async def test_dashboard_builder_mode(self, orchestrator):
        """验证 dashboard_builder 模式激活"""
        request = QueryRequest(
            session_id="sess-4",
            message="我想看本月充值趋势",
            mode="dashboard_builder",
        )

        async def mock_run(**kwargs):
            assert kwargs.get("mode") == "dashboard_builder"
            yield StreamEvent(
                type=StreamEventType.thinking,
                data={"message": "正在构建大屏..."},
            )

        with patch("app.services.agent_orchestrator.data_query_agent") as mock_agent, \
             patch("app.services.agent_orchestrator.conversation_manager") as mock_cm, \
             patch("app.services.agent_orchestrator.reset_panel_state") as mock_reset:

            mock_agent.run = mock_run
            mock_cm.create_conversation = AsyncMock(
                return_value=MagicMock(id="conv-4")
            )
            mock_cm.add_message = AsyncMock(return_value=MagicMock())
            mock_cm.get_context = AsyncMock(
                return_value={"messages": [], "summary": None}
            )

            events = []
            async for event in orchestrator.process_query(request):
                events.append(event)

        # 验证模式已设置
        session = orchestrator._sessions["sess-4"]
        assert session.mode == "dashboard_builder"
        # 验证 reset_panel_state 被调用
        mock_reset.assert_called_once()


class TestHandleConfirmation:
    """测试 SQL 确认/拒绝流程"""

    @pytest.mark.asyncio
    async def test_confirm_executes_sql(self):
        """验证确认后执行 SQL 并返回结果"""
        orch = AgentOrchestrator()
        session = orch._get_or_create_session("sess-confirm")
        session.conversation_id = "conv-confirm"
        session.pending_sql = "SELECT SUM(amount) FROM orders"
        session.pending_explanation = "查询订单总金额"

        async def mock_execute_confirmed_sql(sql):
            yield StreamEvent(
                type=StreamEventType.executing,
                data={"message": "正在执行..."},
            )
            yield StreamEvent(
                type=StreamEventType.result,
                data={"row_count": 1, "execution_time": 150.0},
            )

        with patch("app.services.agent_orchestrator.data_query_agent") as mock_agent, \
             patch("app.services.agent_orchestrator.conversation_manager") as mock_cm:

            mock_agent.execute_confirmed_sql = mock_execute_confirmed_sql
            mock_cm.add_message = AsyncMock(return_value=MagicMock())

            events = []
            async for event in orch.handle_confirmation("sess-confirm", confirmed=True):
                events.append(event)

        event_types = [e.type for e in events]
        assert StreamEventType.executing in event_types
        assert StreamEventType.result in event_types
        # 确认后 pending_sql 应被清除
        assert session.pending_sql is None

    @pytest.mark.asyncio
    async def test_reject_refines_sql(self):
        """验证拒绝后根据反馈重新生成 SQL"""
        orch = AgentOrchestrator()
        session = orch._get_or_create_session("sess-reject")
        session.conversation_id = "conv-reject"
        session.pending_sql = "SELECT SUM(amount) FROM orders"
        session.pending_explanation = "查询订单总金额"

        async def mock_run(**kwargs):
            yield StreamEvent(
                type=StreamEventType.thinking,
                data={"message": "正在重新生成..."},
            )
            yield StreamEvent(
                type=StreamEventType.sql_preview,
                data={
                    "sql": "SELECT SUM(amount) FROM orders WHERE status = 'paid'",
                    "explanation": "只统计已付款订单",
                },
            )

        with patch("app.services.agent_orchestrator.data_query_agent") as mock_agent, \
             patch("app.services.agent_orchestrator.conversation_manager") as mock_cm:

            mock_agent.run = mock_run
            mock_cm.get_context = AsyncMock(
                return_value={"messages": [], "summary": None}
            )

            events = []
            async for event in orch.handle_confirmation(
                "sess-reject", confirmed=False, feedback="只统计已付款的订单"
            ):
                events.append(event)

        event_types = [e.type for e in events]
        assert StreamEventType.thinking in event_types
        assert StreamEventType.sql_preview in event_types

        sql_event = next(e for e in events if e.type == StreamEventType.sql_preview)
        assert "paid" in sql_event.data["sql"]

    @pytest.mark.asyncio
    async def test_confirm_no_session_returns_error(self):
        """验证会话不存在时返回错误"""
        orch = AgentOrchestrator()

        events = []
        async for event in orch.handle_confirmation("nonexistent", confirmed=True):
            events.append(event)

        assert len(events) == 1
        assert events[0].type == StreamEventType.error
        assert "session_not_found" in events[0].data["error_type"]

    @pytest.mark.asyncio
    async def test_confirm_no_pending_sql_returns_error(self):
        """验证无待确认 SQL 时返回错误"""
        orch = AgentOrchestrator()
        orch._get_or_create_session("sess-no-sql")

        events = []
        async for event in orch.handle_confirmation("sess-no-sql", confirmed=True):
            events.append(event)

        assert len(events) == 1
        assert events[0].type == StreamEventType.error
        assert "no_pending_sql" in events[0].data["error_type"]


class TestCancelQuery:
    """测试查询取消"""

    @pytest.mark.asyncio
    async def test_cancel_clears_pending(self):
        """验证取消查询清除 pending 状态"""
        orch = AgentOrchestrator()
        session = orch._get_or_create_session("sess-cancel")
        session.pending_sql = "SELECT 1"

        result = await orch.cancel_query("sess-cancel")

        assert result.type == StreamEventType.result
        assert result.data["cancelled"] is True
        assert session.pending_sql is None

    @pytest.mark.asyncio
    async def test_cancel_no_session(self):
        """验证会话不存在时取消返回错误"""
        orch = AgentOrchestrator()
        result = await orch.cancel_query("nonexistent")
        assert result.type == StreamEventType.error
        assert "session_not_found" in result.data["error_type"]


class TestGetSessionState:
    """测试会话状态查询"""

    def test_get_existing_session(self):
        """验证获取已存在的会话状态"""
        orch = AgentOrchestrator()
        session = orch._get_or_create_session("sess-state")
        session.conversation_id = "conv-state"
        session.pending_sql = "SELECT 1"

        state = orch.get_session_state("sess-state")
        assert state is not None
        assert state["session_id"] == "sess-state"
        assert state["conversation_id"] == "conv-state"
        assert state["has_pending_sql"] is True

    def test_get_nonexistent_session(self):
        """验证获取不存在的会话返回 None"""
        orch = AgentOrchestrator()
        state = orch.get_session_state("nonexistent")
        assert state is None

"""
Agent Orchestrator 单元测试

测试智能体编排器的核心流程：
- 指标匹配回退到 DDL 生成
- SQL 确认/拒绝流程
- 意图不明确时的澄清流程
- 质疑处理
- 会话状态管理
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.schemas import (
    ChartRecommendation,
    ChartType,
    ColumnInfo,
    DDLInfo,
    ColumnDefinition,
    MessageInput,
    MetricMatchResult,
    QueryRequest,
    QueryResult,
    SQLGenResult,
    StreamEvent,
    StreamEventType,
)
from app.services.agent_orchestrator import (
    AgentOrchestrator,
    SessionState,
    _is_challenge_query,
    _build_challenge_response,
)


# ============================================================
# 辅助函数测试
# ============================================================


class TestIsChallengeQuery:
    """测试质疑类查询识别"""

    def test_challenge_keywords_detected(self):
        """验证质疑关键词能被正确识别"""
        assert _is_challenge_query("为什么结果是这样") is True
        assert _is_challenge_query("数据不对") is True
        assert _is_challenge_query("结果不对吧") is True
        assert _is_challenge_query("解释一下SQL") is True

    def test_normal_query_not_detected(self):
        """验证普通查询不会被误判为质疑"""
        assert _is_challenge_query("查询今天的销售额") is False
        assert _is_challenge_query("帮我统计用户数量") is False
        assert _is_challenge_query("按月份分组") is False


class TestBuildChallengeResponse:
    """测试质疑响应构建"""

    def test_join_suggestion(self):
        """验证包含 JOIN 的 SQL 提供拆分子查询建议"""
        sql = "SELECT * FROM orders JOIN users ON orders.user_id = users.id"
        result = _build_challenge_response(sql, "查询订单")
        assert any("JOIN" in s for s in result["verification_suggestions"])

    def test_where_suggestion(self):
        """验证包含 WHERE 的 SQL 提供去除条件建议"""
        sql = "SELECT * FROM orders WHERE status = 'paid'"
        result = _build_challenge_response(sql, "查询已付款订单")
        assert any("WHERE" in s for s in result["verification_suggestions"])

    def test_group_by_suggestion(self):
        """验证包含 GROUP BY 的 SQL 提供明细抽样建议"""
        sql = "SELECT category, COUNT(*) FROM products GROUP BY category"
        result = _build_challenge_response(sql, "统计分类")
        assert any("明细" in s for s in result["verification_suggestions"])

    def test_default_suggestion(self):
        """验证简单 SQL 提供默认建议"""
        sql = "SELECT * FROM users"
        result = _build_challenge_response(sql, "查询用户")
        assert len(result["verification_suggestions"]) > 0


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
        assert state.pending_referenced_tables == []
        assert state.active_query_id is None
        assert state.ddl_context == []
        assert state.last_query is None

    def test_clear_pending(self):
        """验证清除待确认状态"""
        state = SessionState("test-session-2")
        state.pending_sql = "SELECT 1"
        state.pending_explanation = "测试"
        state.pending_referenced_tables = ["table1"]

        state.clear_pending()

        assert state.pending_sql is None
        assert state.pending_explanation is None
        assert state.pending_referenced_tables == []

    def test_clear_active_query(self):
        """验证清除活跃查询状态"""
        state = SessionState("test-session-3")
        state.active_query_id = "query-123"

        state.clear_active_query()

        assert state.active_query_id is None


# ============================================================
# AgentOrchestrator 核心流程测试
# ============================================================


@pytest.fixture
def orchestrator():
    """创建测试用编排器实例"""
    return AgentOrchestrator()


@pytest.fixture
def mock_ddl_context():
    """模拟 DDL 上下文"""
    from datetime import datetime, timezone
    return [
        DDLInfo(
            id="test_db.orders",
            database="test_db",
            table_name="orders",
            ddl_content="CREATE TABLE orders (id INT, amount DECIMAL)",
            columns=[
                ColumnDefinition(name="id", type="INT", nullable=False, is_primary_key=True),
                ColumnDefinition(name="amount", type="DECIMAL", nullable=True, is_primary_key=False),
            ],
            field_count=2,
            loaded_at=datetime.now(timezone.utc),
        )
    ]


class TestProcessQuery:
    """测试 process_query 核心流程"""

    @pytest.mark.asyncio
    async def test_no_ddl_context_returns_clarification(self, orchestrator):
        """验证无 DDL 上下文时返回 clarification 事件"""
        request = QueryRequest(
            session_id="sess-1",
            message="查询今天的销售额",
        )

        # Mock 依赖
        with patch.object(orchestrator._ddl_manager, "list_loaded_ddl", return_value=[]), \
             patch("app.services.agent_orchestrator.metric_engine") as mock_me, \
             patch("app.services.agent_orchestrator.conversation_manager") as mock_cm:

            mock_me.match_metric = AsyncMock(return_value=None)
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

        # 应该有 thinking 和 clarification 事件
        event_types = [e.type for e in events]
        assert StreamEventType.thinking in event_types
        assert StreamEventType.clarification in event_types

    @pytest.mark.asyncio
    async def test_metric_match_yields_sql_preview(self, orchestrator, mock_ddl_context):
        """验证指标匹配命中时 yield sql_preview 事件"""
        request = QueryRequest(
            session_id="sess-2",
            message="查询日活跃用户数",
        )

        # 模拟指标匹配结果
        mock_metric = MagicMock()
        mock_metric.name = "日活跃用户数"
        mock_metric.sql_template = "SELECT COUNT(*) FROM users WHERE date = '${date}'"

        mock_match = MetricMatchResult(
            metric=mock_metric,
            similarity=0.85,
            candidates=[],
        )

        with patch("app.services.agent_orchestrator.metric_engine") as mock_me, \
             patch("app.services.agent_orchestrator.conversation_manager") as mock_cm:

            mock_me.match_metric = AsyncMock(return_value=mock_match)
            mock_me.extract_parameters = AsyncMock(
                return_value={"date": "2024-01-01"}
            )
            mock_me.detect_missing_parameters = AsyncMock(return_value=[])
            mock_cm.create_conversation = AsyncMock(
                return_value=MagicMock(id="conv-2")
            )
            mock_cm.add_message = AsyncMock(return_value=MagicMock())

            events = []
            async for event in orchestrator.process_query(request):
                events.append(event)

        # 应该有 thinking 和 sql_preview 事件
        event_types = [e.type for e in events]
        assert StreamEventType.thinking in event_types
        assert StreamEventType.sql_preview in event_types

        # sql_preview 事件应包含填充后的 SQL
        sql_event = next(e for e in events if e.type == StreamEventType.sql_preview)
        assert "2024-01-01" in sql_event.data["sql"]
        assert sql_event.data["source"] == "metric"

    @pytest.mark.asyncio
    async def test_metric_missing_params_yields_clarification(self, orchestrator):
        """验证指标缺失参数时 yield clarification 事件"""
        request = QueryRequest(
            session_id="sess-3",
            message="查询日活跃用户数",
        )

        mock_metric = MagicMock()
        mock_metric.name = "日活跃用户数"
        mock_metric.sql_template = "SELECT COUNT(*) FROM users WHERE date = '${date}'"

        mock_match = MetricMatchResult(
            metric=mock_metric,
            similarity=0.85,
            candidates=[],
        )

        with patch("app.services.agent_orchestrator.metric_engine") as mock_me, \
             patch("app.services.agent_orchestrator.conversation_manager") as mock_cm:

            mock_me.match_metric = AsyncMock(return_value=mock_match)
            mock_me.extract_parameters = AsyncMock(return_value={})
            mock_me.detect_missing_parameters = AsyncMock(
                return_value=["date"]
            )
            mock_cm.create_conversation = AsyncMock(
                return_value=MagicMock(id="conv-3")
            )
            mock_cm.add_message = AsyncMock(return_value=MagicMock())

            events = []
            async for event in orchestrator.process_query(request):
                events.append(event)

        event_types = [e.type for e in events]
        assert StreamEventType.clarification in event_types

        clarification_event = next(
            e for e in events if e.type == StreamEventType.clarification
        )
        assert "date" in clarification_event.data["missing_parameters"]

    @pytest.mark.asyncio
    async def test_sql_generation_fallback(self, orchestrator, mock_ddl_context):
        """验证指标未命中时回退到 SQL 生成"""
        request = QueryRequest(
            session_id="sess-4",
            message="查询所有订单总金额",
        )

        mock_sql_result = SQLGenResult(
            sql="SELECT SUM(amount) FROM orders",
            explanation="查询订单总金额",
            confidence=0.9,
            referenced_tables=["orders"],
        )

        with patch("app.services.agent_orchestrator.metric_engine") as mock_me, \
             patch("app.services.agent_orchestrator.conversation_manager") as mock_cm, \
             patch.object(orchestrator._ddl_manager, "list_loaded_ddl", return_value=mock_ddl_context), \
             patch.object(orchestrator._ddl_manager, "detect_unloaded_tables", return_value=[]), \
             patch.object(orchestrator._sql_generator, "generate_sql", return_value=mock_sql_result):

            mock_me.match_metric = AsyncMock(return_value=None)
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

        event_types = [e.type for e in events]
        assert StreamEventType.sql_preview in event_types

        sql_event = next(e for e in events if e.type == StreamEventType.sql_preview)
        assert sql_event.data["source"] == "sql_generator"
        assert "SUM(amount)" in sql_event.data["sql"]

    @pytest.mark.asyncio
    async def test_intent_unclear_yields_clarification(self, orchestrator, mock_ddl_context):
        """验证意图不明确时 yield clarification 事件"""
        request = QueryRequest(
            session_id="sess-5",
            message="嗯",
        )

        # SQL Generator 返回空 SQL 表示意图不明确
        mock_sql_result = SQLGenResult(
            sql="",
            explanation="无法理解您的查询意图，请补充更多细节。",
            confidence=0.0,
            referenced_tables=[],
        )

        with patch("app.services.agent_orchestrator.metric_engine") as mock_me, \
             patch("app.services.agent_orchestrator.conversation_manager") as mock_cm, \
             patch.object(orchestrator._ddl_manager, "list_loaded_ddl", return_value=mock_ddl_context), \
             patch.object(orchestrator._sql_generator, "generate_sql", return_value=mock_sql_result):

            mock_me.match_metric = AsyncMock(return_value=None)
            mock_cm.create_conversation = AsyncMock(
                return_value=MagicMock(id="conv-5")
            )
            mock_cm.add_message = AsyncMock(return_value=MagicMock())
            mock_cm.get_context = AsyncMock(
                return_value={"messages": [], "summary": None}
            )

            events = []
            async for event in orchestrator.process_query(request):
                events.append(event)

        event_types = [e.type for e in events]
        assert StreamEventType.clarification in event_types

    @pytest.mark.asyncio
    async def test_challenge_query_handling(self, orchestrator):
        """验证质疑类查询的处理"""
        request = QueryRequest(
            session_id="sess-6",
            message="为什么结果是这样的",
        )

        # 预设会话状态中有 pending_sql
        session = orchestrator._get_or_create_session("sess-6")
        session.conversation_id = "conv-6"
        session.pending_sql = "SELECT COUNT(*) FROM users"
        session.pending_explanation = "统计用户总数"

        with patch("app.services.agent_orchestrator.conversation_manager") as mock_cm:
            mock_cm.add_message = AsyncMock(return_value=MagicMock())

            events = []
            async for event in orchestrator.process_query(request):
                events.append(event)

        # 应该有 result 事件（包含质疑响应）
        event_types = [e.type for e in events]
        assert StreamEventType.result in event_types

        result_event = next(e for e in events if e.type == StreamEventType.result)
        assert result_event.data["type"] == "challenge_response"
        assert "verification_suggestions" in result_event.data


class TestHandleConfirmation:
    """测试 SQL 确认/拒绝流程"""

    @pytest.fixture
    def orchestrator_with_pending(self):
        """创建带有待确认 SQL 的编排器"""
        orch = AgentOrchestrator()
        session = orch._get_or_create_session("sess-confirm")
        session.conversation_id = "conv-confirm"
        session.pending_sql = "SELECT SUM(amount) FROM orders"
        session.pending_explanation = "查询订单总金额"
        session.ddl_context = []
        return orch

    @pytest.mark.asyncio
    async def test_confirm_executes_sql(self, orchestrator_with_pending):
        """验证确认后执行 SQL 并返回结果"""
        orch = orchestrator_with_pending

        mock_result = QueryResult(
            columns=[
                ColumnInfo(name="total", type="DECIMAL", is_numeric=True, is_date_time=False)
            ],
            rows=[[12345.67]],
            row_count=1,
            execution_time=150.0,
            truncated=False,
        )

        with patch.object(orch._query_executor, "execute_with_retry", new_callable=AsyncMock) as mock_exec, \
             patch("app.services.agent_orchestrator.conversation_manager") as mock_cm, \
             patch("app.services.agent_orchestrator.visualization_engine") as mock_viz:

            mock_exec.return_value = mock_result
            mock_cm.add_message = AsyncMock(return_value=MagicMock())
            mock_viz.recommend_chart_type.return_value = ChartRecommendation(
                recommended=ChartType.table,
                reason="单行数据适合表格展示",
                alternatives=[],
            )
            mock_viz.generate_chart_config.return_value = {"type": "table"}

            events = []
            async for event in orch.handle_confirmation("sess-confirm", confirmed=True):
                events.append(event)

        event_types = [e.type for e in events]
        assert StreamEventType.executing in event_types
        assert StreamEventType.result in event_types
        assert StreamEventType.chart_recommendation in event_types

    @pytest.mark.asyncio
    async def test_reject_refines_sql(self, orchestrator_with_pending):
        """验证拒绝后根据反馈重新生成 SQL"""
        orch = orchestrator_with_pending

        refined_result = SQLGenResult(
            sql="SELECT SUM(amount) FROM orders WHERE status = 'paid'",
            explanation="只统计已付款订单的总金额",
            confidence=0.85,
            referenced_tables=["orders"],
        )

        with patch.object(orch._sql_generator, "refine_sql_with_feedback", return_value=refined_result), \
             patch("app.services.agent_orchestrator.conversation_manager") as mock_cm:

            mock_cm.get_context = AsyncMock(
                return_value={"messages": [], "summary": None}
            )

            events = []
            async for event in orch.handle_confirmation(
                "sess-confirm", confirmed=False, feedback="只统计已付款的订单"
            ):
                events.append(event)

        event_types = [e.type for e in events]
        assert StreamEventType.thinking in event_types
        assert StreamEventType.sql_preview in event_types

        sql_event = next(e for e in events if e.type == StreamEventType.sql_preview)
        assert "paid" in sql_event.data["sql"]
        assert sql_event.data["source"] == "sql_generator_refined"

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
    async def test_cancel_active_query(self):
        """验证取消活跃查询"""
        orch = AgentOrchestrator()
        session = orch._get_or_create_session("sess-cancel")
        session.active_query_id = "query-abc"

        with patch.object(orch._query_executor, "cancel_query", new_callable=AsyncMock) as mock_cancel:
            mock_cancel.return_value = None
            result = await orch.cancel_query("sess-cancel")

        assert result.type == StreamEventType.result
        assert result.data["cancelled"] is True
        assert session.active_query_id is None

    @pytest.mark.asyncio
    async def test_cancel_no_session(self):
        """验证会话不存在时取消返回错误"""
        orch = AgentOrchestrator()
        result = await orch.cancel_query("nonexistent")
        assert result.type == StreamEventType.error
        assert "session_not_found" in result.data["error_type"]

    @pytest.mark.asyncio
    async def test_cancel_no_active_query(self):
        """验证无活跃查询时取消返回错误"""
        orch = AgentOrchestrator()
        orch._get_or_create_session("sess-no-query")
        result = await orch.cancel_query("sess-no-query")
        assert result.type == StreamEventType.error
        assert "no_active_query" in result.data["error_type"]


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
        assert state["has_active_query"] is False

    def test_get_nonexistent_session(self):
        """验证获取不存在的会话返回 None"""
        orch = AgentOrchestrator()
        state = orch.get_session_state("nonexistent")
        assert state is None


class TestExecutionErrors:
    """测试执行错误处理"""

    @pytest.mark.asyncio
    async def test_timeout_error(self):
        """验证查询超时返回 error 事件"""
        orch = AgentOrchestrator()
        session = orch._get_or_create_session("sess-timeout")
        session.conversation_id = "conv-timeout"
        session.pending_sql = "SELECT SLEEP(60)"
        session.pending_explanation = "超时测试"

        with patch.object(orch._query_executor, "execute_with_retry", new_callable=AsyncMock) as mock_exec:
            mock_exec.side_effect = TimeoutError("Query timed out after 30 seconds")

            events = []
            async for event in orch.handle_confirmation("sess-timeout", confirmed=True):
                events.append(event)

        event_types = [e.type for e in events]
        assert StreamEventType.executing in event_types
        assert StreamEventType.error in event_types

        error_event = next(e for e in events if e.type == StreamEventType.error)
        assert "timeout" in error_event.data["error_type"]

    @pytest.mark.asyncio
    async def test_connection_error(self):
        """验证连接失败返回 error 事件"""
        orch = AgentOrchestrator()
        session = orch._get_or_create_session("sess-conn")
        session.conversation_id = "conv-conn"
        session.pending_sql = "SELECT 1"
        session.pending_explanation = "连接测试"

        with patch.object(orch._query_executor, "execute_with_retry", new_callable=AsyncMock) as mock_exec:
            mock_exec.side_effect = ConnectionError("Connection refused")

            events = []
            async for event in orch.handle_confirmation("sess-conn", confirmed=True):
                events.append(event)

        error_event = next(e for e in events if e.type == StreamEventType.error)
        assert "connection_error" in error_event.data["error_type"]

    @pytest.mark.asyncio
    async def test_runtime_error_after_retries(self):
        """验证重试耗尽后返回 error 事件"""
        orch = AgentOrchestrator()
        session = orch._get_or_create_session("sess-retry")
        session.conversation_id = "conv-retry"
        session.pending_sql = "SELECT invalid_column FROM orders"
        session.pending_explanation = "重试测试"

        with patch.object(orch._query_executor, "execute_with_retry", new_callable=AsyncMock) as mock_exec:
            mock_exec.side_effect = RuntimeError("Query failed after 3 attempts")

            events = []
            async for event in orch.handle_confirmation("sess-retry", confirmed=True):
                events.append(event)

        error_event = next(e for e in events if e.type == StreamEventType.error)
        assert "execution_error" in error_event.data["error_type"]
        assert "重试3次" in error_event.data["message"]

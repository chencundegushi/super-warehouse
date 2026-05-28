"""
Dashboard Builder 集成测试

测试 Agent Orchestrator 与 Dashboard Tools 的集成：
- Dashboard Builder 模式识别
- 面板状态重置
- QueryRequest mode 字段
- SessionState mode 跟踪
- StreamEventType 面板事件类型
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.schemas import (
    QueryRequest,
    StreamEvent,
    StreamEventType,
)
from app.services.agent_orchestrator import (
    AgentOrchestrator,
    SessionState,
)
from app.services.dashboard_tools import (
    get_panel_state,
    load_dashboard_tools,
    reset_panel_state,
)


# ============================================================
# StreamEventType 面板事件测试
# ============================================================


class TestStreamEventTypePanelEvents:
    """测试 StreamEventType 包含面板事件类型"""

    def test_panel_created_event_type_exists(self):
        """验证 panel_created 事件类型存在"""
        assert StreamEventType.panel_created == "panel_created"

    def test_panel_updated_event_type_exists(self):
        """验证 panel_updated 事件类型存在"""
        assert StreamEventType.panel_updated == "panel_updated"

    def test_panel_removed_event_type_exists(self):
        """验证 panel_removed 事件类型存在"""
        assert StreamEventType.panel_removed == "panel_removed"


# ============================================================
# QueryRequest mode 字段测试
# ============================================================


class TestQueryRequestMode:
    """测试 QueryRequest 的 mode 字段"""

    def test_mode_field_default_none(self):
        """验证 mode 字段默认为 None"""
        request = QueryRequest(
            session_id="test-session",
            message="hello",
        )
        assert request.mode is None

    def test_mode_field_dashboard_builder(self):
        """验证 mode 字段可设置为 dashboard_builder"""
        request = QueryRequest(
            session_id="test-session",
            message="我想看本月充值趋势",
            mode="dashboard_builder",
        )
        assert request.mode == "dashboard_builder"

    def test_mode_field_from_alias(self):
        """验证 mode 字段通过 JSON 传入"""
        request = QueryRequest(
            sessionId="test-session",
            message="hello",
            mode="dashboard_builder",
        )
        assert request.mode == "dashboard_builder"


# ============================================================
# SessionState mode 跟踪测试
# ============================================================


class TestSessionStateMode:
    """测试 SessionState 的 mode 属性"""

    def test_initial_mode_is_none(self):
        """验证初始 mode 为 None"""
        session = SessionState("test-session")
        assert session.mode is None

    def test_mode_can_be_set(self):
        """验证 mode 可以被设置"""
        session = SessionState("test-session")
        session.mode = "dashboard_builder"
        assert session.mode == "dashboard_builder"

    def test_mode_can_be_reset_to_none(self):
        """验证 mode 可以重置为 None"""
        session = SessionState("test-session")
        session.mode = "dashboard_builder"
        session.mode = None
        assert session.mode is None


# ============================================================
# Dashboard Builder 模式识别测试
# ============================================================


class TestDashboardBuilderModeDetection:
    """测试 AgentOrchestrator 的 Dashboard Builder 模式识别"""

    def test_orchestrator_session_tracks_mode(self):
        """验证 orchestrator 会话跟踪 mode"""
        orchestrator = AgentOrchestrator()
        session = orchestrator._get_or_create_session("test-session")
        assert session.mode is None

    def test_get_session_state_includes_mode(self):
        """验证 get_session_state 返回 mode 字段"""
        orchestrator = AgentOrchestrator()
        session = orchestrator._get_or_create_session("test-session")
        session.mode = "dashboard_builder"
        state = orchestrator.get_session_state("test-session")
        assert state is not None
        assert state["mode"] == "dashboard_builder"

    def test_get_session_state_mode_none_by_default(self):
        """验证 get_session_state 默认 mode 为 None"""
        orchestrator = AgentOrchestrator()
        orchestrator._get_or_create_session("test-session")
        state = orchestrator.get_session_state("test-session")
        assert state["mode"] is None


# ============================================================
# Panel State 重置测试
# ============================================================


class TestPanelStateReset:
    """测试进入 Dashboard Builder 模式时面板状态重置"""

    def setup_method(self):
        """每个测试方法前重置面板状态"""
        reset_panel_state()

    def test_reset_panel_state_clears_panels(self):
        """验证 reset_panel_state 清空面板列表"""
        panel_state = get_panel_state()
        panel_state.add_panel({"panel_id": "test-1", "title": "Test"})
        assert len(panel_state.panels) == 1

        reset_panel_state()
        assert len(panel_state.panels) == 0

    def test_load_dashboard_tools_returns_three_tools(self):
        """验证 load_dashboard_tools 返回3个工具"""
        tools = load_dashboard_tools()
        assert len(tools) == 3
        tool_names = [t.name for t in tools]
        assert "create_panel" in tool_names
        assert "update_panel" in tool_names
        assert "remove_panel" in tool_names


# ============================================================
# StreamEvent 面板事件构造测试
# ============================================================


class TestPanelStreamEvents:
    """测试面板相关 StreamEvent 的构造"""

    def test_panel_created_event(self):
        """验证 panel_created 事件可正确构造"""
        event = StreamEvent(
            type=StreamEventType.panel_created,
            data={
                "panel_id": "abc-123",
                "title": "本月充值趋势",
                "sql": "SELECT * FROM orders",
                "chart_type": "line",
                "position": {"pos_x": 0, "pos_y": 0, "pos_w": 4, "pos_h": 3},
            },
        )
        assert event.type == StreamEventType.panel_created
        assert event.data["panel_id"] == "abc-123"
        assert event.data["title"] == "本月充值趋势"

    def test_panel_updated_event(self):
        """验证 panel_updated 事件可正确构造"""
        event = StreamEvent(
            type=StreamEventType.panel_updated,
            data={
                "panel_id": "abc-123",
                "title": "本月充值趋势（按周）",
                "sql": "SELECT * FROM orders GROUP BY week",
                "chart_type": "bar",
                "position": {"pos_x": 0, "pos_y": 0, "pos_w": 4, "pos_h": 3},
            },
        )
        assert event.type == StreamEventType.panel_updated
        assert event.data["chart_type"] == "bar"

    def test_panel_removed_event(self):
        """验证 panel_removed 事件可正确构造"""
        event = StreamEvent(
            type=StreamEventType.panel_removed,
            data={
                "panel_id": "abc-123",
                "message": "面板已删除",
            },
        )
        assert event.type == StreamEventType.panel_removed
        assert event.data["panel_id"] == "abc-123"

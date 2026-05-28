"""
Dashboard Tools 单元测试

测试 Dashboard Agent Tools 的核心逻辑：
- PanelState 面板状态管理
- 布局位置计算
- CreatePanelTool、UpdatePanelTool、RemovePanelTool 工具行为
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.dashboard_tools import (
    CreatePanelTool,
    PanelState,
    RemovePanelTool,
    UpdatePanelTool,
    _recommend_chart_type,
    get_current_panels,
    get_panel_state,
    load_dashboard_tools,
    reset_panel_state,
)


# ============================================================
# PanelState 测试
# ============================================================


class TestPanelState:
    """面板状态管理测试"""

    def setup_method(self):
        """每个测试前重置状态"""
        self.state = PanelState()

    def test_initial_state_empty(self):
        """初始状态面板列表为空"""
        assert self.state.panels == []

    def test_add_panel(self):
        """添加面板到状态"""
        panel = {"panel_id": "p1", "title": "Test"}
        self.state.add_panel(panel)
        assert len(self.state.panels) == 1
        assert self.state.panels[0]["panel_id"] == "p1"

    def test_remove_panel_success(self):
        """成功移除面板"""
        self.state.add_panel({"panel_id": "p1", "title": "A"})
        self.state.add_panel({"panel_id": "p2", "title": "B"})

        result = self.state.remove_panel("p1")
        assert result is True
        assert len(self.state.panels) == 1
        assert self.state.panels[0]["panel_id"] == "p2"

    def test_remove_panel_not_found(self):
        """移除不存在的面板返回 False"""
        result = self.state.remove_panel("nonexistent")
        assert result is False

    def test_get_panel_found(self):
        """获取存在的面板"""
        self.state.add_panel({"panel_id": "p1", "title": "A"})
        panel = self.state.get_panel("p1")
        assert panel is not None
        assert panel["title"] == "A"

    def test_get_panel_not_found(self):
        """获取不存在的面板返回 None"""
        panel = self.state.get_panel("nonexistent")
        assert panel is None

    def test_update_panel_success(self):
        """成功更新面板"""
        self.state.add_panel({"panel_id": "p1", "title": "Old"})
        result = self.state.update_panel("p1", {"title": "New"})
        assert result is True
        assert self.state.get_panel("p1")["title"] == "New"

    def test_update_panel_not_found(self):
        """更新不存在的面板返回 False"""
        result = self.state.update_panel("nonexistent", {"title": "X"})
        assert result is False

    def test_reset(self):
        """重置清空面板列表"""
        self.state.add_panel({"panel_id": "p1"})
        self.state.add_panel({"panel_id": "p2"})
        self.state.reset()
        assert self.state.panels == []


# ============================================================
# 布局位置计算测试
# ============================================================


class TestLayoutCalculation:
    """面板默认布局位置计算测试"""

    def setup_method(self):
        """每个测试前重置状态"""
        self.state = PanelState()


    def test_first_panel_position(self):
        """第一个面板位于 (0, 0)"""
        pos = self.state.calculate_default_position()
        assert pos == {"pos_x": 0, "pos_y": 0, "pos_w": 4, "pos_h": 3}

    def test_second_panel_position(self):
        """第二个面板位于 (4, 0)"""
        self.state.panels = [{}]
        pos = self.state.calculate_default_position()
        assert pos == {"pos_x": 4, "pos_y": 0, "pos_w": 4, "pos_h": 3}

    def test_third_panel_position(self):
        """第三个面板位于 (8, 0)"""
        self.state.panels = [{}, {}]
        pos = self.state.calculate_default_position()
        assert pos == {"pos_x": 8, "pos_y": 0, "pos_w": 4, "pos_h": 3}

    def test_fourth_panel_wraps_to_next_row(self):
        """第四个面板换行到 (0, 3)"""
        self.state.panels = [{}, {}, {}]
        pos = self.state.calculate_default_position()
        assert pos == {"pos_x": 0, "pos_y": 3, "pos_w": 4, "pos_h": 3}

    def test_seventh_panel_third_row(self):
        """第七个面板位于第三行 (0, 6)"""
        self.state.panels = [{}, {}, {}, {}, {}, {}]
        pos = self.state.calculate_default_position()
        assert pos == {"pos_x": 0, "pos_y": 6, "pos_w": 4, "pos_h": 3}

    def test_all_twelve_positions(self):
        """验证12个面板的完整布局"""
        expected = [
            (0, 0), (4, 0), (8, 0),
            (0, 3), (4, 3), (8, 3),
            (0, 6), (4, 6), (8, 6),
            (0, 9), (4, 9), (8, 9),
        ]
        for i, (exp_x, exp_y) in enumerate(expected):
            self.state.panels = [{}] * i
            pos = self.state.calculate_default_position()
            assert pos["pos_x"] == exp_x, f"Panel {i}: pos_x"
            assert pos["pos_y"] == exp_y, f"Panel {i}: pos_y"
            assert pos["pos_w"] == 4
            assert pos["pos_h"] == 3


# ============================================================
# 图表类型推荐测试
# ============================================================


class TestChartRecommendation:
    """图表类型推荐测试"""

    def test_empty_columns_returns_table(self):
        """无列信息时默认返回 table"""
        result = _recommend_chart_type([])
        assert result == "table"


    def test_datetime_and_numeric_returns_line(self):
        """日期时间列 + 数值列推荐折线图"""
        columns = [
            {"name": "dt", "type": "DATE", "is_numeric": False, "is_date_time": True},
            {"name": "amount", "type": "DECIMAL", "is_numeric": True, "is_date_time": False},
        ]
        result = _recommend_chart_type(columns)
        assert result == "line"

    def test_categorical_and_numeric_returns_bar(self):
        """分类列 + 数值列推荐柱状图"""
        columns = [
            {"name": "game_name", "type": "VARCHAR", "is_numeric": False, "is_date_time": False},
            {"name": "revenue", "type": "DECIMAL", "is_numeric": True, "is_date_time": False},
        ]
        result = _recommend_chart_type(columns)
        assert result == "bar"

    def test_only_numeric_returns_table(self):
        """仅数值列推荐表格"""
        columns = [
            {"name": "count", "type": "INT", "is_numeric": True, "is_date_time": False},
        ]
        result = _recommend_chart_type(columns)
        assert result == "table"


# ============================================================
# Tool 行为测试（Mock LLM 调用）
# ============================================================


class TestCreatePanelTool:
    """CreatePanelTool 测试"""

    def setup_method(self):
        """每个测试前重置全局面板状态"""
        reset_panel_state()

    @patch("app.services.dashboard_tools._generate_panel_sql")
    def test_create_panel_success(self, mock_gen_sql):
        """成功创建面板"""
        mock_gen_sql.return_value = {
            "sql": "SELECT dt, SUM(amount) FROM orders WHERE dt >= CURDATE() - INTERVAL 30 DAY GROUP BY dt",
            "explanation": "查询最近30天订单趋势",
            "suggested_columns": [
                {"name": "dt", "type": "DATE", "is_numeric": False, "is_date_time": True},
                {"name": "SUM(amount)", "type": "DECIMAL", "is_numeric": True, "is_date_time": False},
            ],
        }

        tool = CreatePanelTool()
        result_str = tool._run(title="订单趋势", description="最近30天每日订单金额趋势")
        result = json.loads(result_str)

        assert result["success"] is True
        assert result["title"] == "订单趋势"
        assert "CURDATE()" in result["sql"]
        assert result["chart_type"] == "line"
        assert result["position"]["pos_x"] == 0
        assert result["position"]["pos_y"] == 0


    @patch("app.services.dashboard_tools._generate_panel_sql")
    def test_create_panel_with_specified_chart_type(self, mock_gen_sql):
        """用户指定图表类型时使用指定类型"""
        mock_gen_sql.return_value = {
            "sql": "SELECT game, SUM(revenue) FROM games GROUP BY game ORDER BY SUM(revenue) DESC LIMIT 5",
            "explanation": "游戏收入TOP5",
            "suggested_columns": [],
        }

        tool = CreatePanelTool()
        result_str = tool._run(
            title="游戏TOP5", description="游戏收入排名", chart_type="pie"
        )
        result = json.loads(result_str)

        assert result["success"] is True
        assert result["chart_type"] == "pie"

    @patch("app.services.dashboard_tools._generate_panel_sql")
    def test_create_panel_sql_generation_error(self, mock_gen_sql):
        """SQL 生成失败时返回错误"""
        mock_gen_sql.return_value = {
            "error": "没有已加载的表结构信息，请先加载数据库表结构。",
            "sql": "",
            "explanation": "",
            "suggested_columns": [],
        }

        tool = CreatePanelTool()
        result_str = tool._run(title="Test", description="test")
        result = json.loads(result_str)

        assert result["success"] is False
        assert "error" in result

    @patch("app.services.dashboard_tools._generate_panel_sql")
    def test_create_multiple_panels_layout(self, mock_gen_sql):
        """多次创建面板时布局位置递增"""
        mock_gen_sql.return_value = {
            "sql": "SELECT 1",
            "explanation": "test",
            "suggested_columns": [],
        }

        tool = CreatePanelTool()

        # 创建3个面板
        r1 = json.loads(tool._run(title="P1", description="d1"))
        r2 = json.loads(tool._run(title="P2", description="d2"))
        r3 = json.loads(tool._run(title="P3", description="d3"))

        assert r1["position"] == {"pos_x": 0, "pos_y": 0, "pos_w": 4, "pos_h": 3}
        assert r2["position"] == {"pos_x": 4, "pos_y": 0, "pos_w": 4, "pos_h": 3}
        assert r3["position"] == {"pos_x": 8, "pos_y": 0, "pos_w": 4, "pos_h": 3}


class TestUpdatePanelTool:
    """UpdatePanelTool 测试"""

    def setup_method(self):
        """每个测试前重置状态并添加测试面板"""
        reset_panel_state()
        state = get_panel_state()
        state.add_panel({
            "panel_id": "test-panel-1",
            "title": "原始标题",
            "sql": "SELECT dt, count FROM t WHERE dt >= CURDATE()",
            "chart_type": "line",
            "description": "原始描述",
            "pos_x": 0, "pos_y": 0, "pos_w": 4, "pos_h": 3,
        })


    def test_update_title_only(self):
        """仅更新标题"""
        tool = UpdatePanelTool()
        result_str = tool._run(panel_id="test-panel-1", title="新标题")
        result = json.loads(result_str)

        assert result["success"] is True
        assert result["title"] == "新标题"
        # SQL 不变
        assert "CURDATE()" in result["sql"]

    def test_update_chart_type_only(self):
        """仅更新图表类型"""
        tool = UpdatePanelTool()
        result_str = tool._run(panel_id="test-panel-1", chart_type="bar")
        result = json.loads(result_str)

        assert result["success"] is True
        assert result["chart_type"] == "bar"

    @patch("app.services.dashboard_tools._generate_panel_sql")
    def test_update_description_regenerates_sql(self, mock_gen_sql):
        """更新描述时重新生成 SQL"""
        mock_gen_sql.return_value = {
            "sql": "SELECT dt, SUM(amount) FROM orders WHERE dt >= DATE_SUB(CURDATE(), INTERVAL 7 DAY) GROUP BY dt",
            "explanation": "最近7天订单",
            "suggested_columns": [
                {"name": "dt", "type": "DATE", "is_numeric": False, "is_date_time": True},
                {"name": "SUM(amount)", "type": "DECIMAL", "is_numeric": True, "is_date_time": False},
            ],
        }

        tool = UpdatePanelTool()
        result_str = tool._run(
            panel_id="test-panel-1", description="最近7天订单金额趋势"
        )
        result = json.loads(result_str)

        assert result["success"] is True
        assert "DATE_SUB" in result["sql"]
        assert result["chart_type"] == "line"

    def test_update_nonexistent_panel(self):
        """更新不存在的面板返回错误"""
        tool = UpdatePanelTool()
        result_str = tool._run(panel_id="nonexistent", title="X")
        result = json.loads(result_str)

        assert result["success"] is False
        assert "不存在" in result["error"]

    def test_update_no_changes(self):
        """未提供任何更新内容时返回错误"""
        tool = UpdatePanelTool()
        result_str = tool._run(panel_id="test-panel-1")
        result = json.loads(result_str)

        assert result["success"] is False
        assert "未提供" in result["error"]


class TestRemovePanelTool:
    """RemovePanelTool 测试"""

    def setup_method(self):
        """每个测试前重置状态并添加测试面板"""
        reset_panel_state()
        state = get_panel_state()
        state.add_panel({"panel_id": "p1", "title": "Panel 1"})
        state.add_panel({"panel_id": "p2", "title": "Panel 2"})

    def test_remove_panel_success(self):
        """成功删除面板"""
        tool = RemovePanelTool()
        result_str = tool._run(panel_id="p1")
        result = json.loads(result_str)

        assert result["success"] is True
        assert result["panel_id"] == "p1"
        assert len(get_current_panels()) == 1

    def test_remove_nonexistent_panel(self):
        """删除不存在的面板返回错误"""
        tool = RemovePanelTool()
        result_str = tool._run(panel_id="nonexistent")
        result = json.loads(result_str)

        assert result["success"] is False
        assert "不存在" in result["error"]



# ============================================================
# 工具加载测试
# ============================================================


class TestLoadDashboardTools:
    """工具加载测试"""

    def test_load_returns_three_tools(self):
        """加载返回3个工具"""
        tools = load_dashboard_tools()
        assert len(tools) == 3

    def test_tool_names(self):
        """工具名称正确"""
        tools = load_dashboard_tools()
        names = {t.name for t in tools}
        assert names == {"create_panel", "update_panel", "remove_panel"}

    def test_tools_have_descriptions(self):
        """所有工具都有描述"""
        tools = load_dashboard_tools()
        for tool in tools:
            assert tool.description
            assert len(tool.description) > 10

"""
Visualization Engine 单元测试

验证图表类型推荐、ECharts 配置生成和数据兼容性验证功能。
"""

import pytest

from app.models.schemas import (
    ChartType,
    ColumnInfo,
    QueryResult,
)
from app.services.visualization_engine import (
    VisualizationEngine,
    _extract_column_data,
    _get_categorical_columns,
    _get_datetime_columns,
    _get_numeric_columns,
)


@pytest.fixture
def engine():
    """创建 VisualizationEngine 实例"""
    return VisualizationEngine()


# ============================================================
# 辅助函数测试
# ============================================================


class TestHelperFunctions:
    """验证辅助函数"""

    def test_get_datetime_columns(self):
        """测试获取日期时间列"""
        columns = [
            ColumnInfo(name="date", type="DATE", isNumeric=False, isDateTime=True),
            ColumnInfo(name="amount", type="INT", isNumeric=True, isDateTime=False),
            ColumnInfo(name="name", type="VARCHAR", isNumeric=False, isDateTime=False),
        ]
        result = _get_datetime_columns(columns)
        assert len(result) == 1
        assert result[0].name == "date"

    def test_get_numeric_columns(self):
        """测试获取数值列"""
        columns = [
            ColumnInfo(name="date", type="DATE", isNumeric=False, isDateTime=True),
            ColumnInfo(name="amount", type="INT", isNumeric=True, isDateTime=False),
            ColumnInfo(name="count", type="BIGINT", isNumeric=True, isDateTime=False),
        ]
        result = _get_numeric_columns(columns)
        assert len(result) == 2
        assert result[0].name == "amount"
        assert result[1].name == "count"

    def test_get_categorical_columns(self):
        """测试获取分类维度列"""
        columns = [
            ColumnInfo(name="date", type="DATE", isNumeric=False, isDateTime=True),
            ColumnInfo(name="amount", type="INT", isNumeric=True, isDateTime=False),
            ColumnInfo(name="category", type="VARCHAR", isNumeric=False, isDateTime=False),
        ]
        result = _get_categorical_columns(columns)
        assert len(result) == 1
        assert result[0].name == "category"

    def test_extract_column_data(self):
        """测试从查询结果中提取列数据"""
        query_result = QueryResult(
            columns=[
                ColumnInfo(name="name", type="VARCHAR", isNumeric=False, isDateTime=False),
                ColumnInfo(name="value", type="INT", isNumeric=True, isDateTime=False),
            ],
            rows=[["A", 10], ["B", 20], ["C", 30]],
            rowCount=3,
            executionTime=100,
        )
        data = _extract_column_data(query_result, "value")
        assert data == [10, 20, 30]

    def test_extract_column_data_not_found(self):
        """测试提取不存在的列返回空列表"""
        query_result = QueryResult(
            columns=[
                ColumnInfo(name="name", type="VARCHAR", isNumeric=False, isDateTime=False),
            ],
            rows=[["A"], ["B"]],
            rowCount=2,
            executionTime=50,
        )
        data = _extract_column_data(query_result, "nonexistent")
        assert data == []



# ============================================================
# 图表类型推荐测试
# ============================================================


class TestRecommendChartType:
    """验证图表类型推荐功能"""

    def test_recommend_line_for_datetime_and_numeric(self, engine):
        """测试时间序列+数值列推荐折线图"""
        query_result = QueryResult(
            columns=[
                ColumnInfo(name="date", type="DATE", isNumeric=False, isDateTime=True),
                ColumnInfo(name="sales", type="DECIMAL", isNumeric=True, isDateTime=False),
            ],
            rows=[["2024-01-01", 100], ["2024-01-02", 200]],
            rowCount=2,
            executionTime=50,
        )
        result = engine.recommend_chart_type(query_result)
        assert result.recommended == ChartType.line
        assert ChartType.bar in result.alternatives
        assert ChartType.table in result.alternatives

    def test_recommend_bar_for_categorical_and_numeric(self, engine):
        """测试分类维度+数值列推荐柱状图"""
        query_result = QueryResult(
            columns=[
                ColumnInfo(name="category", type="VARCHAR", isNumeric=False, isDateTime=False),
                ColumnInfo(name="count", type="INT", isNumeric=True, isDateTime=False),
            ],
            rows=[["电子", 50], ["服装", 30], ["食品", 20]],
            rowCount=3,
            executionTime=50,
        )
        result = engine.recommend_chart_type(query_result)
        assert result.recommended == ChartType.bar
        assert ChartType.pie in result.alternatives
        assert ChartType.table in result.alternatives

    def test_recommend_table_for_only_numeric(self, engine):
        """测试仅有数值列时推荐表格"""
        query_result = QueryResult(
            columns=[
                ColumnInfo(name="col1", type="INT", isNumeric=True, isDateTime=False),
                ColumnInfo(name="col2", type="FLOAT", isNumeric=True, isDateTime=False),
            ],
            rows=[[1, 2.5], [3, 4.5]],
            rowCount=2,
            executionTime=50,
        )
        result = engine.recommend_chart_type(query_result)
        assert result.recommended == ChartType.table

    def test_recommend_table_for_empty_columns(self, engine):
        """测试空列时推荐表格"""
        query_result = QueryResult(
            columns=[],
            rows=[],
            rowCount=0,
            executionTime=0,
        )
        result = engine.recommend_chart_type(query_result)
        assert result.recommended == ChartType.table

    def test_line_priority_over_bar(self, engine):
        """测试同时有日期时间列和分类列时，折线图优先"""
        query_result = QueryResult(
            columns=[
                ColumnInfo(name="date", type="DATE", isNumeric=False, isDateTime=True),
                ColumnInfo(name="category", type="VARCHAR", isNumeric=False, isDateTime=False),
                ColumnInfo(name="amount", type="DECIMAL", isNumeric=True, isDateTime=False),
            ],
            rows=[["2024-01-01", "A", 100]],
            rowCount=1,
            executionTime=50,
        )
        result = engine.recommend_chart_type(query_result)
        assert result.recommended == ChartType.line

    def test_recommendation_has_reason(self, engine):
        """测试推荐结果包含原因说明"""
        query_result = QueryResult(
            columns=[
                ColumnInfo(name="name", type="VARCHAR", isNumeric=False, isDateTime=False),
                ColumnInfo(name="value", type="INT", isNumeric=True, isDateTime=False),
            ],
            rows=[["A", 10]],
            rowCount=1,
            executionTime=50,
        )
        result = engine.recommend_chart_type(query_result)
        assert result.reason != ""
        assert len(result.reason) > 0



# ============================================================
# ECharts 配置生成测试
# ============================================================


class TestGenerateChartConfig:
    """验证 ECharts 配置生成功能"""

    def test_generate_line_config(self, engine):
        """测试生成折线图配置"""
        query_result = QueryResult(
            columns=[
                ColumnInfo(name="date", type="DATE", isNumeric=False, isDateTime=True),
                ColumnInfo(name="sales", type="DECIMAL", isNumeric=True, isDateTime=False),
            ],
            rows=[["2024-01-01", 100], ["2024-01-02", 200], ["2024-01-03", 150]],
            rowCount=3,
            executionTime=50,
        )
        config = engine.generate_chart_config(query_result, ChartType.line)
        assert config["type"] == "line"
        assert "xAxis" in config
        assert "yAxis" in config
        assert "series" in config
        assert "legend" in config
        assert "tooltip" in config
        assert config["xAxis"]["data"] == ["2024-01-01", "2024-01-02", "2024-01-03"]
        assert len(config["series"]) == 1
        assert config["series"][0]["data"] == [100, 200, 150]

    def test_generate_bar_config(self, engine):
        """测试生成柱状图配置"""
        query_result = QueryResult(
            columns=[
                ColumnInfo(name="product", type="VARCHAR", isNumeric=False, isDateTime=False),
                ColumnInfo(name="sales", type="INT", isNumeric=True, isDateTime=False),
            ],
            rows=[["A", 50], ["B", 30], ["C", 20]],
            rowCount=3,
            executionTime=50,
        )
        config = engine.generate_chart_config(query_result, ChartType.bar)
        assert config["type"] == "bar"
        assert config["xAxis"]["data"] == ["A", "B", "C"]
        assert config["series"][0]["type"] == "bar"
        assert config["series"][0]["data"] == [50, 30, 20]

    def test_generate_pie_config(self, engine):
        """测试生成饼图配置"""
        query_result = QueryResult(
            columns=[
                ColumnInfo(name="category", type="VARCHAR", isNumeric=False, isDateTime=False),
                ColumnInfo(name="amount", type="DECIMAL", isNumeric=True, isDateTime=False),
            ],
            rows=[["电子", 500], ["服装", 300], ["食品", 200]],
            rowCount=3,
            executionTime=50,
        )
        config = engine.generate_chart_config(query_result, ChartType.pie)
        assert config["type"] == "pie"
        assert "series" in config
        assert len(config["series"]) == 1
        pie_data = config["series"][0]["data"]
        assert len(pie_data) == 3
        assert pie_data[0]["name"] == "电子"
        assert pie_data[0]["value"] == 500

    def test_generate_table_config(self, engine):
        """测试生成表格配置"""
        query_result = QueryResult(
            columns=[
                ColumnInfo(name="id", type="INT", isNumeric=True, isDateTime=False),
                ColumnInfo(name="name", type="VARCHAR", isNumeric=False, isDateTime=False),
            ],
            rows=[[1, "Alice"], [2, "Bob"]],
            rowCount=2,
            executionTime=50,
        )
        config = engine.generate_chart_config(query_result, ChartType.table)
        assert config["type"] == "table"
        assert "columns" in config
        assert len(config["columns"]) == 2
        assert config["columns"][0]["title"] == "id"
        assert config["columns"][1]["title"] == "name"

    def test_generate_line_config_multiple_series(self, engine):
        """测试折线图多系列配置"""
        query_result = QueryResult(
            columns=[
                ColumnInfo(name="month", type="DATE", isNumeric=False, isDateTime=True),
                ColumnInfo(name="revenue", type="DECIMAL", isNumeric=True, isDateTime=False),
                ColumnInfo(name="cost", type="DECIMAL", isNumeric=True, isDateTime=False),
            ],
            rows=[["Jan", 1000, 800], ["Feb", 1200, 900]],
            rowCount=2,
            executionTime=50,
        )
        config = engine.generate_chart_config(query_result, ChartType.line)
        assert len(config["series"]) == 2
        assert config["legend"]["data"] == ["revenue", "cost"]



# ============================================================
# 兼容性验证测试
# ============================================================


class TestValidateCompatibility:
    """验证数据与图表类型兼容性检查"""

    def test_table_always_compatible(self, engine):
        """测试 table 类型始终兼容"""
        query_result = QueryResult(
            columns=[
                ColumnInfo(name="x", type="INT", isNumeric=True, isDateTime=False),
            ],
            rows=[[1]],
            rowCount=1,
            executionTime=50,
        )
        result = engine.validate_compatibility(query_result, ChartType.table)
        assert result.compatible is True
        assert result.warnings == []

    def test_pie_compatible_with_categorical_and_numeric(self, engine):
        """测试饼图兼容：有分类维度+数值度量"""
        query_result = QueryResult(
            columns=[
                ColumnInfo(name="category", type="VARCHAR", isNumeric=False, isDateTime=False),
                ColumnInfo(name="value", type="INT", isNumeric=True, isDateTime=False),
            ],
            rows=[["A", 10]],
            rowCount=1,
            executionTime=50,
        )
        result = engine.validate_compatibility(query_result, ChartType.pie)
        assert result.compatible is True
        assert result.warnings == []

    def test_pie_incompatible_no_categorical(self, engine):
        """测试饼图不兼容：缺少分类维度"""
        query_result = QueryResult(
            columns=[
                ColumnInfo(name="value", type="INT", isNumeric=True, isDateTime=False),
            ],
            rows=[[10]],
            rowCount=1,
            executionTime=50,
        )
        result = engine.validate_compatibility(query_result, ChartType.pie)
        assert result.compatible is False
        assert len(result.warnings) > 0
        assert any("分类维度" in w for w in result.warnings)

    def test_pie_incompatible_no_numeric(self, engine):
        """测试饼图不兼容：缺少数值度量"""
        query_result = QueryResult(
            columns=[
                ColumnInfo(name="name", type="VARCHAR", isNumeric=False, isDateTime=False),
            ],
            rows=[["A"]],
            rowCount=1,
            executionTime=50,
        )
        result = engine.validate_compatibility(query_result, ChartType.pie)
        assert result.compatible is False
        assert any("数值" in w for w in result.warnings)

    def test_line_compatible_with_datetime_and_numeric(self, engine):
        """测试折线图兼容：有日期时间维度+数值度量"""
        query_result = QueryResult(
            columns=[
                ColumnInfo(name="date", type="DATE", isNumeric=False, isDateTime=True),
                ColumnInfo(name="value", type="DECIMAL", isNumeric=True, isDateTime=False),
            ],
            rows=[["2024-01-01", 100]],
            rowCount=1,
            executionTime=50,
        )
        result = engine.validate_compatibility(query_result, ChartType.line)
        assert result.compatible is True
        assert result.warnings == []

    def test_line_incompatible_no_datetime(self, engine):
        """测试折线图不兼容：缺少日期时间维度"""
        query_result = QueryResult(
            columns=[
                ColumnInfo(name="category", type="VARCHAR", isNumeric=False, isDateTime=False),
                ColumnInfo(name="value", type="INT", isNumeric=True, isDateTime=False),
            ],
            rows=[["A", 10]],
            rowCount=1,
            executionTime=50,
        )
        result = engine.validate_compatibility(query_result, ChartType.line)
        assert result.compatible is False
        assert any("时间序列" in w or "日期时间" in w for w in result.warnings)

    def test_line_incompatible_no_numeric(self, engine):
        """测试折线图不兼容：缺少数值度量"""
        query_result = QueryResult(
            columns=[
                ColumnInfo(name="date", type="DATE", isNumeric=False, isDateTime=True),
            ],
            rows=[["2024-01-01"]],
            rowCount=1,
            executionTime=50,
        )
        result = engine.validate_compatibility(query_result, ChartType.line)
        assert result.compatible is False
        assert any("数值" in w for w in result.warnings)

    def test_bar_compatible_with_categorical_and_numeric(self, engine):
        """测试柱状图兼容：有分类维度+数值度量"""
        query_result = QueryResult(
            columns=[
                ColumnInfo(name="product", type="VARCHAR", isNumeric=False, isDateTime=False),
                ColumnInfo(name="sales", type="INT", isNumeric=True, isDateTime=False),
            ],
            rows=[["A", 100]],
            rowCount=1,
            executionTime=50,
        )
        result = engine.validate_compatibility(query_result, ChartType.bar)
        assert result.compatible is True
        assert result.warnings == []

    def test_bar_incompatible_no_categorical(self, engine):
        """测试柱状图不兼容：缺少分类维度"""
        query_result = QueryResult(
            columns=[
                ColumnInfo(name="value", type="INT", isNumeric=True, isDateTime=False),
            ],
            rows=[[10]],
            rowCount=1,
            executionTime=50,
        )
        result = engine.validate_compatibility(query_result, ChartType.bar)
        assert result.compatible is False
        assert any("分类维度" in w for w in result.warnings)

    def test_bar_incompatible_no_numeric(self, engine):
        """测试柱状图不兼容：缺少数值度量"""
        query_result = QueryResult(
            columns=[
                ColumnInfo(name="name", type="VARCHAR", isNumeric=False, isDateTime=False),
            ],
            rows=[["A"]],
            rowCount=1,
            executionTime=50,
        )
        result = engine.validate_compatibility(query_result, ChartType.bar)
        assert result.compatible is False
        assert any("数值" in w for w in result.warnings)

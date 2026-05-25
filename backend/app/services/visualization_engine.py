"""
可视化引擎服务

根据查询结果的数据结构推荐图表类型，生成 ECharts 配置对象，验证数据与图表类型兼容性。
核心功能：
- 图表类型推荐：时间序列→折线图，分类+数值→柱状图，默认→表格
- ECharts 配置生成：生成包含 xAxis、yAxis、series、legend、tooltip 的配置
- 兼容性验证：饼图需分类维度+数值度量、折线图需有序维度+数值度量、柱状图需分类维度+数值度量
"""

import logging
from typing import Optional

from app.models.schemas import (
    ChartRecommendation,
    ChartType,
    ColumnInfo,
    CompatibilityResult,
    QueryResult,
)

logger = logging.getLogger(__name__)


# ============================================================
# 辅助函数
# ============================================================


def _get_datetime_columns(columns: list[ColumnInfo]) -> list[ColumnInfo]:
    """获取日期时间类型的列

    Args:
        columns: 列信息列表

    Returns:
        日期时间类型的列列表
    """
    return [col for col in columns if col.is_date_time]


def _get_numeric_columns(columns: list[ColumnInfo]) -> list[ColumnInfo]:
    """获取数值类型的列

    Args:
        columns: 列信息列表

    Returns:
        数值类型的列列表
    """
    return [col for col in columns if col.is_numeric]



def _get_categorical_columns(columns: list[ColumnInfo]) -> list[ColumnInfo]:
    """获取分类维度列（非数值且非日期时间）

    Args:
        columns: 列信息列表

    Returns:
        分类维度列列表
    """
    return [
        col for col in columns
        if not col.is_numeric and not col.is_date_time
    ]


def _extract_column_data(
    query_result: QueryResult, col_name: str
) -> list:
    """从查询结果中提取指定列的数据

    Args:
        query_result: 查询结果
        col_name: 列名

    Returns:
        该列的数据列表
    """
    # 1.找到列索引
    col_index: Optional[int] = None
    for idx, col in enumerate(query_result.columns):
        if col.name == col_name:
            col_index = idx
            break

    if col_index is None:
        return []

    # 2.提取数据
    return [row[col_index] for row in query_result.rows if col_index < len(row)]



# ============================================================
# VisualizationEngine 服务类
# ============================================================


class VisualizationEngine:
    """可视化引擎

    负责根据查询结果的列类型推荐最佳图表类型，
    生成 ECharts 兼容的配置对象，以及验证数据与图表类型的兼容性。
    """

    def __init__(self) -> None:
        """初始化可视化引擎"""
        logger.info("VisualizationEngine initialized")

    # ============================================================
    # 图表类型推荐
    # ============================================================

    def recommend_chart_type(
        self, query_result: QueryResult
    ) -> ChartRecommendation:
        """根据查询结果的列类型推荐图表类型

        推荐规则：
        - 包含日期时间列 + 数值列 → 推荐折线图
        - 包含分类维度列 + 数值列 → 推荐柱状图
        - 其他情况 → 推荐表格

        Args:
            query_result: 查询结果

        Returns:
            图表推荐结果，包含推荐类型、原因和备选类型
        """
        columns = query_result.columns
        logger.info(
            "Recommending chart type, column_count=%d, row_count=%d",
            len(columns), query_result.row_count,
        )

        datetime_cols = _get_datetime_columns(columns)
        numeric_cols = _get_numeric_columns(columns)
        categorical_cols = _get_categorical_columns(columns)

        # 1.时间序列 + 数值 → 折线图
        if datetime_cols and numeric_cols:
            alternatives = [ChartType.bar, ChartType.table]
            if categorical_cols:
                alternatives.insert(1, ChartType.pie)
            recommendation = ChartRecommendation(
                recommended=ChartType.line,
                reason="数据包含时间序列维度和数值度量，适合使用折线图展示趋势",
                alternatives=alternatives,
            )
            logger.info(
                "Chart recommended: line, datetime_cols=%s, numeric_cols=%s",
                [c.name for c in datetime_cols],
                [c.name for c in numeric_cols],
            )
            return recommendation

        # 2.分类维度 + 数值 → 柱状图
        if categorical_cols and numeric_cols:
            alternatives = [ChartType.pie, ChartType.table]
            recommendation = ChartRecommendation(
                recommended=ChartType.bar,
                reason="数据包含分类维度和数值度量，适合使用柱状图展示对比",
                alternatives=alternatives,
            )
            logger.info(
                "Chart recommended: bar, categorical_cols=%s, numeric_cols=%s",
                [c.name for c in categorical_cols],
                [c.name for c in numeric_cols],
            )
            return recommendation

        # 3.默认 → 表格
        recommendation = ChartRecommendation(
            recommended=ChartType.table,
            reason="数据结构不适合图表展示，推荐使用表格形式",
            alternatives=[ChartType.bar],
        )
        logger.info("Chart recommended: table (default fallback)")
        return recommendation

    # ============================================================
    # ECharts 配置生成
    # ============================================================

    def generate_chart_config(
        self, query_result: QueryResult, chart_type: ChartType
    ) -> dict:
        """生成 ECharts 兼容的图表配置对象

        根据图表类型和查询结果数据，生成包含 xAxis、yAxis、series、
        legend、tooltip 等字段的 ECharts 配置。

        Args:
            query_result: 查询结果
            chart_type: 目标图表类型

        Returns:
            ECharts 配置字典
        """
        logger.info(
            "Generating chart config, chart_type=%s, column_count=%d",
            chart_type.value, len(query_result.columns),
        )

        # 1.根据图表类型分发到对应的配置生成方法
        if chart_type == ChartType.line:
            return self._generate_line_config(query_result)
        elif chart_type == ChartType.bar:
            return self._generate_bar_config(query_result)
        elif chart_type == ChartType.pie:
            return self._generate_pie_config(query_result)
        else:
            # table 类型返回基础配置
            return self._generate_table_config(query_result)

    def _generate_line_config(self, query_result: QueryResult) -> dict:
        """生成折线图 ECharts 配置

        使用日期时间列作为 X 轴，数值列作为 Y 轴系列。

        Args:
            query_result: 查询结果

        Returns:
            折线图 ECharts 配置字典
        """
        columns = query_result.columns
        datetime_cols = _get_datetime_columns(columns)
        numeric_cols = _get_numeric_columns(columns)

        # 选择第一个日期时间列作为 X 轴
        x_col = datetime_cols[0] if datetime_cols else columns[0]
        x_data = _extract_column_data(query_result, x_col.name)

        # 所有数值列作为系列
        series = []
        legend_data = []
        for num_col in numeric_cols:
            y_data = _extract_column_data(query_result, num_col.name)
            series.append({
                "name": num_col.name,
                "type": "line",
                "data": y_data,
                "smooth": True,
            })
            legend_data.append(num_col.name)

        config = {
            "type": "line",
            "xAxis": {
                "type": "category",
                "data": x_data,
                "name": x_col.name,
            },
            "yAxis": {"type": "value"},
            "series": series,
            "legend": {"data": legend_data},
            "tooltip": {"trigger": "axis"},
        }
        logger.info(
            "Line chart config generated, x_col=%s, series_count=%d",
            x_col.name, len(series),
        )
        return config

    def _generate_bar_config(self, query_result: QueryResult) -> dict:
        """生成柱状图 ECharts 配置

        使用分类维度列作为 X 轴，数值列作为 Y 轴系列。

        Args:
            query_result: 查询结果

        Returns:
            柱状图 ECharts 配置字典
        """
        columns = query_result.columns
        categorical_cols = _get_categorical_columns(columns)
        numeric_cols = _get_numeric_columns(columns)

        # 选择第一个分类列作为 X 轴
        x_col = categorical_cols[0] if categorical_cols else columns[0]
        x_data = _extract_column_data(query_result, x_col.name)

        # 所有数值列作为系列
        series = []
        legend_data = []
        for num_col in numeric_cols:
            y_data = _extract_column_data(query_result, num_col.name)
            series.append({
                "name": num_col.name,
                "type": "bar",
                "data": y_data,
            })
            legend_data.append(num_col.name)

        config = {
            "type": "bar",
            "xAxis": {
                "type": "category",
                "data": x_data,
                "name": x_col.name,
            },
            "yAxis": {"type": "value"},
            "series": series,
            "legend": {"data": legend_data},
            "tooltip": {"trigger": "axis"},
        }
        logger.info(
            "Bar chart config generated, x_col=%s, series_count=%d",
            x_col.name, len(series),
        )
        return config

    def _generate_pie_config(self, query_result: QueryResult) -> dict:
        """生成饼图 ECharts 配置

        使用分类维度列作为名称，第一个数值列作为值。

        Args:
            query_result: 查询结果

        Returns:
            饼图 ECharts 配置字典
        """
        columns = query_result.columns
        categorical_cols = _get_categorical_columns(columns)
        numeric_cols = _get_numeric_columns(columns)

        # 选择第一个分类列作为名称维度
        name_col = categorical_cols[0] if categorical_cols else columns[0]
        name_data = _extract_column_data(query_result, name_col.name)

        # 选择第一个数值列作为值
        value_col = numeric_cols[0] if numeric_cols else columns[-1]
        value_data = _extract_column_data(query_result, value_col.name)

        # 构建饼图数据
        pie_data = []
        for i in range(min(len(name_data), len(value_data))):
            pie_data.append({
                "name": str(name_data[i]),
                "value": value_data[i],
            })

        config = {
            "type": "pie",
            "series": [{
                "name": value_col.name,
                "type": "pie",
                "radius": "50%",
                "data": pie_data,
            }],
            "legend": {"data": [str(n) for n in name_data]},
            "tooltip": {"trigger": "item"},
        }
        logger.info(
            "Pie chart config generated, name_col=%s, value_col=%s, data_count=%d",
            name_col.name, value_col.name, len(pie_data),
        )
        return config

    def _generate_table_config(self, query_result: QueryResult) -> dict:
        """生成表格配置

        返回列定义和数据行，供前端表格组件使用。

        Args:
            query_result: 查询结果

        Returns:
            表格配置字典
        """
        table_columns = []
        for col in query_result.columns:
            table_columns.append({
                "title": col.name,
                "dataIndex": col.name,
                "key": col.name,
            })

        config = {
            "type": "table",
            "columns": table_columns,
            "series": [],
            "tooltip": {"trigger": "item"},
        }
        logger.info(
            "Table config generated, column_count=%d",
            len(table_columns),
        )
        return config

    # ============================================================
    # 兼容性验证
    # ============================================================

    def validate_compatibility(
        self, query_result: QueryResult, chart_type: ChartType
    ) -> CompatibilityResult:
        """验证数据与图表类型的兼容性

        兼容性规则：
        - table: 始终兼容
        - pie: 需要至少1个分类维度 + 1个数值度量
        - line: 需要至少1个有序维度（日期时间） + 1个数值度量
        - bar: 需要至少1个分类维度 + 1个数值度量

        Args:
            query_result: 查询结果
            chart_type: 目标图表类型

        Returns:
            兼容性验证结果，包含是否兼容和警告信息
        """
        logger.info(
            "Validating compatibility, chart_type=%s, column_count=%d",
            chart_type.value, len(query_result.columns),
        )

        columns = query_result.columns
        datetime_cols = _get_datetime_columns(columns)
        numeric_cols = _get_numeric_columns(columns)
        categorical_cols = _get_categorical_columns(columns)

        warnings: list[str] = []

        # 1.table 类型始终兼容
        if chart_type == ChartType.table:
            logger.info("Compatibility check passed: table is always compatible")
            return CompatibilityResult(compatible=True, warnings=[])

        # 2.pie 类型：需要分类维度 + 数值度量
        if chart_type == ChartType.pie:
            if not categorical_cols:
                warnings.append(
                    "饼图需要至少1个分类维度列，当前数据缺少分类维度"
                )
            if not numeric_cols:
                warnings.append(
                    "饼图需要至少1个数值度量列，当前数据缺少数值列"
                )
            compatible = len(warnings) == 0
            logger.info(
                "Compatibility check for pie: compatible=%s, warnings=%s",
                compatible, warnings,
            )
            return CompatibilityResult(
                compatible=compatible, warnings=warnings
            )

        # 3.line 类型：需要有序维度（日期时间） + 数值度量
        if chart_type == ChartType.line:
            if not datetime_cols:
                warnings.append(
                    "折线图需要至少1个有序维度（日期时间）列，当前数据缺少时间序列维度"
                )
            if not numeric_cols:
                warnings.append(
                    "折线图需要至少1个数值度量列，当前数据缺少数值列"
                )
            compatible = len(warnings) == 0
            logger.info(
                "Compatibility check for line: compatible=%s, warnings=%s",
                compatible, warnings,
            )
            return CompatibilityResult(
                compatible=compatible, warnings=warnings
            )

        # 4.bar 类型：需要分类维度 + 数值度量
        if chart_type == ChartType.bar:
            if not categorical_cols:
                warnings.append(
                    "柱状图需要至少1个分类维度列，当前数据缺少分类维度"
                )
            if not numeric_cols:
                warnings.append(
                    "柱状图需要至少1个数值度量列，当前数据缺少数值列"
                )
            compatible = len(warnings) == 0
            logger.info(
                "Compatibility check for bar: compatible=%s, warnings=%s",
                compatible, warnings,
            )
            return CompatibilityResult(
                compatible=compatible, warnings=warnings
            )

        # 5.未知类型默认兼容
        logger.info("Compatibility check: unknown chart type, defaulting to compatible")
        return CompatibilityResult(compatible=True, warnings=[])


# ============================================================
# 全局单例
# ============================================================

visualization_engine = VisualizationEngine()

"""
Agent Tools 定义

为 LangChain Agent 提供的工具集。
使用 BaseTool 子类定义工具（与验证过的 AwsBillTool 模式一致）。

工具列表：
- generate_sql: 基于 DDL 上下文和自然语言生成 SQL
- execute_sql: 执行 SQL 查询并返回结果
- recommend_chart: 根据查询结果推荐图表类型
- 动态指标 Tools: 每个指标自动注册为一个 Tool
"""

import json
import logging
import re
from typing import Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services.ddl_manager import DDLManager
from app.services.query_executor import QueryExecutor
from app.services.sql_generator import SQLGenerator, SQLGenParams
from app.services.visualization_engine import visualization_engine

logger = logging.getLogger(__name__)

# 全局服务实例
_ddl_manager = DDLManager()
_sql_generator = SQLGenerator()
_query_executor = QueryExecutor()


# ============================================================
# generate_sql Tool
# ============================================================


class GenerateSQLInput(BaseModel):
    """generate_sql 工具输入"""
    query: str = Field(description="用户的数据查询意图描述")


class GenerateSQLTool(BaseTool):
    """根据自然语言生成 SQL"""
    name: str = "generate_sql"
    description: str = "根据用户的自然语言查询需求，结合数据库表结构生成 Apache Doris SQL 语句。当用户的问题无法匹配任何预定义指标时使用此工具。"
    args_schema: Type[BaseModel] = GenerateSQLInput

    def _run(self, query: str) -> str:
        """同步执行"""
        logger.info("Tool generate_sql called, query=%s", query[:100])

        ddl_context = _ddl_manager.list_loaded_ddl()
        if not ddl_context:
            return json.dumps({"error": "没有已加载的表结构信息，请先加载数据库表结构。"}, ensure_ascii=False)

        params = SQLGenParams(
            user_query=query,
            ddl_context=ddl_context,
            conversation_history=[],
            previous_sql=None,
        )

        try:
            result = _sql_generator.generate_sql(params)
        except Exception as e:
            logger.error("SQL generation failed, error=%s", str(e))
            return json.dumps({"error": f"SQL 生成失败：{str(e)}"}, ensure_ascii=False)

        if not result.sql:
            return json.dumps({
                "clarification_needed": True,
                "message": result.explanation or "无法理解查询意图，请补充更多细节。"
            }, ensure_ascii=False)

        return json.dumps({
            "sql": result.sql,
            "explanation": result.explanation,
            "source": "sql_generator",
        }, ensure_ascii=False)


# ============================================================
# execute_sql Tool
# ============================================================


class ExecuteSQLInput(BaseModel):
    """execute_sql 工具输入"""
    sql: str = Field(description="要执行的 SQL 语句")


class ExecuteSQLTool(BaseTool):
    """执行 SQL 查询"""
    name: str = "execute_sql"
    description: str = "执行 SQL 查询语句，返回查询结果。在获得 SQL 后调用此工具执行查询。"
    args_schema: Type[BaseModel] = ExecuteSQLInput

    def _run(self, sql: str) -> str:
        """同步执行（不会被调用，使用 _arun）"""
        raise NotImplementedError("Use async")

    async def _arun(self, sql: str) -> str:
        """异步执行 SQL"""
        return await _execute_sql_impl(sql)


# ============================================================
# recommend_chart Tool
# ============================================================


class RecommendChartInput(BaseModel):
    """recommend_chart 工具输入"""
    columns_json: str = Field(description="查询结果的列信息 JSON 字符串")
    row_count: int = Field(description="查询结果的行数")


class RecommendChartTool(BaseTool):
    """推荐图表类型"""
    name: str = "recommend_chart"
    description: str = "根据查询结果的列信息和行数推荐可视化图表类型。在查询执行成功后调用。"
    args_schema: Type[BaseModel] = RecommendChartInput

    def _run(self, columns_json: str, row_count: int) -> str:
        """同步执行"""
        return _recommend_chart_impl(columns_json, row_count)


# ============================================================
# 动态指标 Tool（简化版，单参数 JSON 字符串）
# ============================================================


class MetricToolInput(BaseModel):
    """指标工具输入（统一用 JSON 字符串传参，避免复杂 schema）"""
    params_json: str = Field(
        default="{}",
        description="指标参数 JSON 字符串，例如 {\"start_date\": \"2026-01-01\", \"end_date\": \"2026-01-31\"}"
    )


def create_metric_tool(metric) -> BaseTool:
    """为单个指标创建 Tool

    使用简单的单参数 schema（params_json），避免动态 Pydantic Model
    产生复杂 JSON schema 导致 API 代理报错。

    Args:
        metric: 指标 ORM 对象

    Returns:
        BaseTool 实例
    """
    # 构建参数描述
    param_descriptions = []
    if hasattr(metric, 'parameters_rel') and metric.parameters_rel:
        for p in metric.parameters_rel:
            desc = f"{p.name}({p.type})"
            if p.default_value:
                desc += f", 默认={p.default_value}"
            if p.enum_values:
                desc += f", 可选值={p.enum_values}"
            param_descriptions.append(desc)

    params_hint = ""
    if param_descriptions:
        params_hint = f"。参数：{', '.join(param_descriptions)}"

    tool_description = f"指标「{metric.name}」：" + (metric.description or "") + params_hint

    # 清理 tool name（只保留 ASCII 字母数字下划线，中文转拼音或用ID）
    tool_name = f"metric_{metric.id[:8]}"

    # 捕获 metric 到闭包
    _metric = metric

    class DynamicMetricTool(BaseTool):
        """动态指标工具"""
        name: str = tool_name
        description: str = tool_description
        args_schema: Type[BaseModel] = MetricToolInput

        def _run(self, params_json: str = "{}") -> str:
            """执行指标查询"""
            logger.info("Metric tool called, name=%s, params_json=%s", _metric.name, params_json)

            try:
                params = json.loads(params_json) if params_json else {}
            except json.JSONDecodeError:
                params = {}

            # 填充 SQL 模板
            sql = _metric.sql_template
            for param_name, param_value in params.items():
                if param_value is not None:
                    sql = sql.replace(f"${{{param_name}}}", str(param_value))

            # 填充默认值
            if hasattr(_metric, 'parameters_rel') and _metric.parameters_rel:
                for p in _metric.parameters_rel:
                    placeholder = f"${{{p.name}}}"
                    if placeholder in sql and p.default_value:
                        sql = sql.replace(placeholder, p.default_value)

            # 检查未填充的参数
            missing = re.findall(r'\$\{(\w+)\}', sql)
            if missing:
                return json.dumps({
                    "clarification_needed": True,
                    "message": f"指标「{_metric.name}」需要以下参数：{', '.join(missing)}，请提供。"
                }, ensure_ascii=False)

            return json.dumps({
                "sql": sql,
                "explanation": f"基于指标「{_metric.name}」生成 SQL",
                "source": "metric",
                "metric_name": _metric.name,
            }, ensure_ascii=False)

    return DynamicMetricTool()


# ============================================================
# 底层实现函数（供 langchain_agent.py 直接调用）
# ============================================================


async def _execute_sql_impl(sql: str) -> str:
    """执行 SQL 的实际实现"""
    logger.info("Tool execute_sql called, sql=%s", sql[:200])

    try:
        result = await _query_executor.execute_with_retry(sql)
    except TimeoutError:
        return json.dumps({"error": "查询超时（超过30秒）"}, ensure_ascii=False)
    except ConnectionError as e:
        return json.dumps({"error": f"数据库连接失败：{str(e)}"}, ensure_ascii=False)
    except RuntimeError as e:
        return json.dumps({"error": f"查询执行失败：{str(e)}"}, ensure_ascii=False)

    return json.dumps({
        "columns": [col.model_dump() for col in result.columns],
        "rows": result.rows,
        "row_count": result.row_count,
        "execution_time": result.execution_time,
        "truncated": result.truncated,
    }, ensure_ascii=False, default=str)


def _recommend_chart_impl(columns_json: str, row_count: int) -> str:
    """推荐图表类型的实际实现"""
    logger.info("Tool recommend_chart called, row_count=%d", row_count)

    from app.models.schemas import ColumnInfo, QueryResult

    try:
        columns_data = json.loads(columns_json)
        columns = [ColumnInfo(**col) for col in columns_data]
    except (json.JSONDecodeError, Exception) as e:
        return json.dumps({
            "recommended": "table",
            "reason": "无法解析列信息，默认使用表格",
            "alternatives": ["bar"],
        }, ensure_ascii=False)

    qr = QueryResult(columns=columns, rows=[], row_count=row_count, execution_time=0, truncated=False)

    try:
        chart_rec = visualization_engine.recommend_chart_type(qr)
        return json.dumps({
            "recommended": chart_rec.recommended.value,
            "reason": chart_rec.reason,
            "alternatives": [alt.value for alt in chart_rec.alternatives],
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({
            "recommended": "table",
            "reason": f"推荐失败：{str(e)}",
            "alternatives": ["bar"],
        }, ensure_ascii=False)


# ============================================================
# 加载指标工具
# ============================================================


async def load_metric_tools() -> list:
    """从数据库加载所有指标并转换为 Tools"""
    from sqlalchemy import select
    from app.models.database import Metric, MetricParameter, async_session_factory

    logger.info("Loading metric tools from database")

    async with async_session_factory() as session:
        result = await session.execute(select(Metric))
        metrics = result.scalars().all()

        tools = []
        for metric in metrics:
            param_result = await session.execute(
                select(MetricParameter).where(
                    MetricParameter.metric_id == metric.id
                ).order_by(MetricParameter.sort_order)
            )
            metric.parameters_rel = param_result.scalars().all()
            tools.append(create_metric_tool(metric))

    logger.info("Loaded %d metric tools", len(tools))
    return tools

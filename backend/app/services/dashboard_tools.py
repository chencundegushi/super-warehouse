"""
Dashboard Agent Tools

为 LangChain Agent 提供 Dashboard 面板管理工具集。
Agent 在对话中调用这些 tool 实现面板的创建、修改和删除。

工具列表：
- create_panel: 根据标题和描述生成 SQL 并推荐图表类型，创建面板
- update_panel: 根据新描述重新生成 SQL 或更新图表类型/标题
- remove_panel: 删除指定面板

核心设计：
- SQL 生成强调使用相对时间函数（CURDATE、DATE_SUB 等），确保每次打开获取最新数据
- 自动计算面板默认位置：每行最多3个面板（每个宽4列），逐行排列
- 维护当前构建中的面板列表状态
"""

import json
import logging
import uuid
from typing import Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from app.models.schemas import (
    ColumnInfo,
    QueryResult,
    SQLGenParams,
)
from app.services.query_executor import QueryExecutor
from app.services.ddl_manager import DDLManager
from app.services.sql_generator import SQLGenerator
from app.services.visualization_engine import visualization_engine

logger = logging.getLogger(__name__)


# ============================================================
# 全局服务实例
# ============================================================

_ddl_manager = DDLManager()
_sql_generator = SQLGenerator()


# ============================================================
# Dashboard 面板构建状态管理
# ============================================================


# Dashboard SQL 生成专用系统提示词（强调相对时间）
DASHBOARD_SQL_SYSTEM_PROMPT = """你是一个专业的 Apache Doris SQL 生成助手。你的任务是根据用户描述的数据指标需求，结合提供的数据库表结构（DDL），生成用于 Dashboard 面板展示的 SQL 查询语句。

**重要约束 - 必须使用相对时间函数：**
- 所有时间条件必须使用相对时间函数，如 CURDATE()、NOW()、DATE_SUB()、DATE_ADD()、DATE_FORMAT() 等
- 禁止使用硬编码的日期字面量（如 '2024-01-01'、'2025-06-01'）
- INTERVAL 语法中数值和单位之间必须有空格，如 INTERVAL 7 DAY（不是 7DAY）
- 禁止在 INTERVAL 中使用函数表达式（如 DAYOFWEEK(CURDATE()) - 1），只能使用固定数字
- 禁止使用 DAYOFWEEK() 函数，Doris 中计算本周请用以下方式

**正确的相对时间示例（Apache Doris 语法）：**
  - 本月数据：WHERE dt >= DATE_FORMAT(CURDATE(), '%Y-%m-01')
  - 最近7天：WHERE dt >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
  - 最近30天：WHERE dt >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
  - 本周数据（周一起）：WHERE dt >= DATE_SUB(CURDATE(), INTERVAL (DAYOFWEEK_ISO(CURDATE()) - 1) DAY)
  - 本周数据（简化写法）：WHERE dt >= DATE_SUB(CURDATE(), INTERVAL 6 DAY)
  - 上个月：WHERE dt >= DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 1 MONTH), '%Y-%m-01') AND dt < DATE_FORMAT(CURDATE(), '%Y-%m-01')
  - 今年：WHERE dt >= DATE_FORMAT(CURDATE(), '%Y-01-01')

**错误写法（禁止使用）：**
  - ❌ INTERVAL DAYOFWEEK(CURDATE()) - 2DAY  （INTERVAL 中不能用函数表达式）
  - ❌ INTERVAL 7DAY  （数字和单位之间必须有空格）
  - ❌ DATE_SUB(CURDATE(), INTERVAL DAYOFWEEK(CURDATE()) - 1 DAY)  （不支持表达式作为间隔值）

规则：
1. 只使用提供的 DDL 中定义的表和列，表名必须与 DDL 中完全一致（注意下划线），禁止自行拼接或缩写表名
2. 生成的 SQL 必须兼容 Apache Doris 语法
3. 时间条件必须使用相对时间函数，确保每次执行获取最新数据
4. 对于聚合查询，确保 GROUP BY 包含所有非聚合列
5. 结果应适合图表展示，行数控制在合理范围内（通常不超过100行）
6. 如果是趋势类查询，按时间排序；如果是排名类查询，按数值降序排列
7. 当用户说"本周"时，使用 DATE_SUB(CURDATE(), INTERVAL 6 DAY) 获取最近7天数据
8. 当用户说"本月"时，使用 DATE_FORMAT(CURDATE(), '%Y-%m-01') 作为起始日期
9. 表名中的每个单词之间都有下划线分隔，如 dws_game_total_revenue_daily，不要写成 dws_game_total_revenuedaily

输出格式（JSON）：
{
  "sql": "生成的SQL语句",
  "explanation": "SQL的中文解释说明",
  "confidence": 0.0-1.0之间的置信度,
  "referenced_tables": ["引用的表名列表"],
  "suggested_columns": [{"name": "列名", "type": "列类型", "is_numeric": true/false, "is_date_time": true/false}]
}"""


class PanelState:
    """面板构建状态

    维护当前 Dashboard 构建过程中的面板列表，
    用于计算新面板的默认布局位置。

    Attributes:
        panels: 当前面板列表
    """

    def __init__(self) -> None:
        """初始化面板状态"""
        self.panels: list[dict] = []

    def add_panel(self, panel: dict) -> None:
        """添加面板到状态列表

        Args:
            panel: 面板配置字典
        """
        self.panels.append(panel)
        logger.info(
            "Panel added to state, panel_id=%s, total_panels=%d",
            panel.get("panel_id"), len(self.panels),
        )


    def remove_panel(self, panel_id: str) -> bool:
        """从状态列表中移除面板

        Args:
            panel_id: 面板 ID

        Returns:
            是否成功移除
        """
        for i, panel in enumerate(self.panels):
            if panel.get("panel_id") == panel_id:
                self.panels.pop(i)
                logger.info(
                    "Panel removed from state, panel_id=%s, remaining=%d",
                    panel_id, len(self.panels),
                )
                return True
        logger.warning("Panel not found in state, panel_id=%s", panel_id)
        return False

    def get_panel(self, panel_id: str) -> Optional[dict]:
        """获取指定面板

        Args:
            panel_id: 面板 ID

        Returns:
            面板配置字典，未找到返回 None
        """
        for panel in self.panels:
            if panel.get("panel_id") == panel_id:
                return panel
        return None

    def update_panel(self, panel_id: str, updates: dict) -> bool:
        """更新指定面板的配置

        Args:
            panel_id: 面板 ID
            updates: 需要更新的字段字典

        Returns:
            是否成功更新
        """
        for panel in self.panels:
            if panel.get("panel_id") == panel_id:
                panel.update(updates)
                logger.info(
                    "Panel updated in state, panel_id=%s, fields=%s",
                    panel_id, list(updates.keys()),
                )
                return True
        logger.warning("Panel not found for update, panel_id=%s", panel_id)
        return False


    def calculate_default_position(self) -> dict:
        """计算新面板的默认布局位置

        布局规则：每行最多2个面板，每个宽6列，高4行。
        pos_x = panel_index % 2 * 6
        pos_y = panel_index // 2 * 4

        Returns:
            布局位置字典，包含 pos_x, pos_y, pos_w, pos_h
        """
        panel_index = len(self.panels)
        pos_x = (panel_index % 2) * 6
        pos_y = (panel_index // 2) * 4
        pos_w = 6
        pos_h = 4

        logger.info(
            "Calculated default position, index=%d, pos_x=%d, pos_y=%d",
            panel_index, pos_x, pos_y,
        )
        return {
            "pos_x": pos_x,
            "pos_y": pos_y,
            "pos_w": pos_w,
            "pos_h": pos_h,
        }

    def reset(self) -> None:
        """重置面板状态"""
        self.panels = []
        logger.info("Panel state reset")


# 全局面板状态实例
_panel_state = PanelState()


# ============================================================
# 辅助函数
# ============================================================


def _generate_panel_sql(description: str) -> dict:
    """调用 SQL Generator 生成面板 SQL

    在 prompt 中强调使用相对时间函数。

    Args:
        description: 指标描述

    Returns:
        包含 sql、explanation、suggested_columns 的字典
    """
    logger.info("Generating panel SQL, description=%s", description[:100])


    # 1.获取 DDL 上下文
    ddl_context = _ddl_manager.list_loaded_ddl()
    if not ddl_context:
        return {
            "error": "没有已加载的表结构信息，请先加载数据库表结构。",
            "sql": "",
            "explanation": "",
            "suggested_columns": [],
        }

    # 2.构建强调相对时间的查询描述
    enhanced_query = (
        f"为 Dashboard 面板生成 SQL 查询。\n"
        f"指标需求：{description}\n\n"
        f"重要：SQL 中的时间条件必须使用相对时间函数"
        f"（CURDATE()、DATE_SUB()、DATE_FORMAT()、NOW() 等），"
        f"禁止使用硬编码日期。"
    )

    # 3.调用 SQL Generator（使用 Dashboard 专用 prompt）
    params = SQLGenParams(
        user_query=enhanced_query,
        ddl_context=ddl_context,
        conversation_history=[],
        previous_sql=None,
    )

    try:
        # 使用自定义 prompt 调用 LLM
        ddl_text = _sql_generator._build_ddl_context_text(ddl_context)
        user_message = (
            f"## 数据库表结构（DDL）\n{ddl_text}\n\n"
            f"## 指标需求\n{description}\n\n"
            f"请生成用于 Dashboard 面板展示的 SQL 查询。"
            f"时间条件必须使用相对时间函数（CURDATE、DATE_SUB、DATE_FORMAT 等），"
            f"禁止硬编码日期。"
        )
        response = _sql_generator._call_llm(
            DASHBOARD_SQL_SYSTEM_PROMPT, user_message
        )
        parsed = _sql_generator._parse_llm_response(response)

        sql = parsed.get("sql", "")
        explanation = parsed.get("explanation", "")
        suggested_columns = parsed.get("suggested_columns", [])

        logger.info(
            "Panel SQL generated, sql_length=%d, description=%s",
            len(sql), description[:50],
        )
        return {
            "sql": sql,
            "explanation": explanation,
            "suggested_columns": suggested_columns,
        }

    except Exception as e:
        logger.error(
            "Panel SQL generation failed, description=%s, error=%s",
            description[:50], str(e),
        )
        return {
            "error": f"SQL 生成失败：{str(e)}",
            "sql": "",
            "explanation": "",
            "suggested_columns": [],
        }


def _recommend_chart_type(suggested_columns: list[dict]) -> str:
    """根据列信息推荐图表类型

    利用 Visualization Engine 的推荐逻辑，
    根据 SQL 生成时返回的列类型信息推荐最佳图表类型。

    Args:
        suggested_columns: SQL 生成时返回的列信息列表

    Returns:
        推荐的图表类型字符串（table/bar/line/pie）
    """
    logger.info(
        "Recommending chart type, column_count=%d", len(suggested_columns)
    )

    if not suggested_columns:
        logger.info("No column info available, defaulting to table")
        return "table"

    # 1.将 suggested_columns 转换为 ColumnInfo 列表
    try:
        columns = []
        for col in suggested_columns:
            columns.append(ColumnInfo(
                name=col.get("name", "unknown"),
                type=col.get("type", "VARCHAR"),
                is_numeric=col.get("is_numeric", False),
                is_date_time=col.get("is_date_time", False),
            ))

        # 2.构建 QueryResult 用于推荐
        query_result = QueryResult(
            columns=columns,
            rows=[],
            row_count=0,
            execution_time=0,
            truncated=False,
        )

        # 3.调用 Visualization Engine 推荐
        recommendation = visualization_engine.recommend_chart_type(query_result)
        chart_type = recommendation.recommended.value

        logger.info("Chart type recommended: %s", chart_type)
        return chart_type

    except Exception as e:
        logger.error("Chart recommendation failed, error=%s", str(e))
        return "table"


# ============================================================
# Tool 输入 Schema 定义
# ============================================================


class CreatePanelInput(BaseModel):
    """create_panel 工具输入

    Attributes:
        title: 面板标题
        description: 指标描述，用于生成 SQL
        chart_type: 可选，用户指定的图表类型
    """
    title: str = Field(description="面板标题，简洁描述展示的数据内容")
    description: str = Field(
        description="指标描述，详细说明需要查询的数据内容，用于生成 SQL"
    )
    chart_type: Optional[str] = Field(
        default=None,
        description="可选的图表类型（table/bar/line/pie），不指定则自动推荐",
    )



class UpdatePanelInput(BaseModel):
    """update_panel 工具输入

    Attributes:
        panel_id: 面板 ID
        description: 新的指标描述（可选，变更时重新生成 SQL）
        title: 新标题（可选）
        chart_type: 新图表类型（可选）
    """
    panel_id: str = Field(description="要修改的面板 ID")
    description: Optional[str] = Field(
        default=None,
        description="新的指标描述，提供时将重新生成 SQL",
    )
    title: Optional[str] = Field(
        default=None, description="新的面板标题"
    )
    chart_type: Optional[str] = Field(
        default=None,
        description="新的图表类型（table/bar/line/pie）",
    )


class RemovePanelInput(BaseModel):
    """remove_panel 工具输入

    Attributes:
        panel_id: 要删除的面板 ID
    """
    panel_id: str = Field(description="要删除的面板 ID")


# ============================================================
# LangChain Tool 实现
# ============================================================


class CreatePanelTool(BaseTool):
    """创建 Dashboard 面板工具

    接收标题和描述，调用 SQL Generator 生成相对时间 SQL，
    调用 Visualization Engine 推荐图表类型，计算默认布局位置。
    """
    name: str = "create_panel"
    description: str = (
        "为 Dashboard 创建一个新的数据面板。"
        "根据标题和指标描述自动生成 SQL 查询（使用相对时间函数确保数据实时性）"
        "并推荐最佳图表类型。每个面板独立展示一个数据指标。"
    )
    args_schema: Type[BaseModel] = CreatePanelInput

    def _run(
        self,
        title: str,
        description: str,
        chart_type: Optional[str] = None,
    ) -> str:
        """同步版本，不执行 SQL 预览"""
        raise NotImplementedError("Use async")

    async def _arun(
        self,
        title: str,
        description: str,
        chart_type: Optional[str] = None,
    ) -> str:
        """创建面板（异步版本，含 SQL 预览执行）

        Args:
            title: 面板标题
            description: 指标描述
            chart_type: 可选的图表类型

        Returns:
            面板配置 JSON 字符串（含查询预览数据）
        """
        logger.info(
            "Tool create_panel called, title=%s, description=%s",
            title, description[:100],
        )


        # 1.调用 SQL Generator 生成相对时间 SQL
        sql_result = _generate_panel_sql(description)

        if sql_result.get("error"):
            return json.dumps({
                "success": False,
                "error": sql_result["error"],
            }, ensure_ascii=False)

        sql = sql_result["sql"]
        if not sql:
            return json.dumps({
                "success": False,
                "error": "无法根据描述生成 SQL，请提供更具体的指标描述。",
            }, ensure_ascii=False)

        # 2.确定图表类型
        if chart_type and chart_type in ("table", "bar", "line", "pie"):
            final_chart_type = chart_type
        else:
            # 调用 Visualization Engine 推荐
            suggested_columns = sql_result.get("suggested_columns", [])
            final_chart_type = _recommend_chart_type(suggested_columns)

        # 3.计算默认布局位置
        position = _panel_state.calculate_default_position()

        # 4.生成面板 ID
        panel_id = str(uuid.uuid4())

        # 5.构建面板配置
        panel_config = {
            "panel_id": panel_id,
            "title": title,
            "sql": sql,
            "chart_type": final_chart_type,
            "description": description,
            **position,
        }

        # 6.添加到状态
        _panel_state.add_panel(panel_config)

        logger.info(
            "Panel created, panel_id=%s, title=%s, chart_type=%s, pos=(%d,%d)",
            panel_id, title, final_chart_type,
            position["pos_x"], position["pos_y"],
        )

        # 7.立即执行 SQL 获取预览数据
        query_data = None
        query_error = None
        try:
            executor = QueryExecutor()
            result = await executor.execute_sql(sql)
            query_data = {
                "columns": [col.model_dump(by_alias=True) for col in result.columns],
                "rows": result.rows[:50],  # 预览最多50行
                "rowCount": result.row_count,
                "executionTime": result.execution_time,
            }
            logger.info("Panel SQL preview executed, panel_id=%s, rows=%d", panel_id, result.row_count)
        except Exception as e:
            query_error = str(e)
            logger.warning("Panel SQL preview failed, panel_id=%s, error=%s", panel_id, str(e))

        return json.dumps({
            "success": True,
            "panel_id": panel_id,
            "title": title,
            "sql": sql,
            "chart_type": final_chart_type,
            "position": position,
            "query_data": query_data,
            "query_error": query_error,
        }, ensure_ascii=False, default=str)



class UpdatePanelTool(BaseTool):
    """更新 Dashboard 面板工具

    根据新描述重新生成 SQL，或更新图表类型/标题。
    """
    name: str = "update_panel"
    description: str = (
        "修改已有的 Dashboard 面板。"
        "可以更新面板标题、图表类型，或提供新的指标描述重新生成 SQL。"
        "修改不会影响面板的布局位置。"
    )
    args_schema: Type[BaseModel] = UpdatePanelInput

    def _run(
        self,
        panel_id: str,
        description: Optional[str] = None,
        title: Optional[str] = None,
        chart_type: Optional[str] = None,
    ) -> str:
        """同步版本，不执行 SQL 预览"""
        raise NotImplementedError("Use async")

    async def _arun(
        self,
        panel_id: str,
        description: Optional[str] = None,
        title: Optional[str] = None,
        chart_type: Optional[str] = None,
    ) -> str:
        """更新面板（异步版本，含 SQL 预览执行）

        Args:
            panel_id: 面板 ID
            description: 新的指标描述（可选）
            title: 新标题（可选）
            chart_type: 新图表类型（可选）

        Returns:
            更新结果 JSON 字符串
        """
        logger.info(
            "Tool update_panel called, panel_id=%s, has_description=%s, title=%s, chart_type=%s",
            panel_id, description is not None, title, chart_type,
        )

        # 1.查找面板
        panel = _panel_state.get_panel(panel_id)
        if panel is None:
            return json.dumps({
                "success": False,
                "error": f"面板不存在：{panel_id}",
            }, ensure_ascii=False)

        updates = {}

        # 2.如果提供了新描述，重新生成 SQL
        if description:
            sql_result = _generate_panel_sql(description)
            if sql_result.get("error"):
                return json.dumps({
                    "success": False,
                    "error": sql_result["error"],
                }, ensure_ascii=False)

            new_sql = sql_result["sql"]
            if not new_sql:
                return json.dumps({
                    "success": False,
                    "error": "无法根据新描述生成 SQL，请提供更具体的描述。",
                }, ensure_ascii=False)

            updates["sql"] = new_sql
            updates["description"] = description

            # 如果未指定图表类型，根据新 SQL 重新推荐
            if not chart_type:
                suggested_columns = sql_result.get("suggested_columns", [])
                updates["chart_type"] = _recommend_chart_type(suggested_columns)


        # 3.更新标题
        if title:
            updates["title"] = title

        # 4.更新图表类型
        if chart_type and chart_type in ("table", "bar", "line", "pie"):
            updates["chart_type"] = chart_type

        # 5.应用更新
        if not updates:
            return json.dumps({
                "success": False,
                "error": "未提供任何需要更新的内容。",
            }, ensure_ascii=False)

        _panel_state.update_panel(panel_id, updates)

        # 6.获取更新后的面板
        updated_panel = _panel_state.get_panel(panel_id)

        logger.info(
            "Panel updated, panel_id=%s, updated_fields=%s",
            panel_id, list(updates.keys()),
        )

        # 7.执行更新后的 SQL 获取预览数据
        query_data = None
        query_error = None
        final_sql = updated_panel.get("sql", "")
        if final_sql:
            try:
                executor = QueryExecutor()
                result = await executor.execute_sql(final_sql)
                query_data = {
                    "columns": [col.model_dump(by_alias=True) for col in result.columns],
                    "rows": result.rows[:50],
                    "rowCount": result.row_count,
                    "executionTime": result.execution_time,
                }
                logger.info("Panel SQL preview executed (update), panel_id=%s, rows=%d", panel_id, result.row_count)
            except Exception as e:
                query_error = str(e)
                logger.warning("Panel SQL preview failed (update), panel_id=%s, error=%s", panel_id, str(e))

        return json.dumps({
            "success": True,
            "panel_id": panel_id,
            "title": updated_panel.get("title"),
            "sql": updated_panel.get("sql"),
            "chart_type": updated_panel.get("chart_type"),
            "position": {
                "pos_x": updated_panel.get("pos_x"),
                "pos_y": updated_panel.get("pos_y"),
                "pos_w": updated_panel.get("pos_w"),
                "pos_h": updated_panel.get("pos_h"),
            },
            "query_data": query_data,
            "query_error": query_error,
        }, ensure_ascii=False, default=str)


class RemovePanelTool(BaseTool):
    """删除 Dashboard 面板工具

    从当前构建中的 Dashboard 中移除指定面板。
    """
    name: str = "remove_panel"
    description: str = (
        "从 Dashboard 中删除指定面板。"
        "删除后其他面板的布局位置保持不变。"
    )
    args_schema: Type[BaseModel] = RemovePanelInput

    def _run(self, panel_id: str) -> str:
        """删除面板

        Args:
            panel_id: 面板 ID

        Returns:
            删除结果 JSON 字符串
        """
        logger.info("Tool remove_panel called, panel_id=%s", panel_id)

        # 1.移除面板
        success = _panel_state.remove_panel(panel_id)

        if not success:
            return json.dumps({
                "success": False,
                "error": f"面板不存在：{panel_id}",
            }, ensure_ascii=False)

        logger.info("Panel removed, panel_id=%s", panel_id)

        return json.dumps({
            "success": True,
            "panel_id": panel_id,
            "message": "面板已删除",
        }, ensure_ascii=False)



# ============================================================
# 工具加载与状态管理接口
# ============================================================


def load_dashboard_tools() -> list[BaseTool]:
    """加载 Dashboard Agent 工具集

    Returns:
        Dashboard 相关 Tool 列表
    """
    tools = [
        CreatePanelTool(),
        UpdatePanelTool(),
        RemovePanelTool(),
    ]
    logger.info("Loaded %d dashboard tools", len(tools))
    return tools


def get_panel_state() -> PanelState:
    """获取全局面板状态实例

    Returns:
        当前面板状态对象
    """
    return _panel_state


def reset_panel_state() -> None:
    """重置面板状态

    在开始新的 Dashboard 构建会话时调用。
    """
    _panel_state.reset()


def get_current_panels() -> list[dict]:
    """获取当前所有面板配置

    Returns:
        面板配置列表
    """
    return _panel_state.panels.copy()

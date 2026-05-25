"""
Pydantic 模型定义

定义系统中所有 API 请求/响应的数据模型，确保类型安全和数据验证。
包含查询、指标、对话、技能、DDL 等模块的 Schema 定义。
"""

import logging
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ============================================================
# 基础枚举类型
# ============================================================

class StreamEventType(str, Enum):
    """SSE 流事件类型枚举"""
    thinking = "thinking"
    sql_preview = "sql_preview"
    executing = "executing"
    result = "result"
    chart_recommendation = "chart_recommendation"
    error = "error"
    clarification = "clarification"


class ChartType(str, Enum):
    """图表类型枚举"""
    table = "table"
    bar = "bar"
    line = "line"
    pie = "pie"


class MetricParameterType(str, Enum):
    """指标参数类型枚举"""
    string = "string"
    number = "number"
    date = "date"
    enum = "enum"


# ============================================================
# Agent 编排器相关模型
# ============================================================

class QueryRequest(BaseModel):
    """查询请求模型"""
    session_id: str = Field(..., alias="sessionId", description="会话标识")
    message: str = Field(..., description="用户消息内容")
    conversation_id: Optional[str] = Field(
        None, alias="conversationId", description="对话ID，可选"
    )
    auto_execute: bool = Field(
        True, alias="autoExecute", description="是否自动执行SQL（跳过确认）"
    )

    model_config = {"populate_by_name": True}


class StreamEvent(BaseModel):
    """SSE 流事件模型"""
    type: StreamEventType = Field(..., description="事件类型")
    data: Any = Field(..., description="事件数据")


# ============================================================
# SQL 生成相关模型
# ============================================================

class SQLGenResult(BaseModel):
    """SQL 生成结果"""
    sql: str = Field(..., description="生成的SQL语句")
    explanation: str = Field(..., description="SQL解释说明")
    confidence: float = Field(..., ge=0, le=1, description="置信度(0-1)")
    referenced_tables: list[str] = Field(
        default_factory=list,
        alias="referencedTables",
        description="引用的表名列表",
    )

    model_config = {"populate_by_name": True}


class SQLGenParams(BaseModel):
    """SQL 生成参数"""
    user_query: str = Field(..., alias="userQuery", description="用户查询文本")
    ddl_context: list[Any] = Field(
        default_factory=list, alias="ddlContext", description="DDL上下文信息"
    )
    conversation_history: list[Any] = Field(
        default_factory=list,
        alias="conversationHistory",
        description="对话历史",
    )
    previous_sql: Optional[str] = Field(
        None, alias="previousSQL", description="上一次生成的SQL"
    )

    model_config = {"populate_by_name": True}


# ============================================================
# 指标引擎相关模型
# ============================================================

class MetricParameter(BaseModel):
    """指标参数定义"""
    name: str = Field(..., description="参数名称")
    type: MetricParameterType = Field(..., description="参数类型")
    required: bool = Field(True, description="是否必填")
    default_value: Optional[Any] = Field(
        None, alias="defaultValue", description="默认值"
    )
    enum_values: Optional[list[str]] = Field(
        None, alias="enumValues", description="枚举可选值列表"
    )

    model_config = {"populate_by_name": True}


class MetricCreateInput(BaseModel):
    """指标创建输入"""
    name: str = Field(..., max_length=64, description="指标名称，最长64字符")
    description: str = Field(
        ..., max_length=512, description="用途说明，最长512字符"
    )
    sql_template: str = Field(
        ..., alias="sqlTemplate", description="SQL模板"
    )
    parameters: list[MetricParameter] = Field(
        default_factory=list,
        max_length=20,
        description="参数定义列表，最多20个",
    )

    model_config = {"populate_by_name": True}


class MetricUpdateInput(BaseModel):
    """指标更新输入"""
    name: Optional[str] = Field(
        None, max_length=64, description="指标名称，最长64字符"
    )
    description: Optional[str] = Field(
        None, max_length=512, description="用途说明，最长512字符"
    )
    sql_template: Optional[str] = Field(
        None, alias="sqlTemplate", description="SQL模板"
    )
    parameters: Optional[list[MetricParameter]] = Field(
        None, max_length=20, description="参数定义列表，最多20个"
    )

    model_config = {"populate_by_name": True}


class MetricMatchResult(BaseModel):
    """指标匹配结果"""
    metric: Any = Field(..., description="匹配到的指标")
    similarity: float = Field(..., description="相似度分数")
    candidates: list[Any] = Field(
        default_factory=list, description="候选指标列表"
    )


# ============================================================
# 查询执行相关模型
# ============================================================

class ColumnInfo(BaseModel):
    """列信息"""
    name: str = Field(..., description="列名")
    type: str = Field(..., description="列类型")
    is_numeric: bool = Field(False, alias="isNumeric", description="是否为数值类型")
    is_date_time: bool = Field(
        False, alias="isDateTime", description="是否为日期时间类型"
    )

    model_config = {"populate_by_name": True}


class QueryResult(BaseModel):
    """查询结果"""
    columns: list[ColumnInfo] = Field(
        default_factory=list, description="列信息列表"
    )
    rows: list[list[Any]] = Field(default_factory=list, description="数据行")
    row_count: int = Field(0, alias="rowCount", description="结果行数")
    execution_time: float = Field(
        0, alias="executionTime", description="执行耗时(ms)"
    )
    truncated: bool = Field(False, description="是否因maxRows截断")

    model_config = {"populate_by_name": True}


class ChartRecommendation(BaseModel):
    """图表推荐结果"""
    recommended: ChartType = Field(..., description="推荐的图表类型")
    reason: str = Field(..., description="推荐原因")
    alternatives: list[ChartType] = Field(
        default_factory=list, description="备选图表类型"
    )


class CompatibilityResult(BaseModel):
    """图表兼容性验证结果"""
    compatible: bool = Field(..., description="是否兼容")
    warnings: list[str] = Field(
        default_factory=list, description="不兼容时的适配建议"
    )


class ExecuteOptions(BaseModel):
    """查询执行选项"""
    timeout: int = Field(30000, description="超时时间(ms)，默认30000")
    max_rows: int = Field(
        1000, alias="maxRows", description="最大返回行数，默认1000"
    )
    query_id: Optional[str] = Field(
        None, alias="queryId", description="查询标识，用于取消查询"
    )

    model_config = {"populate_by_name": True}


# ============================================================
# 对话管理相关模型
# ============================================================

class ConvListParams(BaseModel):
    """对话列表查询参数"""
    page: int = Field(1, ge=1, description="页码")
    page_size: int = Field(
        20, ge=1, le=20, alias="pageSize", description="每页条数，最大20"
    )
    sort_by: str = Field(
        "updatedAt", alias="sortBy", description="排序字段"
    )
    order: str = Field("desc", description="排序方向")

    model_config = {"populate_by_name": True}


class ConvSearchParams(BaseModel):
    """对话搜索参数"""
    keyword: Optional[str] = Field(None, description="搜索关键词")
    start_time: Optional[datetime] = Field(
        None, alias="startTime", description="开始时间"
    )
    end_time: Optional[datetime] = Field(
        None, alias="endTime", description="结束时间"
    )
    limit: int = Field(50, ge=1, le=50, description="返回条数上限，最大50")

    model_config = {"populate_by_name": True}


class ConversationSummary(BaseModel):
    """对话摘要信息"""
    id: str = Field(..., description="会话ID")
    title: str = Field(..., description="会话标题")
    updated_at: datetime = Field(
        ..., alias="updatedAt", description="最后活跃时间"
    )
    message_count: int = Field(
        0, alias="messageCount", description="消息总数"
    )

    model_config = {"populate_by_name": True}


class MessageInput(BaseModel):
    """消息输入"""
    role: str = Field(..., description="消息角色(user/agent)")
    content: str = Field(..., description="消息文本内容")
    sql: Optional[str] = Field(None, description="关联的SQL语句")
    query_result: Optional[Any] = Field(
        None, alias="queryResult", description="查询结果"
    )

    model_config = {"populate_by_name": True}


# ============================================================
# 技能管理相关模型
# ============================================================

class SkillFile(BaseModel):
    """技能文件"""
    name: str = Field(..., description="技能名称")
    content: str = Field(
        ..., max_length=1048576, description="技能文件内容，最大1MB"
    )
    format: str = Field("claude-skill", description="技能文件格式")


class SkillExecutionResult(BaseModel):
    """技能执行结果"""
    success: bool = Field(..., description="是否执行成功")
    output: Any = Field(None, description="执行输出")
    execution_time: float = Field(
        0, alias="executionTime", description="执行耗时(ms)"
    )
    has_data: bool = Field(
        False, alias="hasData", description="是否包含数据结果"
    )
    data: Optional[QueryResult] = Field(
        None, description="数据结果（如有）"
    )

    model_config = {"populate_by_name": True}


# ============================================================
# DDL 管理相关模型
# ============================================================

class ColumnDefinition(BaseModel):
    """列定义"""
    name: str = Field(..., description="列名")
    type: str = Field(..., description="列类型")
    nullable: bool = Field(True, description="是否可空")
    comment: Optional[str] = Field(None, description="列注释")
    is_primary_key: bool = Field(
        False, alias="isPrimaryKey", description="是否为主键"
    )

    model_config = {"populate_by_name": True}


class DDLLoadParams(BaseModel):
    """DDL 加载参数"""
    database: str = Field(..., description="数据库名")
    tables: Optional[list[str]] = Field(
        None, description="表名列表，为空则加载整个数据库"
    )


class DDLFilterParams(BaseModel):
    """DDL 过滤参数"""
    database: Optional[str] = Field(None, description="数据库名过滤")
    table_name: Optional[str] = Field(
        None, alias="tableName", description="表名过滤"
    )

    model_config = {"populate_by_name": True}


class DDLInfo(BaseModel):
    """DDL 信息"""
    id: str = Field(..., description="DDL记录唯一标识")
    database: str = Field(..., description="数据库名")
    table_name: str = Field(..., alias="tableName", description="表名")
    ddl_content: str = Field(
        ..., alias="ddlContent", description="完整DDL语句"
    )
    columns: list[ColumnDefinition] = Field(
        default_factory=list, description="列定义列表"
    )
    field_count: int = Field(0, alias="fieldCount", description="字段数量")
    loaded_at: datetime = Field(
        ..., alias="loadedAt", description="加载时间"
    )

    model_config = {"populate_by_name": True}


# ============================================================
# 通用分页模型
# ============================================================

class PaginationParams(BaseModel):
    """通用分页参数"""
    page: int = Field(1, ge=1, description="页码")
    page_size: int = Field(
        20, ge=1, alias="pageSize", description="每页条数"
    )

    model_config = {"populate_by_name": True}


class PaginatedResult(BaseModel):
    """通用分页结果"""
    items: list[Any] = Field(default_factory=list, description="数据列表")
    total: int = Field(0, description="总记录数")
    page: int = Field(1, description="当前页码")
    page_size: int = Field(
        20, alias="pageSize", description="每页条数"
    )

    model_config = {"populate_by_name": True}

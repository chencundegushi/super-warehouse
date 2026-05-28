"""
Dashboard 智能大屏 API 路由

提供 Dashboard 的 CRUD 操作、面板 SQL 执行和全量执行接口。
通过 DashboardService 管理大屏配置，通过 QueryExecutor 执行面板 SQL。
面板 SQL 执行前进行安全校验，仅允许 SELECT 语句。

路由前缀: /api/dashboards
"""

import asyncio
import logging
import re
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.dashboard_service import (
    DashboardError,
    DashboardNameConflictError,
    DashboardNameTooLongError,
    DashboardNotFoundError,
    LayoutConstraintError,
    PanelLimitExceededError,
    PanelNotFoundError,
    dashboard_service,
)
from app.services.query_executor import QueryExecutor

logger = logging.getLogger(__name__)

# 创建路由器，设置前缀和标签
router = APIRouter(prefix="/api/dashboards", tags=["dashboards"])

# QueryExecutor 单例实例
_query_executor: Optional[QueryExecutor] = None


def _get_query_executor() -> QueryExecutor:
    """获取查询执行器单例实例

    Returns:
        QueryExecutor 实例
    """
    global _query_executor
    if _query_executor is None:
        _query_executor = QueryExecutor()
    return _query_executor


# ============================================================
# SQL 安全校验
# ============================================================

# 禁止的 SQL 关键字（写操作）
_FORBIDDEN_SQL_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE)\b",
    re.IGNORECASE,
)


def _validate_sql_safety(sql: str) -> None:
    """校验 SQL 安全性，仅允许 SELECT 语句

    规则：
    - SQL 去除前导空白和注释后必须以 SELECT 开头
    - 不得包含 INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE 关键字

    Args:
        sql: 待校验的 SQL 语句

    Raises:
        ValueError: SQL 不安全时抛出
    """
    # 1.去除前导空白
    stripped = sql.strip()

    # 2.去除前导 SQL 注释（单行 -- 和多行 /* */）
    while stripped.startswith("--"):
        stripped = stripped.split("\n", 1)[-1].strip() if "\n" in stripped else ""
    while stripped.startswith("/*"):
        end_idx = stripped.find("*/")
        if end_idx == -1:
            stripped = ""
        else:
            stripped = stripped[end_idx + 2:].strip()

    # 3.检查是否以 SELECT 开头
    if not stripped.upper().startswith("SELECT"):
        raise ValueError("Only SELECT statements are allowed")

    # 4.检查是否包含禁止的关键字
    if _FORBIDDEN_SQL_KEYWORDS.search(stripped):
        raise ValueError(
            "SQL contains forbidden keywords (INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE)"
        )


# ============================================================
# 请求/响应模型
# ============================================================


class PanelInput(BaseModel):
    """面板创建输入"""
    title: str = Field(..., description="面板标题")
    sql: str = Field(..., description="查询SQL")
    chart_type: str = Field(..., alias="chartType", description="图表类型(table/bar/line/pie)")
    pos_x: int = Field(..., alias="posX", description="网格X位置(0-11)")
    pos_y: int = Field(..., alias="posY", description="网格Y位置")
    pos_w: int = Field(..., alias="posW", description="宽度列数(≥3)")
    pos_h: int = Field(..., alias="posH", description="高度行数(≥2)")

    model_config = {"populate_by_name": True}


class CreateDashboardRequest(BaseModel):
    """创建 Dashboard 请求"""
    name: str = Field(..., description="Dashboard名称(≤64字符，系统内唯一)")
    panels: Optional[list[PanelInput]] = Field(None, description="初始面板列表")


class UpdatePanelLayout(BaseModel):
    """面板布局更新输入"""
    id: str = Field(..., description="面板ID")
    title: str = Field(..., description="面板标题")
    sql: str = Field(..., description="查询SQL")
    chart_type: str = Field(..., alias="chartType", description="图表类型")
    pos_x: int = Field(..., alias="posX", description="网格X位置")
    pos_y: int = Field(..., alias="posY", description="网格Y位置")
    pos_w: int = Field(..., alias="posW", description="宽度列数")
    pos_h: int = Field(..., alias="posH", description="高度行数")

    model_config = {"populate_by_name": True}


class UpdateDashboardRequest(BaseModel):
    """更新 Dashboard 请求"""
    name: Optional[str] = Field(None, description="新名称")
    panels: Optional[list[UpdatePanelLayout]] = Field(None, description="面板布局更新列表")


class PanelResponse(BaseModel):
    """面板响应"""
    id: str = Field(..., description="面板ID")
    dashboard_id: str = Field(..., alias="dashboardId", description="所属Dashboard ID")
    title: str = Field(..., description="面板标题")
    sql: str = Field(..., description="查询SQL")
    chart_type: str = Field(..., alias="chartType", description="图表类型")
    pos_x: int = Field(..., alias="posX", description="网格X位置")
    pos_y: int = Field(..., alias="posY", description="网格Y位置")
    pos_w: int = Field(..., alias="posW", description="宽度列数")
    pos_h: int = Field(..., alias="posH", description="高度行数")
    sort_order: int = Field(..., alias="sortOrder", description="排序序号")
    created_at: str = Field(..., alias="createdAt", description="创建时间")
    updated_at: str = Field(..., alias="updatedAt", description="更新时间")

    model_config = {"populate_by_name": True}


class DashboardResponse(BaseModel):
    """Dashboard 详情响应（含面板列表）"""
    id: str = Field(..., description="Dashboard ID")
    name: str = Field(..., description="Dashboard名称")
    created_at: str = Field(..., alias="createdAt", description="创建时间")
    updated_at: str = Field(..., alias="updatedAt", description="更新时间")
    last_accessed_at: str = Field(..., alias="lastAccessedAt", description="最近访问时间")
    panel_count: int = Field(..., alias="panelCount", description="面板数量")
    panels: list[PanelResponse] = Field(default_factory=list, description="面板列表")

    model_config = {"populate_by_name": True}


class DashboardSummaryResponse(BaseModel):
    """Dashboard 摘要响应（列表用）"""
    id: str = Field(..., description="Dashboard ID")
    name: str = Field(..., description="Dashboard名称")
    created_at: str = Field(..., alias="createdAt", description="创建时间")
    updated_at: str = Field(..., alias="updatedAt", description="更新时间")
    last_accessed_at: str = Field(..., alias="lastAccessedAt", description="最近访问时间")
    panel_count: int = Field(..., alias="panelCount", description="面板数量")

    model_config = {"populate_by_name": True}


class DashboardListResponse(BaseModel):
    """Dashboard 列表分页响应"""
    items: list[DashboardSummaryResponse] = Field(..., description="Dashboard列表")
    total: int = Field(..., description="总数")
    page: int = Field(..., description="当前页码")
    page_size: int = Field(..., alias="pageSize", description="每页条数")

    model_config = {"populate_by_name": True}


class PanelExecuteResponse(BaseModel):
    """面板 SQL 执行响应"""
    panel_id: str = Field(..., alias="panelId", description="面板ID")
    title: str = Field(..., description="面板标题")
    columns: list[dict[str, Any]] = Field(default_factory=list, description="列信息")
    rows: list[list[Any]] = Field(default_factory=list, description="数据行")
    row_count: int = Field(0, alias="rowCount", description="行数")
    execution_time: float = Field(0, alias="executionTime", description="执行耗时(ms)")
    truncated: bool = Field(False, description="是否截断")
    error: Optional[str] = Field(None, description="错误信息(执行失败时)")

    model_config = {"populate_by_name": True}


class ExecuteAllResponse(BaseModel):
    """全量执行响应"""
    dashboard_id: str = Field(..., alias="dashboardId", description="Dashboard ID")
    results: list[PanelExecuteResponse] = Field(..., description="各面板执行结果")

    model_config = {"populate_by_name": True}


# ============================================================
# 辅助函数
# ============================================================


def _panel_to_response(panel) -> PanelResponse:
    """将 Panel ORM 对象转换为响应模型

    Args:
        panel: Panel ORM 对象

    Returns:
        PanelResponse 实例
    """
    return PanelResponse(
        id=panel.id,
        dashboardId=panel.dashboard_id,
        title=panel.title,
        sql=panel.sql,
        chartType=panel.chart_type,
        posX=panel.pos_x,
        posY=panel.pos_y,
        posW=panel.pos_w,
        posH=panel.pos_h,
        sortOrder=panel.sort_order,
        createdAt=panel.created_at,
        updatedAt=panel.updated_at,
    )


def _dashboard_to_response(dashboard, include_panels: bool = False) -> DashboardResponse:
    """将 Dashboard ORM 对象转换为响应模型

    Args:
        dashboard: Dashboard ORM 对象
        include_panels: 是否包含面板列表

    Returns:
        DashboardResponse 实例
    """
    panels = []
    if include_panels and hasattr(dashboard, "panels") and dashboard.panels:
        panels = [_panel_to_response(p) for p in dashboard.panels]

    return DashboardResponse(
        id=dashboard.id,
        name=dashboard.name,
        createdAt=dashboard.created_at,
        updatedAt=dashboard.updated_at,
        lastAccessedAt=dashboard.last_accessed_at,
        panelCount=dashboard.panel_count,
        panels=panels,
    )


# ============================================================
# Dashboard CRUD 接口
# ============================================================


@router.post("", summary="创建 Dashboard", status_code=201)
async def create_dashboard(request: CreateDashboardRequest) -> DashboardResponse:
    """创建新 Dashboard

    Args:
        request: 创建请求，包含名称和可选的初始面板列表

    Returns:
        创建的 Dashboard 信息

    Raises:
        HTTPException 400: 名称超长、面板数量超限或布局约束违反
        HTTPException 409: 名称冲突
    """
    logger.info("POST /api/dashboards, name=%s, panels_count=%d",
                request.name, len(request.panels) if request.panels else 0)

    try:
        # 1.转换面板输入为字典列表
        panels_data = None
        if request.panels:
            panels_data = [
                {
                    "title": p.title,
                    "sql": p.sql,
                    "chart_type": p.chart_type,
                    "pos_x": p.pos_x,
                    "pos_y": p.pos_y,
                    "pos_w": p.pos_w,
                    "pos_h": p.pos_h,
                }
                for p in request.panels
            ]

        # 2.调用服务创建
        dashboard = await dashboard_service.create_dashboard(
            name=request.name, panels=panels_data
        )

        # 3.重新获取含面板的完整数据
        dashboard = await dashboard_service.get_dashboard(dashboard.id)

        logger.info("Dashboard created, id=%s, name=%s", dashboard.id, dashboard.name)
        return _dashboard_to_response(dashboard, include_panels=True)

    except DashboardNameTooLongError as e:
        logger.warning("Create dashboard failed, name too long, error=%s", str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except DashboardNameConflictError as e:
        logger.warning("Create dashboard failed, name conflict, error=%s", str(e))
        raise HTTPException(status_code=409, detail=str(e))
    except PanelLimitExceededError as e:
        logger.warning("Create dashboard failed, panel limit, error=%s", str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except LayoutConstraintError as e:
        logger.warning("Create dashboard failed, layout constraint, error=%s", str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except DashboardError as e:
        logger.warning("Create dashboard failed, error=%s", str(e))
        raise HTTPException(status_code=400, detail=str(e))


@router.get("", summary="获取 Dashboard 列表")
async def list_dashboards(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=50, alias="pageSize", description="每页条数"),
) -> DashboardListResponse:
    """分页查询 Dashboard 列表，按最近访问时间降序排列

    Args:
        page: 页码（从1开始）
        page_size: 每页条数（最大50）

    Returns:
        分页结果，包含 Dashboard 摘要列表和总数
    """
    logger.info("GET /api/dashboards, page=%d, page_size=%d", page, page_size)

    result = await dashboard_service.list_dashboards(page=page, page_size=page_size)

    items = [
        DashboardSummaryResponse(
            id=item["id"],
            name=item["name"],
            createdAt=item["created_at"],
            updatedAt=item["updated_at"],
            lastAccessedAt=item["last_accessed_at"],
            panelCount=item["panel_count"],
        )
        for item in result["items"]
    ]

    logger.info("List dashboards completed, total=%d, returned=%d", result["total"], len(items))
    return DashboardListResponse(
        items=items,
        total=result["total"],
        page=result["page"],
        pageSize=result["page_size"],
    )


@router.get("/{dashboard_id}", summary="获取 Dashboard 详情")
async def get_dashboard(dashboard_id: str) -> DashboardResponse:
    """获取 Dashboard 详情，包含所有面板配置

    获取时自动更新最近访问时间。

    Args:
        dashboard_id: Dashboard ID

    Returns:
        Dashboard 详情（含面板列表）

    Raises:
        HTTPException 404: Dashboard 不存在
    """
    logger.info("GET /api/dashboards/%s", dashboard_id)

    try:
        dashboard = await dashboard_service.get_dashboard(dashboard_id)
        logger.info("Dashboard retrieved, id=%s, panel_count=%d",
                    dashboard_id, dashboard.panel_count)
        return _dashboard_to_response(dashboard, include_panels=True)

    except DashboardNotFoundError as e:
        logger.warning("Dashboard not found, id=%s", dashboard_id)
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/{dashboard_id}", summary="更新 Dashboard")
async def update_dashboard(
    dashboard_id: str, request: UpdateDashboardRequest
) -> DashboardResponse:
    """更新 Dashboard 基本信息（名称）

    Args:
        dashboard_id: Dashboard ID
        request: 更新请求

    Returns:
        更新后的 Dashboard 信息

    Raises:
        HTTPException 400: 名称超长
        HTTPException 404: Dashboard 不存在
        HTTPException 409: 名称冲突
    """
    logger.info("PUT /api/dashboards/%s, new_name=%s", dashboard_id, request.name)

    try:
        # 1.更新名称（如果提供）
        dashboard = await dashboard_service.update_dashboard(
            dashboard_id=dashboard_id, name=request.name
        )

        # 2.更新面板布局（如果提供）
        if request.panels:
            layout = [
                {
                    "panel_id": p.id,
                    "pos_x": p.pos_x,
                    "pos_y": p.pos_y,
                    "pos_w": p.pos_w,
                    "pos_h": p.pos_h,
                }
                for p in request.panels
            ]
            await dashboard_service.update_layout(dashboard_id, layout)

            # 同时更新面板的 title、sql、chart_type
            for p in request.panels:
                await dashboard_service.update_panel(
                    dashboard_id=dashboard_id,
                    panel_id=p.id,
                    title=p.title,
                    sql=p.sql,
                    chart_type=p.chart_type,
                )

        logger.info("Dashboard updated, id=%s", dashboard_id)
        # 重新获取完整数据返回
        dashboard = await dashboard_service.get_dashboard(dashboard_id)
        return _dashboard_to_response(dashboard, include_panels=True)

    except DashboardNotFoundError as e:
        logger.warning("Dashboard not found, id=%s", dashboard_id)
        raise HTTPException(status_code=404, detail=str(e))
    except DashboardNameTooLongError as e:
        logger.warning("Update dashboard failed, name too long, error=%s", str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except DashboardNameConflictError as e:
        logger.warning("Update dashboard failed, name conflict, error=%s", str(e))
        raise HTTPException(status_code=409, detail=str(e))


@router.delete("/{dashboard_id}", summary="删除 Dashboard", status_code=204)
async def delete_dashboard(dashboard_id: str) -> None:
    """删除 Dashboard 及其所有面板

    Args:
        dashboard_id: Dashboard ID

    Raises:
        HTTPException 404: Dashboard 不存在
    """
    logger.info("DELETE /api/dashboards/%s", dashboard_id)

    try:
        await dashboard_service.delete_dashboard(dashboard_id)
        logger.info("Dashboard deleted, id=%s", dashboard_id)

    except DashboardNotFoundError as e:
        logger.warning("Dashboard not found, id=%s", dashboard_id)
        raise HTTPException(status_code=404, detail=str(e))


# ============================================================
# 面板 SQL 执行接口
# ============================================================


@router.post("/{dashboard_id}/panels/{panel_id}/execute", summary="执行单面板 SQL")
async def execute_panel(dashboard_id: str, panel_id: str) -> PanelExecuteResponse:
    """执行单个面板的 SQL 查询

    执行前进行 SQL 安全校验，仅允许 SELECT 语句。

    Args:
        dashboard_id: Dashboard ID
        panel_id: Panel ID

    Returns:
        面板执行结果（含列信息和数据行）

    Raises:
        HTTPException 400: SQL 安全校验失败
        HTTPException 404: Dashboard 或 Panel 不存在
        HTTPException 408: 查询超时
        HTTPException 500: 查询执行错误
    """
    logger.info("POST /api/dashboards/%s/panels/%s/execute", dashboard_id, panel_id)

    # 1.获取 Dashboard 和面板信息
    try:
        dashboard = await dashboard_service.get_dashboard_readonly(dashboard_id)
    except DashboardNotFoundError:
        logger.warning("Dashboard not found, id=%s", dashboard_id)
        raise HTTPException(status_code=404, detail=f"Dashboard not found: {dashboard_id}")

    # 2.查找目标面板
    target_panel = None
    if dashboard.panels:
        for panel in dashboard.panels:
            if panel.id == panel_id:
                target_panel = panel
                break

    if target_panel is None:
        logger.warning("Panel not found, panel_id=%s, dashboard_id=%s", panel_id, dashboard_id)
        raise HTTPException(
            status_code=404,
            detail=f"Panel not found: {panel_id} in dashboard {dashboard_id}",
        )

    # 3.SQL 安全校验
    try:
        _validate_sql_safety(target_panel.sql)
    except ValueError as e:
        logger.warning("SQL safety check failed, panel_id=%s, error=%s", panel_id, str(e))
        raise HTTPException(status_code=400, detail=str(e))

    # 4.执行 SQL
    try:
        executor = _get_query_executor()
        result = await executor.execute_sql(target_panel.sql)

        logger.info("Panel SQL executed, panel_id=%s, rows=%d, time=%.2fms",
                    panel_id, result.row_count, result.execution_time)

        return PanelExecuteResponse(
            panelId=target_panel.id,
            title=target_panel.title,
            columns=[col.model_dump(by_alias=True) for col in result.columns],
            rows=result.rows,
            rowCount=result.row_count,
            executionTime=result.execution_time,
            truncated=result.truncated,
            error=None,
        )
    except TimeoutError as e:
        logger.error("Panel SQL timed out, panel_id=%s, error=%s", panel_id, str(e))
        raise HTTPException(status_code=408, detail=str(e))
    except ConnectionError as e:
        logger.error("Doris connection failed, panel_id=%s, error=%s", panel_id, str(e))
        raise HTTPException(status_code=503, detail=str(e))
    except RuntimeError as e:
        logger.error("Panel SQL execution failed, panel_id=%s, error=%s", panel_id, str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{dashboard_id}/execute-all", summary="执行所有面板 SQL")
async def execute_all_panels(dashboard_id: str) -> ExecuteAllResponse:
    """并行执行 Dashboard 中所有面板的 SQL 查询

    每个面板独立执行，单面板失败不影响其他面板。
    执行前对每个面板进行 SQL 安全校验。

    Args:
        dashboard_id: Dashboard ID

    Returns:
        所有面板的执行结果列表

    Raises:
        HTTPException 404: Dashboard 不存在
    """
    logger.info("POST /api/dashboards/%s/execute-all", dashboard_id)

    # 1.获取 Dashboard 及所有面板
    try:
        dashboard = await dashboard_service.get_dashboard_readonly(dashboard_id)
    except DashboardNotFoundError:
        logger.warning("Dashboard not found, id=%s", dashboard_id)
        raise HTTPException(status_code=404, detail=f"Dashboard not found: {dashboard_id}")

    panels = dashboard.panels if dashboard.panels else []
    if not panels:
        logger.info("Dashboard has no panels, id=%s", dashboard_id)
        return ExecuteAllResponse(dashboardId=dashboard_id, results=[])

    # 2.并行执行所有面板 SQL
    async def _execute_single_panel(panel) -> PanelExecuteResponse:
        """执行单个面板 SQL，捕获异常返回错误信息"""
        # 安全校验
        try:
            _validate_sql_safety(panel.sql)
        except ValueError as e:
            logger.warning("SQL safety check failed, panel_id=%s, error=%s", panel.id, str(e))
            return PanelExecuteResponse(
                panelId=panel.id,
                title=panel.title,
                columns=[],
                rows=[],
                rowCount=0,
                executionTime=0,
                truncated=False,
                error=str(e),
            )

        # 执行 SQL
        try:
            executor = _get_query_executor()
            result = await executor.execute_sql(panel.sql)
            return PanelExecuteResponse(
                panelId=panel.id,
                title=panel.title,
                columns=[col.model_dump(by_alias=True) for col in result.columns],
                rows=result.rows,
                rowCount=result.row_count,
                executionTime=result.execution_time,
                truncated=result.truncated,
                error=None,
            )
        except Exception as e:
            logger.error("Panel SQL execution failed, panel_id=%s, error=%s", panel.id, str(e))
            return PanelExecuteResponse(
                panelId=panel.id,
                title=panel.title,
                columns=[],
                rows=[],
                rowCount=0,
                executionTime=0,
                truncated=False,
                error=str(e),
            )

    # 3.使用 asyncio.gather 并行执行，单面板失败不影响其他面板
    results = await asyncio.gather(
        *[_execute_single_panel(panel) for panel in panels]
    )

    # 4.统计执行结果
    success_count = sum(1 for r in results if r.error is None)
    logger.info("Execute-all completed, dashboard_id=%s, total=%d, success=%d, failed=%d",
                dashboard_id, len(results), success_count, len(results) - success_count)

    return ExecuteAllResponse(dashboardId=dashboard_id, results=list(results))
